from fastapi import APIRouter, Header, Query, Path


from .dependencies import provider
from .models import PrettyJSONResponse, V2Response_Model
from typing import Any

router = APIRouter(
    prefix="/v2",
    tags=["v2"],
    responses={200: {"model": V2Response_Model}},
)


@router.get(
    "/pia",
    response_class=PrettyJSONResponse,
    summary="Aircrafts with PIA addresses (Privacy ICAO Address)",
    description="Returns all aircraft with [PIA](https://nbaa.org/aircraft-operations/security/privacy/privacy-icao-address-pia/) addresses.",
)
async def v2_pia(
    x_original_forwarded_for: str
    | None = Header(default=None, include_in_schema=False),
) -> V2Response_Model:

    client_ip = x_original_forwarded_for
    params = ["all", "filter_pia"]

    res = await provider.ReAPI.request(params=params, client_ip=client_ip)
    return res


@router.get(
    "/mil",
    response_class=PrettyJSONResponse,
    summary="Military registered aircrafts",
    description="Returns all military registered aircraft.",
)
async def v2_mil(
    x_original_forwarded_for: str
    | None = Header(default=None, include_in_schema=False),
) -> V2Response_Model:

    client_ip = x_original_forwarded_for
    params = ["all", "filter_mil"]

    res = await provider.ReAPI.request(params=params, client_ip=client_ip)
    return res


@router.get(
    "/ladd",
    response_class=PrettyJSONResponse,
    summary="Aircrafts on LADD (Limiting Aircraft Data Displayed)",
    description="Returns all aircrafts on [LADD](https://www.faa.gov/pilots/ladd) filter.",
)
async def v2_ladd(
    x_original_forwarded_for: str
    | None = Header(default=None, include_in_schema=False),
) -> V2Response_Model:

    client_ip = x_original_forwarded_for
    params = ["all", "filter_ladd"]

    res = await provider.ReAPI.request(params=params, client_ip=client_ip)
    return res


@router.get(
    "/squawk/{squawk}",
    response_class=PrettyJSONResponse,
    summary="Aircrafts with specific squawk (1200, 7700, etc.)",
    description='Returns aircraft filtered by "squawk" [transponder code](https://en.wikipedia.org/wiki/List_of_transponder_codes).',
)
async def v2_squawk_filter(
    # Allow custom examples
    squawk: str = Path(default=..., example="1200"),
    x_original_forwarded_for: str
    | None = Header(default=None, include_in_schema=False),
) -> V2Response_Model:

    client_ip = x_original_forwarded_for
    params = ["all", f"filter_squawk={squawk}"]

    res = await provider.ReAPI.request(params=params, client_ip=client_ip)
    return res


@router.get(
    "/type/{aircraft_type}",
    response_class=PrettyJSONResponse,
    summary="Aircrafts of specific type (A320, B738)",
    description="Returns aircraft filtered by [aircraft type designator code](https://en.wikipedia.org/wiki/List_of_aircraft_type_designators).",
)
async def v2_type_filter(
    aircraft_type: str = Path(default=..., example="A320"),
    x_original_forwarded_for: str
    | None = Header(default=None, include_in_schema=False),
) -> V2Response_Model:

    client_ip = x_original_forwarded_for
    params = [f"find_type={aircraft_type}"]

    res = await provider.ReAPI.request(params=params, client_ip=client_ip)
    return res


@router.get(
    "/reg/{registration}",
    response_class=PrettyJSONResponse,
    summary="Aircrafts with specific registration (G-KELS)",
    description="Returns aircraft filtered by [aircarft registration code](https://en.wikipedia.org/wiki/Aircraft_registration).",
)
async def v2_reg_filter(
    registration: str = Path(default=..., example="G-KELS"),
    x_original_forwarded_for: str
    | None = Header(default=None, include_in_schema=False),
) -> V2Response_Model:

    client_ip = x_original_forwarded_for
    params = [f"find_reg={registration}"]

    res = await provider.ReAPI.request(params=params, client_ip=client_ip)
    return res


@router.get(
    "/hex/{icao_hex}",
    response_class=PrettyJSONResponse,
    summary="Aircrafts with specific transponder hex code (4CA87C)",
    description="Returns aircraft filtered by [transponder hex code](https://en.wikipedia.org/wiki/Aviation_transponder_interrogation_modes#ICAO_24-bit_address).",
)
async def v2_hex_filter(
    icao_hex: str = Path(default=..., example="4CA87C"),
    x_original_forwarded_for: str
    | None = Header(default=None, include_in_schema=False),
) -> V2Response_Model:

    client_ip = x_original_forwarded_for
    params = [f"find_hex={icao_hex}"]

    res = await provider.ReAPI.request(params=params, client_ip=client_ip)
    return res


@router.get(
    "/callsign/{callsign}",
    response_class=PrettyJSONResponse,
    summary="Aircrafts with specific callsign (JBU1942)",
    description="Returns aircraft filtered by [callsign](https://en.wikipedia.org/wiki/Aviation_call_signs).",
)
async def v2_callsign_filter(
    callsign: str = Path(default=..., example="JBU1942"),
    x_original_forwarded_for: str
    | None = Header(default=None, include_in_schema=False),
) -> V2Response_Model:
    client_ip = x_original_forwarded_for
    params = [f"find_callsign={callsign}"]

    res = await provider.ReAPI.request(params=params, client_ip=client_ip)
    return res


@router.get(
    "/point/{lat}/{lon}/{radius}",
    response_class=PrettyJSONResponse,
    summary="Aircrafts surrounding a point (lat, lon) up to 250nm",
    description="Returns aircraft located in a circle described by the latitude and longtidude of its center and its radius.",
)
async def v2_point(
    lat: float = Path(..., example=40.78),
    lon: float = Path(..., example=73.97),
    radius: int = Path(..., example=250),
    x_original_forwarded_for: str
    | None = Header(default=None, include_in_schema=False),
) -> V2Response_Model:
    radius = min(radius, 250)
    client_ip = x_original_forwarded_for

    res = await provider.ReAPI.request(
        params=[f"circle={lat},{lon},{radius}"], client_ip=client_ip
    )
    return res

@router.get(
    "/all",
    response_class=PrettyJSONResponse,
    summary="All aircrafts",
    description="Returns all [aircraft](https://en.wikipedia.org/wiki/Aircraft).",
)
async def v2_all(
    x_original_forwarded_for: str
    | None = Header(default=None, include_in_schema=False),
) -> V2Response_Model:

    client_ip = x_original_forwarded_for
    params = ["all"]

    res = await provider.ReAPI.request(params=params, client_ip=client_ip)
    return res
