# Playwright API to get 256x256 screenshots of the ICAO
# boom!

from fastapi import APIRouter, Request
from fastapi.responses import Response, FileResponse
from fastapi_cache.decorator import cache
from playwright.async_api import async_playwright
from async_timeout import timeout

from adsb_api.utils.dependencies import redisVRS, browser
import traceback
import time
import asyncio
import base64

router = APIRouter(
    prefix="/0",
    tags=["v0"],
)


def get_map_zoom(groundspeed):
    if groundspeed <= 0:
        return 6
    zoom_levels = {300: 6, 200: 7, 175: 9, 150: 12, 125: 11, 75: 12, 50: 13, 0: 14}
    for speed in sorted(zoom_levels.keys(), reverse=True):
        if groundspeed >= speed:
            return zoom_levels[speed]


@router.get(
    "/screenshot/",
    responses={200: {"content": {"image/png": {}}}},
    response_class=Response,
)
@router.get(
    "/screenshot/{icao}",
    responses={200: {"content": {"image/png": {}}}},
    response_class=Response,
)
async def get_new_screenshot(
    icao: str,
    trace: bool = False,
    gs: float = 0.0,
    min_lat: float = False,
    min_lon: float = False,
    max_lat: float = False,
    max_lon: float = False,
) -> Response:
    icaos = icao.lower().split(",")
    for icao in icaos:
        if len(icao) == 6:
            if all(c in "0123456789abcdef" for c in icao):
                continue
        elif len(icao) == 7:
            if icao[0] != "~":
                return Response(status_code=400)
            if all(c in "0123456789abcdef" for c in icao[1:]):
                continue
        return Response(status_code=400)

    gs_zoom = get_map_zoom(gs)
    # for the cache key, cut off the to 2 decimal places
    icaos_str = ":".join(icaos)
    cache_key = f"screenshot:{icaos_str}:{min_lat:.1f}:{min_lon:.1f}:{max_lat:.1f}:{max_lon:.1f}"

    if not trace:
        if cached_screenshot := await redisVRS.redis.get(cache_key):
            print(f"cached! {icao}")
            cached_screenshot = base64.b64decode(cached_screenshot)
            return Response(cached_screenshot, media_type="image/png")

        slept = 0

        while slept < 60:
            lock = await redisVRS.redis.setnx(f"{cache_key}:lock", 1)
            if lock:
                # set expiry
                await redisVRS.redis.expire(f"{cache_key}:lock", 60)
                break

            screen = await redisVRS.redis.get(cache_key)

            if screen:
                break
            else:
                slept += 1
                print(f"waiting for lock or screenshot {icaos} {gs} {gs_zoom} {slept}")
                await asyncio.sleep(1)

        if screen := await redisVRS.redis.get(cache_key):
            print(f"cached! {icao}")
            screen = base64.b64decode(screen)
            return Response(screen, media_type="image/png")

    # otherwise, let's get to work
    print(f"locked! {icao} {trace} {gs_zoom}")

    # we want to set map zoom based on the groundspeed
    # 0-100: 13
    # 100-200: 10
    # 200+: 7
    # 300+: 5

    # run this in asyncio-timeout context
    try:
        async with browser.get_tab() as tab:
            async with timeout(10):
                if trace:
                    await tab.context.tracing.start(screenshots=True, snapshots=True)
                try:
                    start_js = "window._alol_mapcentered = false;window._alol_maploaded = false;window._alol_viewadjusted = false;window._are_tiles_loaded = false;window._alol_loading = 0; window._alol_loaded = 0;window._alol_viewadjusted=false;"
                    other_planes_js = "".join(
                        [
                            f'selectPlaneByHex("{icao}", {{noDeselect: true}});'
                            for icao in icaos
                        ]
                    )
                    if min_lat and min_lon and max_lat and max_lon:
                        # function adjustViewSelectedPlanes(maxLat, maxLon, minLat, minLon) {
                        other_planes_js += f"""
                            window.__alol_adjustViewSelectedPlanes = function() {{
                                let maxLat = {max_lat}; let maxLon = {max_lon}; let minLat = {min_lat}; let minLon = {min_lon};
                                let topRight = ol.proj.fromLonLat([maxLon, maxLat]);
                                let bottomLeft = ol.proj.fromLonLat([minLon, minLat]);
                                let newCenter = [(topRight[0] + bottomLeft[0]) / 2, (topRight[1] + bottomLeft[1]) / 2];
                                let longerSide = Math.max(Math.abs(topRight[0] - bottomLeft[0]), Math.abs(topRight[1] - bottomLeft[1]));
                                longerSide = Math.max(longerSide, 60 * 1000);
                                let newZoom = Math.floor(Math.log2(6e7 / longerSide));
                                console.log('newCenter: ' + newCenter);
                                console.log('newZoom: ' + newZoom);
                                if(newZoom > 13) newZoom = 13;
                                OLMap.getView().setCenter(newCenter);
                                OLMap.getView().setZoom(newZoom);
                                window._alol_viewadjusted = true;
                            }};
                            window.__alol_adjustViewSelectedPlanes();
                        """
                    print(f"js: {start_js + other_planes_js}")
                    await tab.evaluate(start_js + other_planes_js)

                    # wait ...

                    try:
                        await tab.wait_for_function(
                            """
                            window._alol_maploaded === true &&
                            window._alol_mapcentered === true &&
                            window._are_tiles_loaded === true &&
                            window._alol_viewadjusted === true &&
                            SelPlanes.length > 0 &&
                            window.planesAreGood()
                            """,
                            timeout=10000,
                            polling=25,
                        )

                    except Exception as e:
                        traceback.print_exc()
                        print(f"{icao} waiting: {e}")
                except Exception as e:
                    traceback.print_exc()
                    print(f"{icao} inner: {e}")
                screenshot = await tab.screenshot(type="png")
                screenshot_b64 = base64.b64encode(screenshot).decode()
                if not trace:
                    await redisVRS.redis.set(cache_key, screenshot_b64, ex=20)
                    await redisVRS.redis.delete(f"{cache_key}:lock")
                    return Response(screenshot, media_type="image/png")
                else:
                    await tab.context.tracing.stop(path=f"/tmp/trace-{icao}.zip")
                    return FileResponse(
                        f"/tmp/trace-{icao}.zip", media_type="application/zip"
                    )

    except Exception as e:
        traceback.print_exc()
        print(f"{icao} outer: {e}")
        await redisVRS.redis.delete(f"{cache_key}:lock")
        return Response("sorry, no screenshots", media_type="text/plain")


@router.get(
    "/screenshot2/{icao}",
    responses={200: {"content": {"image/png": {}}}},
    response_class=Response,
)
async def get_new_screenshot2(
    icao: str,
    trace: bool = False,
    gs: float = 0.0,
    min_lat: float = False,
    min_lon: float = False,
    max_lat: float = False,
    max_lon: float = False,
) -> Response:
    icaos = icao.lower().split(",")
    for icao in icaos:
        if len(icao) == 6:
            if all(c in "0123456789abcdef" for c in icao):
                continue
        elif len(icao) == 7:
            if icao[0] != "~":
                return Response(status_code=400)
            if all(c in "0123456789abcdef" for c in icao[1:]):
                continue
        return Response(status_code=400)

    try:
        async with browser.get_tab() as tab:
            async with timeout(10):
                if trace:
                    await tab.context.tracing.start(screenshots=True, snapshots=True)
                try:
                    start_js = "window._alol_mapcentered = false;window._alol_maploaded = false;window._alol_viewadjusted = false;window._are_tiles_loaded = false;window._alol_loading = 0; window._alol_loaded = 0;window._alol_viewadjusted=false;"
                    other_planes_js = "".join(
                        [
                            f'selectPlaneByHex("{icao}", {{noDeselect: true}});'
                            for icao in icaos
                        ]
                    )
                    if min_lat and min_lon and max_lat and max_lon:
                        # function adjustViewSelectedPlanes(maxLat, maxLon, minLat, minLon) {
                        other_planes_js += f"""
                            window.adjustViewSelectedPlanes();
                        """
                    else:
                        other_planes_js += "window._alol_viewadjusted = true;"
                    print(f"js: {start_js + other_planes_js}")
                    await tab.evaluate(start_js + other_planes_js)

                    # wait ...

                    try:
                        await tab.wait_for_function(
                            f"""
                            window._alol_maploaded === true &&
                            window._alol_mapcentered === true &&
                            window._are_tiles_loaded === true &&
                            window._alol_viewadjusted === true &&
                            window.planesAreGood()
                            """,
                            timeout=10000,
                            polling=25,
                        )
                    except Exception as e:
                        traceback.print_exc()
                        print(f"{icao} waiting: {e}")
                except Exception as e:
                    traceback.print_exc()
                    print(f"{icao} inner: {e}")
                screenshot = await tab.screenshot(type="png")
                if trace:
                    await tab.context.tracing.stop(path=f"/tmp/trace-{icao}.zip")
                    return FileResponse(
                        f"/tmp/trace-{icao}.zip", media_type="application/zip"
                    )
                return Response(screenshot, media_type="image/png")
    except Exception as e:
        traceback.print_exc()
        print(f"{icao} outer: {e}")
        return Response("sorry, no screenshots", media_type="text/plain")
