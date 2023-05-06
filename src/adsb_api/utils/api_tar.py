# Playwright API to get 256x256 screenshots of the ICAO
# boom!

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse
from fastapi_cache.decorator import cache
from playwright.async_api import async_playwright
import tempfile
import time

router = APIRouter(
    prefix="/",
    tags=["v0"],
)


@app.get("/0/screenshot")
@cache(expire=60)
async def get_screenshot(request: Request, icao: str):
    url = f"http://tar1090-prod/?icao={icao}&hideButtons&hideSidebar"
    async with async_playwright() as p:
        browser = await p.chromium.connect("ws://playwright:3000")
        page = await browser.new_page()

        width, height = 1024, 1024
        await page.set_viewport_size({"width": width, "height": height})
        await page.goto(url)
        await page.wait_for_selector(".ol-layer")
        await page.wait_for_load_state("networkidle")
        # sleep for 5 seconds to let the map load
        await page.wait_for_timeout(5000)
        clip = {
            "x": width / 2 - 128,
            "y": height / 2 - 128,
            "width": 256,
            "height": 256,
        }

        with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as tmp_file:
            page.screenshot(path=tmp_file.name, clip=clip)
            # close page?
            await page.close()
            await browser.close()

        time_end = time.time()
        print(f"Screenshot took {time_end - time_start:.2f}s")
        # Return the screenshot as a PNG
        return FileResponse(
            tmp_file.name, media_type="image/png", filename=f"{icao}.png"
        )
