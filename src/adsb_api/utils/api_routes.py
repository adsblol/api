from fastapi import APIRouter, Response
from adsb_api.utils.models import PrettyJSONResponse
from adsb_api.utils.dependencies import redisVRS
from adsb_api.utils.models import PlaneList
from adsb_api.utils.plausible import plausible
import asyncio

CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "POST, OPTIONS",
    "Access-Control-Allow-Headers": "access-control-allow-origin,content-type",
}

router = APIRouter(prefix="/api", tags=["v0"])


async def calc_plausible(route, lat: str, lng: str) -> bool:
    """Calculate if route is plausible for given position (non-blocking)."""
    for i in range(len(route.get("_airports", [])) - 1):
        a, b = route["_airports"][i], route["_airports"][i + 1]
        is_plausible, _ = await plausible(lat, lng, f"{a['lat']:.5f}", f"{a['lon']:.5f}", f"{b['lat']:.5f}", f"{b['lon']:.5f}")
        if is_plausible:
            return True
    return False


async def get_route_cached_or_fetch(callsign: str, lat: str, lng: str) -> dict:
    """Get route from cache or fetch, with plausible calculation."""
    if cached := await redisVRS.get_cached_route(callsign):
        return cached

    route = await redisVRS.get_route(callsign)
    if route["airport_codes"] != "unknown":
        route["plausible"] = await calc_plausible(route, lat, lng)
        await redisVRS.cache_route(callsign, route["plausible"], route)
    return route


@router.get("/0/airport/{icao}", response_class=PrettyJSONResponse, tags=["v0"],
            summary="Airports by ICAO", description="Data by https://github.com/vradarserver/standing-data/")
async def api_airport(icao: str):
    return await redisVRS.get_airport(icao)


@router.get("/0/route/{callsign}/{lat}/{lng}", response_class=PrettyJSONResponse, tags=["v0"],
            summary="Route plus plausible flag", description="Data by https://github.com/vradarserver/standing-data/",
            include_in_schema=False)
async def api_route3(callsign: str, lat: str, lng: str):
    return PrettyJSONResponse(content=await get_route_cached_or_fetch(callsign, lat, lng), headers=CORS_HEADERS)


@router.get("/0/route/{callsign}", response_class=PrettyJSONResponse, tags=["v0"],
            summary="Route for callsign", description="Data by https://github.com/vradarserver/standing-data/",
            include_in_schema=False)
async def api_route(callsign: str):
    await asyncio.sleep(5)
    return Response(status_code=302, headers={"Location": f"https://vrs-standing-data.adsb.lol/routes/{callsign[:2]}/{callsign}.json#deprecated"})


@router.post("/0/routeset", response_class=PrettyJSONResponse, tags=["v0"])
async def api_routeset(planeList: PlaneList):
    if not planeList.planes or len(planeList.planes) > 100:
        return Response(status_code=400)

    callsigns = [p.callsign for p in planeList.planes]
    cached = await redisVRS.get_cached_routes_bulk(callsigns)
    uncached = [cs for cs in callsigns if not cached.get(cs)]
    fetched = await redisVRS.get_routes_bulk(uncached) if uncached else {}

    # Merge routes, track uncached for parallel plausible
    routes = {}
    tasks = []
    for p in planeList.planes:
        r = cached.get(p.callsign) or fetched.get(p.callsign)
        if not r:
            r = {"callsign": p.callsign, "airport_codes": "unknown", "_airports": []}
        elif p.callsign in uncached and r["airport_codes"] != "unknown":
            tasks.append((p.callsign, r, p.lat, p.lng))
        routes[p.callsign] = r

    # Parallel plausible + cache
    if tasks:
        for (cs, r, lat, lng), is_plausible in zip(tasks, await asyncio.gather(*(calc_plausible(r, lat, lng) for _, r, lat, lng in tasks))):
            r["plausible"] = is_plausible
        await asyncio.gather(*(redisVRS.cache_route(cs, routes[cs]["plausible"], routes[cs]) for cs, _, _, _ in tasks))

    return PrettyJSONResponse(content=list(routes.values()), headers=CORS_HEADERS)


@router.options("/0/routeset", include_in_schema=False)
async def api_routeset_options():
    return Response(status_code=200, headers=CORS_HEADERS)
