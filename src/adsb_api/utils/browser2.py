import asyncio
import logging
import traceback
from contextlib import asynccontextmanager
from typing import Optional

import backoff
from async_timeout import timeout
from playwright.async_api import Page, async_playwright


class BrowserTabPool:
    def __init__(
        self,
        url: str,
        min_tabs: int = 4,
        max_tabs: int = 8,
        tab_ttl: int = 600,
        tab_max_uses: int = 200,
        before_add_to_pool_cb=None,
        before_return_to_pool_cb=None,
    ):
        self.p = None
        self.browser = None
        self.url = url
        self.min_tabs = min_tabs
        self.max_tabs = max_tabs
        self.tab_ttl = tab_ttl
        self.tab_max_uses = tab_max_uses
        self.pool = asyncio.Queue()
        self._active_tabs = set()
        self.before_add_to_pool_cb = before_add_to_pool_cb
        self.before_return_to_pool_cb = before_return_to_pool_cb
        self._background_task = None
        self._total_tabs = (
            0  # Tracks the total number of tabs being created, in the pool, and active
        )
        self.logger = logging.getLogger(__name__)
        logging.basicConfig(level=logging.INFO)  # Change the log level as necessary

    @backoff.on_exception(backoff.expo, Exception)
    async def initialize(self):
        self.logger.info("Initializing browser...")

        if not self.p:
            self.p = await async_playwright().__aenter__()
            self.logger.info("Playwright object created.")
        if self.browser:
            # Old browser detected. Clean up...
            self.logger.info("Old browser detected. Cleaning up...")
            try:
                self._active_tabs = set()
                self.pool = asyncio.Queue()
                self._total_tabs = 0
                await self.browser.close()
            except Exception as e:
                self.logger.error("Error while closing old browser: %s", e)

        self.browser = await self.p.chromium.connect_over_cdp(
            "ws://localhost:3000/?timeout=12000000"
        )
        for _ in range(self.min_tabs):
            try:
                await self._add_tab_to_pool()
            except Exception as e:
                self.logger.error("Error while adding tab to pool: %s", e)

    async def _add_tab_to_pool(self):
        # Check if browser is healthy, if not, return
        if not self.browser.is_connected():
            self.logger.error("Browser is not connected. Not adding tab to pool...")
        # Edge Case: Prevent the creation of more tabs than max_tabs
        if self._total_tabs >= self.max_tabs:
            return
        self._total_tabs += 1  # Increment _total_tabs when a new tab is being created
        self.logger.info("Total number of tabs after addition: %s", self._total_tabs)
        context = await self.browser.new_context(
            base_url=self.url,
            viewport={"width": 512, "height": 512},
            screen={"width": 512, "height": 512},
        )
        tab = await context.new_page()
        tab.__use_count = 0
        tab.__created_at = asyncio.get_event_loop().time()
        await tab.goto(self.url)

        if self.before_add_to_pool_cb:
            is_tab_good_to_go = await self.before_add_to_pool_cb(tab)
            if not is_tab_good_to_go:
                self.logger.error("Tab is not good to go. Removing tab from pool...")
                await self._remove_tab(tab)
                return
        self.logger.info(
            "Tab added to pool. Total number of tabs: %s / min: %s, max: %s",
            self._total_tabs,
            self.min_tabs,
            self.max_tabs,
        )

        self.pool.put_nowait(tab)
        self._active_tabs.add(tab)

    async def _remove_tab(self, tab, reason=None):
        self.logger.info("Removing tab from pool... Reason: %s", reason or "Unknown")

        if tab and not tab.is_closed():
            self.logger.info("Tab is open, proceeding to close it.")
            await tab.close()
        if tab in self._active_tabs:
            self._active_tabs.remove(tab)
        self._total_tabs -= 1

    async def is_tab_healthy(self, tab: Page):
        # Checks if the browser is connected and the tab is not closed
        return self.browser.is_connected() and not tab.is_closed()

    async def release_tab(self, tab):
        self.logger.info("Tab use count before release: %s", tab.__use_count)
        self.logger.info("Releasing tab back to pool...")
        if self.before_return_to_pool_cb:
            await self.before_return_to_pool_cb(tab)
        tab.__use_count += 1
        self.pool.put_nowait(tab)

    async def reconcile_pool(self):
        # Edge Case: Ensures that the pool always has at least min_tabs and not more than max_tabs
        if not self.browser or not self.browser.is_connected():
            self.logger.error("Browser is not connected. Not reconciling pool...")
            return
        while self._total_tabs < self.max_tabs:
            self.logger.info(
                "Current pool size: %s, total tabs: %s",
                self.pool.qsize(),
                self._total_tabs,
            )
            await self._add_tab_to_pool()

    async def enforce_tab_limits(self):
        # Edge Case: Closes tabs after a certain number of uses
        for tab in list(self._active_tabs):
            if tab.__use_count >= self.tab_max_uses:
                await self._remove_tab(tab, "maximum uses")
            if tab.__created_at + self.tab_ttl < asyncio.get_event_loop().time():
                await self._remove_tab(tab, "maximum age")

    @asynccontextmanager
    async def get_tab(self) -> Optional:
        self.logger.info("Retrieving tab from pool...")

        while True:
            self.logger.info("Waiting for tab...")
            tab = await self.pool.get()
            if await self.is_tab_healthy(tab):
                self.logger.info("Tab retrieved from pool!")
                break
            else:
                await self._remove_tab(tab, "Unhealthy hot")

        try:
            yield tab
        finally:
            if await self.is_tab_healthy(tab):
                await self.release_tab(tab)
            else:
                await self._remove_tab(tab, "Unhealthy after use")

    # Handle browser launch errors
    @backoff.on_exception(backoff.expo, Exception, max_tries=10)
    async def reconcile_browser(self):
        if not self.p or not self.browser or not self.browser.is_connected():
            # clean up existing tabs before creating new browser
            for tab in list(
                self._active_tabs
            ):  # make a copy of the set to avoid RuntimeError during iteration
                await self._remove_tab(tab)
            try:
                if not self.p:
                    self.p = await async_playwright().__aenter__()
                if not self.browser or not self.browser.is_connected():
                    self.browser = await self.p.chromium.connect_over_cdp(
                        "ws://localhost:3000/?timeout=12000000"
                    )
                await self.initialize()
            except Exception as e:
                self.logger.error("Failed to reconcile browser. Reason: %s", e)
                raise

    async def _background_task_fn(self):
        try:
            while True:
                self.logger.info("Running background task...")
                try:
                    await asyncio.gather(
                        self.reconcile_pool(),
                        self.enforce_tab_limits(),
                        self.reconcile_browser(),
                    )
                except Exception as e:
                    traceback.print_exc()
                    self.logger.error("Error during background task. Reason: %s", e)
                await asyncio.sleep(2)
        except asyncio.CancelledError:
            self.logger.info("Background task cancelled...")

    async def start(self):
        # Edge Case: Avoids multiple background tasks
        self.logger.info("Running background task...")
        if self._background_task:
            return
        self._background_task = asyncio.create_task(self._background_task_fn())

    async def stop(self):
        self.logger.info("Stopping background task...")

        # Edge Case: Gracefully handles stopping of the background task
        if self._background_task:
            self._background_task.cancel()
            self._background_task = None

    # Graceful shutdown
    async def shutdown(self):
        self.logger.info("Shutting down...")
        if self._background_task:
            self._background_task.cancel()
        for tab in self._active_tabs:
            await self._remove_tab(tab)
        await self.browser.close()


async def before_add_to_pool_cb(page):
    tasks = [
        page.route("**/api/0/routeset", lambda route: route.abort()),
        page.route("**/globeRates.json", lambda route: route.abort()),
        page.route("https://api.planespotters.net/*", lambda route: route.abort()),
        page.set_viewport_size({"width": 512, "height": 512}),
        page.goto("?screenshot&zoom=6&hideButtons&hideSidebar&lat=82&lon=-5"),
    ]
    try:
        with timeout(5):
            await asyncio.gather(*tasks)
    except asyncio.TimeoutError:
        traceback.print_exc()
        return False

    infoblock = page.locator("#selected_infoblock")

    tasks = [
        infoblock.wait_for(state="hidden", timeout=5000),
        page.wait_for_function("typeof deselectAllPlanes === 'function'", timeout=5000),
        page.wait_for_function("typeof OLMap === 'object'", timeout=5000),
    ]
    try:
        with timeout(10):
            await asyncio.gather(*tasks)
    except asyncio.TimeoutError:
        traceback.print_exc()
        return False
    js_magic = """
        // Initialize the global variables
        window._are_tiles_loaded = false;window._alol_loading = 0;window._alol_loaded = 0;

        function attachEventHandlers(layer) {
            if (layer.getSource && typeof layer.getSource === 'function') {
                let source = layer.getSource();
                if (source) {
                    source.on('tileloadstart', function() {
                        ++window._alol_loading;
                        window._are_tiles_loaded = false;
                        console.log(`Loading tiles: ${window._alol_loading}`);
                    });

                    source.on(['tileloadend', 'tileloaderror'], updateLoadingStatus);
                }
                else {
                    console.log(`Layer has no tileloadstart, tileloadend or tileloaderror event: ${layer.get('title')}`);
                }
            }
            else {
                console.log(`Layer has no source: ${layer.get('title')}`);
            }
        }

        function handleLayers(layers) {
            layers.forEach(layer => {
                layer instanceof ol.layer.Group
                    ? handleLayers(layer.getLayers().getArray())
                    : attachEventHandlers(layer);
            });
        }

        function updateLoadingStatus() {
            setTimeout(() => {
                ++window._alol_loaded;
                console.log(`Loaded tiles: ${window._alol_loaded}`);
                if (window._alol_loading === window._alol_loaded) {
                    console.log('All tiles loaded');
                    window._alol_loading = 0;
                    window._alol_loaded = 0;
                    window._are_tiles_loaded = true;
                }
            }, 100);
        }

        // Start processing layers
        handleLayers(OLMap.getLayers().getArray());
    """
    tasks = [
        page.evaluate(
            """$('#selected_infoblock')[0].remove(); function adjustInfoBlock(){}; toggleIsolation("on"); toggleMultiSelect("on"); reaper('all');"""
        ),
        page.evaluate(
            """
        planespottersAPI=false; useRouteAPI=false; setPictureVisibility();
        OLMap.addEventListener("moveend", () => {window._alol_mapcentered = true;});
        OLMap.addEventListener("rendercomplete", () => {window._alol_maploaded = true;});
        window._alol_mapcentered = false; window._alol_maploaded = false; window._are_tiles_loaded = false;
        """
        ),
        page.evaluate(js_magic),
    ]
    try:
        with timeout(10):
            await asyncio.gather(*tasks)
    except asyncio.TimeoutError:
        traceback.print_exc()
        return False
    return True


async def before_return_to_pool_cb(page):
    await page.evaluate(
        """
        reaper('all'); window._alol_mapcentered = false; window._alol_maploaded = false;
        window._are_tiles_loaded = false;window._alol_loading = 0;window._alol_loaded = 0;

        """
    )
