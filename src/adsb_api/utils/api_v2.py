from typing import Callable

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


def _reapi_route(
    paths: str | list[str],
    params: list[str] | Callable[[Request], list[str]],
    summary: str,
    description: str,
    path_params: dict | None = None,
    **kwargs,
):
    """Factory function to create ReAPI-based route handlers.

    Args:
        paths: Single path or list of paths for the route
        params: Static params list or callable that receives Request and returns params
        summary: OpenAPI summary
        description: OpenAPI description
        path_params: Dict of path param names to Path(...) definitions
        **kwargs: Additional arguments passed to @router.get()
    """
    if isinstance(paths, str):
        paths = [paths]

    def decorator(func):
        async def handler(request: Request, **path_kwargs) -> Response:
            actual_params = params(request) if callable(params) else params
            res = await provider.ReAPI.request(params=actual_params, client_ip=request.client.host)
            return Response(res, media_type="application/json")

        # Apply path param annotations if provided
        if path_params:
            for name, param in path_params.items():
                handler.__annotations__[name] = param

        # Register the route(s)
        for path in paths:
            router.get(path, summary=summary, description=description, **kwargs)(handler)

        return handler
    return decorator


# Static param routes
_reapi_route(
    "/pia",
    ["all", "filter_pia"],
    "Aircrafts with PIA addresses (Privacy ICAO Address)",
    "Returns all aircraft with [PIA](https://nbaa.org/aircraft-operations/security/privacy/privacy-icao-address-pia/) addresses.",
)

_reapi_route(
    "/mil",
    ["all", "filter_mil"],
    "Military registered aircrafts",
    "Returns all military registered aircraft.",
)

_reapi_route(
    "/ladd",
    ["all", "filter_ladd"],
    "Aircrafts on LADD (Limiting Aircraft Data Displayed)",
    "Returns all aircrafts on [LADD](https://www.faa.gov/pilots/ladd) filter.",
)


# Dynamic param routes (single path param)
_reapi_route(
    ["/squawk/{squawk}", "/sqk/{squawk}"],
    lambda req: ["all", f"filter_squawk={req.path_params['squawk']}"],
    "Aircrafts with specific squawk (1200, 7700, etc.)",
    'Returns aircraft filtered by "squawk" [transponder code](https://en.wikipedia.org/wiki/List_of_transponder_codes).',
    path_params={"squawk": Path(default=..., examples="1200")},
)

_reapi_route(
    "/type/{aircraft_type}",
    lambda req: [f"find_type={req.path_params['aircraft_type']}"],
    "Aircrafts of specific type (A320, B738)",
    "Returns aircraft filtered by [aircraft type designator code](https://en.wikipedia.org/wiki/List_of_aircraft_type_designators).",
    path_params={"aircraft_type": Path(default=..., examples="A320")},
)

_reapi_route(
    ["/registration/{registration}", "/reg/{registration}"],
    lambda req: [f"find_reg={req.path_params['registration']}"],
    "Aircrafts with specific registration (G-KELS)",
    "Returns aircraft filtered by [aircarft registration code](https://en.wikipedia.org/wiki/Aircraft_registration).",
    path_params={"registration": Path(default=..., examples="G-KELS")},
)

_reapi_route(
    ["/hex/{icao_hex}", "/icao/{icao_hex}"],
    lambda req: [f"find_hex={req.path_params['icao_hex']}"],
    "Aircrafts with specific transponder hex code (4CA87C)",
    "Returns aircraft filtered by [transponder hex code](https://en.wikipedia.org/wiki/Aviation_transponder_interrogation_modes#ICAO_24-bit_address).",
    path_params={"icao_hex": Path(default=..., examples="4CA87C")},
)

_reapi_route(
    "/callsign/{callsign}",
    lambda req: [f"find_callsign={req.path_params['callsign']}"],
    "Aircrafts with specific callsign (JBU1942)",
    "Returns aircraft filtered by [callsign](https://en.wikipedia.org/wiki/Aviation_call_signs).",
    path_params={"callsign": Path(default=..., examples="JBU1942")},
)


# Dynamic param routes (multiple path params)
_reapi_route(
    ["/point/{lat}/{lon}/{radius}", "/lat/{lat}/lon/{lon}/dist/{radius}"],
    lambda req: [f"circle={req.path_params['lat']},{req.path_params['lon']},{min(int(req.path_params['radius']), 250)}"],
    "Aircrafts surrounding a point (lat, lon) up to 250nm",
    "Returns aircraft located in a circle described by the latitude and longtidude of its center and its radius.",
    path_params={
        "lat": Path(..., examples=51.89508, ge=-90, le=90),
        "lon": Path(..., examples=2.79437, ge=-180, le=180),
        "radius": Path(..., examples=250, ge=0, le=250),
    },
)

_reapi_route(
    "/closest/{lat}/{lon}/{radius}",
    lambda req: [f"closest={req.path_params['lat']},{req.path_params['lon']},{int(req.path_params['radius'])}"],
    "Single aircraft closest to a point (lat, lon)",
    "Returns the closest aircraft to a point described by the latitude and longtidude within a radius up to 250nm.",
    path_params={
        "lat": Path(..., examples=51.89508, ge=-90, le=90),
        "lon": Path(..., examples=2.79437, ge=-180, le=180),
        "radius": Path(..., examples=250, ge=0, le=250),
    },
)
