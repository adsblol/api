import asyncio
import ipaddress
import pathlib
import random
import secrets
import time
import traceback
import uuid
from collections import defaultdict

import aiohttp
import h3
import orjson
from fastapi import FastAPI, Header, Request
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import FileResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi_cache import FastAPICache
from fastapi_cache.backends.redis import RedisBackend
from redis import asyncio as aioredis

from adsb_api.utils.api_routes import router as routes_router
from adsb_api.utils.api_tar import close_http_session as close_tar_http_session
from adsb_api.utils.api_tar import router as tar_router
from adsb_api.utils.api_v2 import router as v2_router
from adsb_api.utils.dependencies import browser, feederData, provider, redisVRS
from adsb_api.utils.models import ApiUuidRequest, PrettyJSONResponse
from adsb_api.utils.settings import (INSECURE, REDIS_KEY_BEAST_CLIENTS, REDIS_KEY_BEAST_RECEIVERS, REDIS_KEY_HUB_AIRCRAFT, REDIS_KEY_MLAT_CLIENTS, REDIS_KEY_MLAT_SYNC, REDIS_KEY_MLAT_TOTALCOUNT, REDIS_HOST, SALT_BEAST,
                                     SALT_MLAT, SALT_MY)

PROJECT_PATH = pathlib.Path(__file__).parent.parent.parent

# Shared aiohttp session for external HTTP requests
_http_session: aiohttp.ClientSession | None = None

async def get_http_session() -> aiohttp.ClientSession:
    global _http_session
    if _http_session is None:
        _http_session = aiohttp.ClientSession()
    return _http_session

description = """
The adsb.lol API is a free and open source
API for the [adsb.lol](https://adsb.lol) project.

## Usage
You can use the API by sending a GET request
to the endpoint you want to use.
The API will return a JSON response.

## Feeders

By sending data to adsb.lol, you get access to the
[direct readsb re-api](https://www.adsb.lol/docs/feeders-only/re-api/)
and
[our raw aggregated data](https://www.adsb.lol/docs/feeders-only/beast-mlat-out/). :)

## Terms of Service
You can use the API for free.

In the future, you will require an API key
which you can get by feeding to adsb.lol.

Rate limits are dynamic based on the environment load. 

If you get 4xx errors, you are doing something wrong. 

## License

The license for the API as well as all data ADSB.lol
makes public is [ODbL](https://opendatacommons.org/licenses/odbl/summary/).

This is the same license
[OpenStreetMap](https://www.openstreetmap.org/copyright) uses.
"""

app = FastAPI(
    title="adsb.lol API",
    description=description,
    version="0.0.2",
    docs_url=None,
    redoc_url=None,
    openapi_url="/api/openapi.json",
    license_info={
        "name": "Open Data Commons Open Database License (ODbL) v1.0",
        "url": "https://opendatacommons.org/licenses/odbl/1-0/",
    },
)

app.include_router(v2_router)
app.include_router(routes_router)
app.include_router(tar_router)

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory=PROJECT_PATH / "templates")


@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return FileResponse("static/favicon.ico")


@app.get("/docs", include_in_schema=False)
def docs_override():
    return get_swagger_ui_html(
        openapi_url="/api/openapi.json",
        title="adsb.lol API",
        swagger_favicon_url="/favicon.ico",
    )


def ensure_uuid_security():
    # Each UUID should be at least 128 characters long
    # and should be unique.
    # If no UUIDs are set, generate some.
    if INSECURE:
        time.sleep(0.5)
        print("WARNING: INSECURE MODE IS ENABLED")
        print("WARNING: UUIDS WILL BE GENERATED ON EACH STARTUP!")
        time.sleep(0.5)
    salts = {"my": SALT_MY, "mlat": SALT_MLAT, "beast": SALT_BEAST}
    for name, salt in salts.items():
        if salt is None or len(salt) < 128:
            print(f"WARNING: {name} salt is not secure")
            print("WARNING: Overriding with random salt")
            salts[name] = secrets.token_hex(128)
            # print first chars of salt
            print("WARNING: First 10 chars of salt: " + salts[name][:10])


@app.on_event("startup")
async def startup_event():
    redis = aioredis.from_url(REDIS_HOST, encoding="utf8", decode_responses=True)
    FastAPICache.init(RedisBackend(redis), prefix="api")
    for i in (redisVRS, provider, feederData):
        i.redis_connection_string = REDIS_HOST
    await provider.startup()
    await redisVRS.connect()
    await feederData.connect()
    await asyncio.sleep(1)
    await redisVRS.dispatch_background_task()
    await feederData.dispatch_background_task()
    try:
        # Add timeout to prevent hanging if CDP browser is unavailable
        await asyncio.wait_for(browser.start(), timeout=5.0)
    except asyncio.TimeoutError:
        print("browser.start() timed out after 5s - CDP browser may be unavailable")
    except Exception:
        traceback.print_exc()

    ensure_uuid_security()


@app.on_event("shutdown")
async def shutdown_event():
    global _http_session
    await provider.shutdown()
    await redisVRS.shutdown()
    await browser.shutdown()
    await close_tar_http_session()
    if _http_session:
        await _http_session.close()
        _http_session = None


@app.get(
    "/api/0/mlat-server/{server}/sync.json",
    response_class=PrettyJSONResponse,
    include_in_schema=False,
)
async def mlat_receivers(
    server: str,
    host: str | None = Header(default=None, include_in_schema=False),
):
    if host != "mlat.adsb.lol":
        print(f"failed mlat_sync host={host}, server={server} (not mlat.adsb.lol)")
        return {"error": "not found"}

    mlat_sync = await provider._json_get(REDIS_KEY_MLAT_SYNC)
    if not mlat_sync:
        return {"error": "not found"}
    if server not in mlat_sync:
        print(f"failed mlat_sync host={host}, server={server} (not in {mlat_sync.keys()})")
        return {"error": "not found"}

    return mlat_sync[server]


@app.get(
    "/api/0/mlat-server/totalcount.json",
    response_class=PrettyJSONResponse,
    include_in_schema=False,
)
async def mlat_totalcount_json():
    return await provider._json_get(REDIS_KEY_MLAT_TOTALCOUNT) or {}


@app.get("/metrics", include_in_schema=False)
async def metrics():
    # Parallel JSON gets with parsing
    data = await provider._json_gets([REDIS_KEY_BEAST_CLIENTS, REDIS_KEY_BEAST_RECEIVERS, REDIS_KEY_MLAT_CLIENTS, REDIS_KEY_HUB_AIRCRAFT])
    aircraft_count = data.get(REDIS_KEY_HUB_AIRCRAFT)

    metrics = [
        "adsb_api_beast_total_receivers {}".format(len(data.get(REDIS_KEY_BEAST_RECEIVERS) or [])),
        "adsb_api_beast_total_clients {}".format(len(data.get(REDIS_KEY_BEAST_CLIENTS) or [])),
        *[
            'adsb_api_mlat_total{{server="{0}"}} {1}'.format(server, len(clients))
            for server, clients in (data.get(REDIS_KEY_MLAT_CLIENTS) or {}).items()
        ],
        f"adsb_api_aircraft_total {int(aircraft_count) if aircraft_count else 0}",
    ]
    return Response(content="\n".join(metrics), media_type="text/plain")


@app.get(
    "/0/me",
    response_class=PrettyJSONResponse,
    tags=["v0"],
    summary="Information about your receiver and global stats",
)
async def api_me(request: Request):
    client_ip = request.client.host
    my_beast_clients, mlat_clients = await asyncio.gather(
        provider.get_clients_per_client_ip(client_ip),
        provider.mlat_clients_to_list(client_ip),
    )

    data = await provider._json_gets([REDIS_KEY_MLAT_CLIENTS, REDIS_KEY_BEAST_CLIENTS, REDIS_KEY_HUB_AIRCRAFT])
    mlat_data, beast_data, aircraft_count = data.get(REDIS_KEY_MLAT_CLIENTS) or {}, data.get(REDIS_KEY_BEAST_CLIENTS) or {}, data.get(REDIS_KEY_HUB_AIRCRAFT)

    response = {
        "_motd": [],
        "clients": {
            "beast": my_beast_clients,
            "mlat": mlat_clients,
        },
        "global": {
            "beast": len(beast_data),
            "mlat": sum([len(i) for i in mlat_data.values()]),
            "aircraft": int(aircraft_count) if aircraft_count else 0,
        },
    }

    # If any of the clients.beast.ms = -1, they PROBABLY do not use beast_reduce_plus_out
    # so add a WARNING
    if any([i["ms"] == -1 for i in my_beast_clients]):
        response["_motd"].append(
            "WARNING: You are probably not using beast_reduce_plus_out. Please use it instead of beast_reduce_out."
        )
    # If there's any mlat client, and bad sync timeout is >0 for any of them, add a WARNING
    if any([i["bad_sync_timeout"] > 0 for i in mlat_clients]):
        response["_motd"].append(
            "WARNING: Some of your mlat clients have bad sync timeout. Please check your mlat configuration."
        )
    # If any bad
    return response

@app.get("/0/my", tags=["v0"], summary="My Map redirect based on IP")
@app.get("/api/0/my", tags=["v0"], summary="My Map redirect based on IP", include_in_schema=False)
async def api_my(request: Request):
    client_ip = request.client.host
    my_beast_clients = await provider.get_clients_per_client_ip(client_ip)
    uids = []
    if len(my_beast_clients) == 0:
        return RedirectResponse(
            url="https://adsb.lol#sorry-but-i-could-not-find-your-receiver?"
        )
    for client in my_beast_clients:
        uids.append(client["adsblol_my_url"].split("https://")[1].split(".")[0])
    # redirect to
    # uid1_uid2.my.adsb.lol
    host = "https://" + "_".join(uids) + ".my.adsb.lol"
    return RedirectResponse(url=host)


@app.get(
    "/data/receiver.json", response_class=PrettyJSONResponse, include_in_schema=False
)
async def receiver_json(
    host: str | None = Header(default=None, include_in_schema=False)
):
    ret = {
        "readsb": True,
        "version": "adsb.lol",
        "refresh": 1000,
    }
    # add feederData.additional_receiver_params
    # ret.update(feederData.additional_receiver_params)

    uids = host.split(".")[0].split("_")

    for uid in uids:
        # try getting receiver for uid
        receiver = await feederData.redis.get(f"my:{uid}")
        if receiver:
            receiver = receiver.decode()[:18]
        else:
            continue

        rdata = await feederData.redis.get(f"receiver:{receiver}")
        if rdata:
            rdata = orjson.loads(rdata.decode())
            ret["lat"], ret["lon"] = round(rdata[8], 1), round(rdata[9], 1)
            break
    return ret


@app.get(
    "/data/aircraft.json",
    response_class=PrettyJSONResponse,
    include_in_schema=False,
)
async def aircraft_json(
    host: str | None = Header(default=None, include_in_schema=False)
):
    uids = host.split(".")[0].split("_")
    ac = []
    for uid in uids:
        # we need to find the name of a redis key by its value!
        receiver = await feederData.redis.get(f"my:{uid}")
        if receiver:
            receiver = receiver.decode()[:18]
        else:
            continue

        if receiver:
            data = await feederData.get_aircraft(receiver)
            if data is not None:
                # remove key recentReceiverIds if it exists
                for aircraft in data:
                    try:
                        del aircraft["recentReceiverIds"]
                    except KeyError:
                        pass
                ac.extend(data)
    return {
        "now": int(time.time()),
        "messages": 0,
        "aircraft": ac,
    }


# An API 1:1 caching https://api.planespotters.net/pub/photos/hex/<hex> for 1h
# Watch out! It passes also ?icaoType and ?reg to the API


@app.get(
    "/0/planespotters_net/hex/{hex}",
    response_class=PrettyJSONResponse,
    include_in_schema=False,
    tags=["v0"],
)
async def planespotters_net_hex(
    hex: str,
    reg: str = "",
    icaoType: str = "",
):
    # make a params out of the query params
    params = {"icaoType": icaoType, "reg": reg}
    redis_key = f"planespotters_net_hex:{hex}:{icaoType}:{reg}"
    # check if we have a cached response

    if cache := await redisVRS.redis.get(redis_key):
        return orjson.loads(cache)
    # if not, query the API (using shared session)
    session = await get_http_session()
    async with session.get(
        f"https://api.planespotters.net/pub/photos/hex/{hex}",
        params=params,
    ) as response:
        if response.status == 200:
            await redisVRS.redis.setex(redis_key, 3600, orjson.dumps(await response.json()))
            return await response.json()
        return {"error": "not found"}


@app.options("/0/planespotters_net/hex/{hex}", include_in_schema=False)
async def planespotters_net_hex_options():
    return Response(
        status_code=200,
        headers={
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type",
        },
    )

@app.get(
    "/0/h3_latency",
    include_in_schema=False,
    tags=["v0"],
)
async def h3_latency():
    data = await provider._json_gets([REDIS_KEY_BEAST_RECEIVERS, REDIS_KEY_BEAST_CLIENTS])
    beast_receivers = data.get(REDIS_KEY_BEAST_RECEIVERS) or []
    beast_clients = data.get(REDIS_KEY_BEAST_CLIENTS) or []

    _h3 = defaultdict(list)
    for receiverId, lat, lon in beast_receivers:
        for client in beast_clients:
            if not client["_uuid"].startswith(receiverId) or client.get("ms", -1) < 0:
                continue
            _h3[h3.latlng_to_cell(lat, lon, 1)].append(client["ms"])
    ret = defaultdict(dict)
    for key, value in _h3.items():
        # calculate median
        value.sort()
        ret[key]["median"] = value[len(value) // 2]
        # calculate average, limit to 2 decimals
        ret[key]["average"] = round(sum(value) / len(value), 2)
        # calculate min
        ret[key]["min"] = min(value)
        # calculate max
        ret[key]["max"] = max(value)
        # calculate count
        ret[key]["count"] = len(value)
    # if count < 2, remove the key
    ret = {key: value for key, value in ret.items() if value["count"] > 1}
    # sort by median
    ret = dict(sorted(ret.items(), key=lambda item: item[1]["median"]))
    return Response(orjson.dumps(ret), media_type="application/json")

if __name__ == "__main__":
    print("Run with:")
    print("uvicorn app:app --host 0.0.0.0 --port 80")
    print("or for development:")
    print("uvicorn app:app --host 0.0.0.0 --port 80 --reload")
