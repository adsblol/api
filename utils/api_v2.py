from fastapi import APIRouter, Header, Query

from . import provider
from .models import PrettyJSONResponse, V2Response_Model

router = APIRouter(
    prefix="/v2",
    tags=["v2"],
)

@router.get("/pia", response_class=PrettyJSONResponse, response_model=V2Response_Model)
async def v2_pia(
    x_original_forwarded_for: str
    | None = Header(default=None, include_in_schema=False),
) -> V2Response_Model:
    """
    Returns all aircraft with [PIA](https://nbaa.org/aircraft-operations/security/privacy/privacy-icao-address-pia/) addresses.
    """
    client_ip = x_original_forwarded_for
    params = ["all", "filter_pia"]

    res = await provider.ReAPI.request(params=params, client_ip=client_ip)
    return res


@router.get("/mil", response_class=PrettyJSONResponse, response_model=V2Response_Model)
async def v2_mil(
    x_original_forwarded_for: str
    | None = Header(default=None, include_in_schema=False),
) -> V2Response_Model:
    """
    Returns all military registered aircraft.
    """
    client_ip = x_original_forwarded_for
    params = ["all", "filter_mil"]

    res = await provider.ReAPI.request(params=params, client_ip=client_ip)
    return res


@router.get("/ladd", response_class=PrettyJSONResponse, response_model=V2Response_Model)
async def v2_ladd(
    x_original_forwarded_for: str
    | None = Header(default=None, include_in_schema=False),
) -> V2Response_Model:
    """
    Returns all aircrafto on [LADD](https://www.faa.gov/pilots/ladd) filter.
    """
    client_ip = x_original_forwarded_for
    params = ["all", "filter_ladd"]

    res = await provider.ReAPI.request(params=params, client_ip=client_ip)
    return res


@router.get("/all", response_class=PrettyJSONResponse, response_model=V2Response_Model)
async def v2_all(
    x_original_forwarded_for: str
    | None = Header(default=None, include_in_schema=False),
) -> V2Response_Model:
    """
    Returns all [aircraft](https://en.wikipedia.org/wiki/Aircraft).
    """
    client_ip = x_original_forwarded_for
    params = ["all"]

    res = await provider.ReAPI.request(params=params, client_ip=client_ip)
    return res


@router.get("/squawk/{squawk}", response_class=PrettyJSONResponse, response_model=V2Response_Model)
async def v2_squawk_filter(
    squawk: str = Query(default=..., example="1200"),
    x_original_forwarded_for: str
    | None = Header(default=None, include_in_schema=False),
) -> V2Response_Model:
    """
    Returns aircraft filtered by "squawk" [transponder code](https://en.wikipedia.org/wiki/List_of_transponder_codes).
    """
    client_ip = x_original_forwarded_for
    params = ["all", f"filter_squawk={squawk}"]

    res = await provider.ReAPI.request(params=params, client_ip=client_ip)
    return res


@router.get("/type/{aircraft_type}", response_class=PrettyJSONResponse, response_model=V2Response_Model)
async def v2_type_filter(
    aircraft_type: str = Query(default=..., example="A332"),
    x_original_forwarded_for: str
    | None = Header(default=None, include_in_schema=False),
) -> V2Response_Model:
    """
    Returns aircraft filtered by [aircraft type designator code](https://en.wikipedia.org/wiki/List_of_aircraft_type_designators).
    """
    client_ip = x_original_forwarded_for
    params = [f"find_type={aircraft_type}"]

    res = await provider.ReAPI.request(params=params, client_ip=client_ip)
    return res


@router.get("/reg/{registration}", response_class=PrettyJSONResponse, response_model=V2Response_Model)
async def v2_reg_filter(
    registration: str = Query(default=..., example="G-KELS"),
    x_original_forwarded_for: str
    | None = Header(default=None, include_in_schema=False),
) -> V2Response_Model:
    """
    Returns aircraft filtered by [aircarft registration code](https://en.wikipedia.org/wiki/Aircraft_registration).
    """
    client_ip = x_original_forwarded_for
    params = [f"find_reg={registration}"]

    res = await provider.ReAPI.request(params=params, client_ip=client_ip)
    return res


@router.get("/hex/{icao_hex}", response_class=PrettyJSONResponse, response_model=V2Response_Model)
async def v2_hex_filter(
    icao_hex: str = Query(default=..., example="4CA87C"),
    x_original_forwarded_for: str
    | None = Header(default=None, include_in_schema=False),
) -> V2Response_Model:
    """
    Returns aircraft filtered by [transponder hex code](https://en.wikipedia.org/wiki/Aviation_transponder_interrogation_modes#ICAO_24-bit_address).
    """
    client_ip = x_original_forwarded_for
    params = [f"find_hex={icao_hex}"]

    res = await provider.ReAPI.request(params=params, client_ip=client_ip)
    return res


@router.get("/callsign/{callsign}", response_class=PrettyJSONResponse, response_model=V2Response_Model)
async def v2_callsign_filter(
    callsign: str = Query(default=..., example="JBU1942"),
    x_original_forwarded_for: str
    | None = Header(default=None, include_in_schema=False),
) -> V2Response_Model:
    """
    Returns aircraft filtered by [callsign](https://en.wikipedia.org/wiki/Aviation_call_signs).
    """
    client_ip = x_original_forwarded_for
    params = [f"find_callsign={callsign}"]

    res = await provider.ReAPI.request(params=params, client_ip=client_ip)
    return res


@router.get("/point/{lat}/{lon}/{radius}", response_class=PrettyJSONResponse, response_model=V2Response_Model)
async def v2_point(
    lat: float,
    lon: float,
    radius: int,
    x_original_forwarded_for: str
    | None = Header(default=None, include_in_schema=False),
) -> V2Response_Model:
    """
    Return aircraft located in a circle described by the latitude and longtidude of it's center and it's radius.
    """
    radius = min(radius, 250)
    client_ip = x_original_forwarded_for

    res = await provider.ReAPI.request(
        params=[f"circle={lat},{lon},{radius}"], client_ip=client_ip
    )
    return res
