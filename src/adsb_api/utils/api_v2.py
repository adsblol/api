from fastapi import APIRouter, Request, Path
from fastapi.responses import Response
from fastapi_cache.decorator import cache

from adsb_api.utils.dependencies import provider
from adsb_api.utils.models import V2Response_Model
from adsb_api.utils.settings import REDIS_TTL

router = APIRouter(
    prefix="/v2",
    tags=["v2"],
    responses={200: {"model": V2Response_Model}},
)


@router.get(
    "/pia",
    summary="Aircrafts with PIA addresses (Privacy ICAO Address)",
    description="Returns all aircraft with [PIA](https://nbaa.org/aircraft-operations/security/privacy/privacy-icao-address-pia/) addresses.",
)
async def v2_pia(request: Request) -> Response:
    params = ["all", "filter_pia"]

    res = await provider.ReAPI.request(params=params, client_ip=request.client.host)
    return Response(res, media_type="application/json")


@router.get(
    "/mil",
    summary="Military registered aircrafts",
    description="Returns all military registered aircraft.",
)
async def v2_mil(request: Request) -> Response:
    params = ["all", "filter_mil"]

    res = await provider.ReAPI.request(params=params, client_ip=request.client.host)
    return Response(res, media_type="application/json")


@router.get(
    "/ladd",
    summary="Aircrafts on LADD (Limiting Aircraft Data Displayed)",
    description="Returns all aircrafts on [LADD](https://www.faa.gov/pilots/ladd) filter.",
)
async def v2_ladd(
    request: Request,
) -> Response:
    params = ["all", "filter_ladd"]

    res = await provider.ReAPI.request(params=params, client_ip=request.client.host)
    return Response(res, media_type="application/json")


@router.get(
    "/squawk/{squawk}",
    summary="Aircrafts with specific squawk (1200, 7700, etc.)",
    description='Returns aircraft filtered by "squawk" [transponder code](https://en.wikipedia.org/wiki/List_of_transponder_codes).',
)
@router.get(
    "/sqk/{squawk}",
    summary="Aircrafts with specific squawk (1200, 7700, etc.)",
    description='Returns aircraft filtered by "squawk" [transponder code](https://en.wikipedia.org/wiki/List_of_transponder_codes).',
)
async def v2_squawk_filter(
    # Allow custom examples
    request: Request,
    squawk: str = Path(default=..., example="1200"),
) -> Response:
    params = ["all", f"filter_squawk={squawk}"]

    res = await provider.ReAPI.request(params=params, client_ip=request.client.host)
    return Response(res, media_type="application/json")


@router.get(
    "/type/{aircraft_type}",
    summary="Aircrafts of specific type (A320, B738)",
    description="Returns aircraft filtered by [aircraft type designator code](https://en.wikipedia.org/wiki/List_of_aircraft_type_designators).",
)
async def v2_type_filter(
    request: Request,
    aircraft_type: str = Path(default=..., example="A320"),
) -> Response:
    params = [f"find_type={aircraft_type}"]

    res = await provider.ReAPI.request(params=params, client_ip=request.client.host)
    return Response(res, media_type="application/json")


@router.get(
    "/registration/{registration}",
    summary="Aircrafts with specific registration (G-KELS)",
    description="Returns aircraft filtered by [aircarft registration code](https://en.wikipedia.org/wiki/Aircraft_registration).",
)
@router.get(
    "/reg/{registration}",
    summary="Aircrafts with specific registration (G-KELS)",
    description="Returns aircraft filtered by [aircarft registration code](https://en.wikipedia.org/wiki/Aircraft_registration).",
)
async def v2_reg_filter(
    request: Request,
    registration: str = Path(default=..., example="G-KELS"),
) -> Response:
    params = [f"find_reg={registration}"]

    res = await provider.ReAPI.request(params=params, client_ip=request.client.host)
    return Response(res, media_type="application/json")


@router.get(
    "/hex/{icao_hex}",
    summary="Aircrafts with specific transponder hex code (4CA87C)",
    description="Returns aircraft filtered by [transponder hex code](https://en.wikipedia.org/wiki/Aviation_transponder_interrogation_modes#ICAO_24-bit_address).",
)
@router.get(
    "/icao/{icao_hex}",
    summary="Aircrafts with specific transponder hex code (4CA87C)",
    description="Returns aircraft filtered by [transponder hex code](https://en.wikipedia.org/wiki/Aviation_transponder_interrogation_modes#ICAO_24-bit_address).",
)
async def v2_hex_filter(
    request: Request,
    icao_hex: str = Path(default=..., example="4CA87C"),
) -> Response:
    params = [f"find_hex={icao_hex}"]

    res = await provider.ReAPI.request(params=params, client_ip=request.client.host)
    return Response(res, media_type="application/json")


@router.get(
    "/callsign/{callsign}",
    summary="Aircrafts with specific callsign (JBU1942)",
    description="Returns aircraft filtered by [callsign](https://en.wikipedia.org/wiki/Aviation_call_signs).",
)
async def v2_callsign_filter(
    request: Request,
    callsign: str = Path(default=..., example="JBU1942"),
) -> Response:
    params = [f"find_callsign={callsign}"]

    res = await provider.ReAPI.request(params=params, client_ip=request.client.host)
    return Response(res, media_type="application/json")


@router.get(
    "/point/{lat}/{lon}/{radius}",
    summary="Aircrafts surrounding a point (lat, lon) up to 250nm",
    description="Returns aircraft located in a circle described by the latitude and longtidude of its center and its radius.",
)
@router.get(
    "/lat/{lat}/lon/{lon}/dist/{radius}",
    summary="Aircrafts surrounding a point (lat, lon) up to 250nm",
    description="Returns aircraft located in a circle described by the latitude and longtidude of its center and its radius.",
)
async def v2_point(
    request: Request,
    lat: float = Path(..., example=51.89508, ge=-90, le=90),
    lon: float = Path(..., example=2.79437, ge=-180, le=180),
    radius: int = Path(..., example=250, ge=0, le=250),
) -> Response:
    radius = min(radius, 250)

    res = await provider.ReAPI.request(
        params=[f"circle={lat},{lon},{radius}"], client_ip=request.client.host
    )
    return Response(res, media_type="application/json")


# closest
@router.get(
    "/closest/{lat}/{lon}/{radius}",
    summary="Single aircraft closest to a point (lat, lon)",
    description="Returns the closest aircraft to a point described by the latitude and longtidude within a radius up to 250nm.",
)
async def v2_closest(
    request: Request,
    lat: float = Path(..., example=51.89508, ge=-90, le=90),
    lon: float = Path(..., example=2.79437, ge=-180, le=180),
    radius: int = Path(..., example=250, ge=0, le=250),
) -> Response:
    res = await provider.ReAPI.request(
        params=[f"closest={lat},{lon},{radius}"], client_ip=request.client.host
    )
    return Response(res, media_type="application/json")
