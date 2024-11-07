from fastapi import APIRouter, Response
from adsb_api.utils.models import PrettyJSONResponse
from adsb_api.utils.dependencies import redisVRS
from adsb_api.utils.models import PlaneList
from adsb_api.utils.plausible import plausible
import asyncio
import time

CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "POST, OPTIONS",
    "Access-Control-Allow-Headers": "access-control-allow-origin,content-type",
}


router = APIRouter(
    prefix="/api",
    tags=["v0"],
)


@router.get(
    "/0/airport/{icao}",
    response_class=PrettyJSONResponse,
    tags=["v0"],
    summary="Airports by ICAO",
    description="Data by https://github.com/vradarserver/standing-data/",
)
async def api_airport(icao: str):
    """
    Return information about an airport.
    """
    return await redisVRS.get_airport(icao)

route_cache = {}
route_cache_next_prune = 0

async def pruneRouteCache():
    now = time.time()
    for key in list(route_cache.keys()):
        value = route_cache[key]
        route, validUntil = value
        if now > validUntil:
            del route_cache[key]
    print(f"PRUNED route_cache, new item count: {len(plausible_cache)} (took {round((time.time() - now) * 1000, 3)} ms)")

async def get_route_for_callsign_lat_lng(callsign: str, lat: str, lng: str):

    # cache routes in the worker for 5 minutes
    validTime = 300

    now = time.time()
    global route_cache_next_prune
    if now > route_cache_next_prune:
        route_cache_next_prune = now + validTime / 2
        await pruneRouteCache()

    key = callsign
    cached, validUntil = route_cache.get(key, (None, 0))
    if now < validUntil:
        route = cached
    else:
        route = await redisVRS.get_route(callsign)
        route_cache[key] = (route, now + validTime)

    is_plausible = await redisVRS.is_plausible(callsign)
    if is_plausible:
        route["plausible"] = is_plausible
        return route

    if route["airport_codes"] == "unknown":
        return route
    a = 0
    is_plausible = False
    # print(f"==> {callsign}:", end=" ")
    while a < len(route["_airports"]) - 1:
        b = a + 1
        airportA = route["_airports"][a]
        airportB = route["_airports"][b]
        # print(f"checking {airportA['iata']}-{airportB['iata']}", end=" ")
        is_plausible, _ = plausible(
            lat,
            lng,
            f"{airportA['lat']:.5f}",
            f"{airportA['lon']:.5f}",
            f"{airportB['lat']:.5f}",
            f"{airportB['lon']:.5f}",
        )
        a = b  # try the next pair in mult segment routes
    print(f"==> {callsign} plausible: {is_plausible} {type(is_plausible)}")
    await redisVRS.set_plausible(callsign, int(is_plausible))
    route["plausible"] = is_plausible
    return route


@router.get(
    "/0/route/{callsign}/{lat}/{lng}",
    response_class=PrettyJSONResponse,
    tags=["v0"],
    summary="Route plus plausible flag for a specific callsign and position",
    description="Data by https://github.com/vradarserver/standing-data/",
    include_in_schema=False,
)
async def api_route3(
    callsign: str,
    lat: str = None,
    lng: str = None,
):
    """
    Return information about a route and plane position.
    Return value includes a guess whether
    this is a plausible route,given plane position.
    """
    route = await get_route_for_callsign_lat_lng(callsign, lat, lng)
    return PrettyJSONResponse(content=route, headers=CORS_HEADERS)


@router.get(
    "/0/route/{callsign}",
    response_class=PrettyJSONResponse,
    tags=["v0"],
    summary="Route for a specific callsign",
    description="Data by https://github.com/vradarserver/standing-data/",
    include_in_schema=False,
)
async def api_route(
    callsign: str,
):
    """
    Return information about a route.
    """
    new_url = f"https://vrs-standing-data.adsb.lol/routes/{callsign[0:2]}/{callsign}.json#this-API-has-been-deprecated-please-use-this-new-URL-directly"
    await asyncio.sleep(5)
    return Response(status_code=302, headers={"Location": new_url})


@router.post(
    "/0/routeset",
    response_class=PrettyJSONResponse,
    tags=["v0"],
    summary="Routes for a list of aircraft callsigns",
    description="""Look up routes for multiple planes at once.
    Data by https://github.com/vradarserver/standing-data/""",
)
async def api_routeset(planeList: PlaneList):
    """
    Return route information on a list of planes / positions
    """
    # print(planeList)
    response = []
    if len(planeList.planes) > 100:
        return Response(status_code=400)
    tasks = []
    for plane in planeList.planes:
        tasks.append(
            get_route_for_callsign_lat_lng(plane.callsign, plane.lat, plane.lng)
        )
    response = [x for x in await asyncio.gather(*tasks)]
    return PrettyJSONResponse(content=response, headers=CORS_HEADERS)


@router.options("/0/routeset", include_in_schema=False)
async def api_routeset_options():
    return Response(status_code=200, headers=CORS_HEADERS)
