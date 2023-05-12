from fastapi import APIRouter, Response
from adsb_api.utils.models import PrettyJSONResponse
from adsb_api.utils.dependencies import redisVRS
from adsb_api.utils.models import PlaneList
from adsb_api.utils.plausible import plausible

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
    description="Data by https://github.com/vradarserver/standing-data/",
)
async def api_airport(icao: str):
    """
    Return information about an airport.
    """
    return await redisVRS.get_airport(icao)


async def get_route_for_callsign_lat_lng(callsign: str, lat: str, lng: str):
    route = await redisVRS.get_route(callsign)
    if route["airport_codes"] != "unknown":
        a = 0
        is_plausible = False
        distance = 0
        #print(f"==> {callsign}:", end=" ")
        while a < len(route["_airports"]) - 1:
            b = a + 1
            airportA = route["_airports"][a]
            airportB = route["_airports"][b]
            #print(f"checking {airportA['iata']}-{airportB['iata']}", end=" ")
            is_plausible, distance = plausible(
                lat,
                lng,
                f"{airportA['lat']:.5f}",
                f"{airportA['lon']:.5f}",
                f"{airportB['lat']:.5f}",
                f"{airportB['lon']:.5f}",
            )
            if is_plausible:
                redisVRS.set_plausible(callsign)
                break
            a = b  # try the next pair in mult segment routes

        if not is_plausible:
            #print(f"implausible {lat}/{lng} (dist {distance}nm)")
            ...
        else:
            #print(" [ok]")
            ...
        route["plausible"] = is_plausible
    return route


@router.get(
    "/0/route/{callsign}/{lat}/{lng}",
    response_class=PrettyJSONResponse,
    tags=["v0"],
    description="Data by https://github.com/vradarserver/standing-data/",
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
    description="Data by https://github.com/vradarserver/standing-data/",
)
async def api_route(
    callsign: str,
):
    """
    Return information about a route.
    """
    route = await redisVRS.get_route(callsign)
    return PrettyJSONResponse(content=route, headers=CORS_HEADERS)


@router.post(
    "/0/routeset",
    response_class=PrettyJSONResponse,
    tags=["v0"],
    description="""Look up routes for multiple planes at once.
    Data by https://github.com/vradarserver/standing-data/""",
)
async def api_routeset(planeList: PlaneList):
    """
    Return route information on a list of planes / positions
    """
    #print(planeList)
    response = []
    if len(planeList.planes) > 100:
        return Response(status_code=400)
    for plane in planeList.planes:
        route = await get_route_for_callsign_lat_lng(
            plane.callsign, plane.lat, plane.lng
        )
        response.append(route)
    return PrettyJSONResponse(content=response, headers=CORS_HEADERS)

@router.options("/0/routeset")
async def api_routeset_options():
    return Response(status_code=200, headers=CORS_HEADERS)
