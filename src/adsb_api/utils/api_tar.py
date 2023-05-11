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
    icao: str, trace: bool = False, gs: float = 0.0
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

    if not trace:
        if cached_screenshot := await redisVRS.redis.get(
            f"screenshot:{icao}:{gs_zoom}"
        ):
            print(f"cached! {icao}")
            cached_screenshot = base64.b64decode(cached_screenshot)
            return Response(cached_screenshot, media_type="image/png")

        slept = 0

        while slept < 60:
            lock = await redisVRS.redis.setnx(f"screenshot:{icao}:{gs_zoom}:lock", 1)
            if lock:
                # set expiry
                await redisVRS.redis.expire(f"screenshot:{icao}:{gs_zoom}:lock", 60)
                break

            screen = await redisVRS.redis.get(f"screenshot:{icao}:{gs_zoom}")

            if screen:
                break
            else:
                slept += 1
                print(f"waiting for lock or screenshot {icao} {gs} {gs_zoom} {slept}")
                await asyncio.sleep(1)

        if screen := await redisVRS.redis.get(f"screenshot:{icao}:{gs}"):
            print(f"cached! {icao} {gs} {gs_zoom}")
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
                    start_js = "window._alol_mapcentered = false; window._alol_maploaded = false; window._are_tiles_loaded = false;window._alol_loading = 0;window._alol_loaded = 0;"
                    follow_plane_js = f'selectPlaneByHex("{icaos[0]}", {{noDeselect: true, zoom: {gs_zoom}, follow: true}});'
                    other_planes_js = "".join(
                        [
                            f'selectPlaneByHex("{icao}", {{noDeselect: true}});'
                            for icao in icaos[1:]
                        ]
                    )
                    print(f"js: {start_js + follow_plane_js + other_planes_js}")
                    await tab.evaluate(start_js + follow_plane_js + other_planes_js)

                    # wait ...

                    try:
                        await tab.wait_for_function(
                            f"""
                            window._alol_maploaded === true &&
                            window._alol_mapcentered === true &&
                            window._are_tiles_loaded === true
                            """,
                            timeout=10000,
                            polling=300,
                        )
                        await tab.wait_for_function(
                            """SelectedPlane != null && SelectedPlane.trace != null""",
                            timeout=2000,
                            polling=300,
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
                    await redisVRS.redis.set(
                        f"screenshot:{icao}:{gs_zoom}", screenshot_b64, ex=20
                    )
                    await redisVRS.redis.delete(f"screenshot:{icao}:{gs_zoom}:lock")
                    return Response(screenshot, media_type="image/png")
                else:
                    await tab.context.tracing.stop(path=f"/tmp/trace-{icao}.zip")
                    return FileResponse(
                        f"/tmp/trace-{icao}.zip", media_type="application/zip"
                    )

    except Exception as e:
        traceback.print_exc()
        print(f"{icao} outer: {e}")
        await redisVRS.redis.delete(f"screenshot:{icao}:{gs_zoom}:lock")
        return Response("sorry, no screenshots", media_type="text/plain")
