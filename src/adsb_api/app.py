import ipaddress
import pathlib
import secrets
import time
import traceback
import uuid
import random
import asyncio
from collections import defaultdict
import h3

import aiohttp
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
from adsb_api.utils.api_tar import router as tar_router
from adsb_api.utils.api_v2 import router as v2_router
from adsb_api.utils.dependencies import browser, feederData, provider, redisVRS
from adsb_api.utils.models import ApiUuidRequest, PrettyJSONResponse
from adsb_api.utils.settings import INSECURE, REDIS_HOST, SALT_BEAST, SALT_MLAT, SALT_MY

PROJECT_PATH = pathlib.Path(__file__).parent.parent.parent

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

If you want to use the API for production purposes,
please contact me so I do not break your application by accident.

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
    await redisVRS.dispatch_background_task()
    await feederData.connect()
    await feederData.dispatch_background_task()
    try:
        await browser.start()
    except:
        traceback.print_exc()

    ensure_uuid_security()


@app.on_event("shutdown")
async def shutdown_event():
    await provider.shutdown()
    await redisVRS.shutdown()
    await browser.shutdown()


@app.get(
    "/api/0/mlat-server/{server}/sync.json",
    response_class=PrettyJSONResponse,
    include_in_schema=False,
)
async def mlat_receivers(
    server: str,
    host: str | None = Header(default=None, include_in_schema=False),
):
    # if the host is not mlat.adsb.lol,
    # return a 404
    if host != "mlat.adsb.lol":
        return {"error": "not found"}

    if server not in provider.mlat_sync_json.keys():
        return {"error": "not found"}

    return provider.mlat_sync_json[server]


@app.get(
    "/api/0/mlat-server/totalcount.json",
    response_class=PrettyJSONResponse,
    include_in_schema=False,
)
async def mlat_totalcount_json():
    return provider.mlat_totalcount_json


@app.get("/metrics", include_in_schema=False)
async def metrics():
    """
    Return metrics for Prometheus
    """
    metrics = [
        "adsb_api_beast_total_receivers {}".format(len(provider.beast_receivers)),
        "adsb_api_beast_total_clients {}".format(len(provider.beast_clients)),
        # "adsb_api_mlat_total {}".format(len(provider.mlat_sync_json)),
        # new format is {'0a': {clients}, '0b': {clients}}
        # so let's make tag for each server
        *[
            'adsb_api_mlat_total{{server="{0}"}} {1}'.format(server, len(clients))
            for server, clients in provider.mlat_clients.items()
        ],
        "adsb_api_aircraft_total {}".format(provider.aircraft_totalcount),
    ]
    return Response(content="\n".join(metrics), media_type="text/plain")


@app.get(
    "/api/0/me",
    response_class=PrettyJSONResponse,
    tags=["v0"],
    summary="Information about your receiver and global stats",
    include_in_schema=False,
)
@app.get(
    "/0/me",
    response_class=PrettyJSONResponse,
    tags=["v0"],
    summary="Information about your receiver and global stats",
)
async def api_me(request: Request):
    client_ip = request.client.host
    my_beast_clients = provider.get_clients_per_client_ip(client_ip)
    mlat_clients = provider.mlat_clients_to_list(client_ip)

    # /api/0/me is deprecated,
    # add a warning in the response,
    # also, planes is also for /api/0/me,
    # in /0/me they are called aircraft

    # count all items as mlat_clients format is {'0a': {clients}, '0b': {clients}}
    all_mlat_clients = sum([len(i) for i in provider.mlat_clients.values()])
    response = {
        "_motd": [],
        "clients": {
            "beast": my_beast_clients,
            "mlat": mlat_clients,
        },
        "global": {
            "beast": len(provider.beast_clients),
            "mlat": all_mlat_clients,
            "aircraft": provider.aircraft_totalcount,
        },
    }
    # if we are on /api/0/me, add a warning
    if request.url.path == "/api/0/me":
        response["_motd"].append([
            "WARNING: /api/0/me is deprecated, use /0/me instead",
            "WARNING: /api/0/me is to be removed 1 Nov, 2023.",
            "WARNING: /api/0/me is being slowed down 1-3 seconds to make users notice the deprecation.",
            "DIFF: /0/me: .global.planes is renamed to .global.aircraft",
            "DIFF: /0/me: .feeding.beast and .feeding.mlat have been removed. Count the .clients instead.",
            "DIFF: /0/me: .client_ip is removed. Use icanhazip.com instead.",
        ])
        response["global"]["planes"] = provider.aircraft_totalcount
        response["feeding"] = {
            "beast": len(my_beast_clients) > 0,
            "mlat": len(mlat_clients) > 0,
        }
        response["client_ip"] = client_ip

        await asyncio.sleep(random.randint(1, 3))

    # If any of the clients.beast.ms = -1, they PROBABLY do not use beast_reduce_plus_out
    # so add a WARNING
    if any([i["ms"] == -1 for i in my_beast_clients]):
        response["_motd"].append(
            "WARNING: You are probably not using beast_reduce_plus_out. Please use it instead of beast_reduce_out."
        )
    return response

@app.get("/0/my", tags=["v0"], summary="My Map redirect based on IP")
@app.get("/api/0/my", tags=["v0"], summary="My Map redirect based on IP", include_in_schema=False)
async def api_my(request: Request):
    client_ip = request.client.host
    my_beast_clients = provider.get_clients_per_client_ip(client_ip)
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


@app.get(
    "/0/h3_latency",
    include_in_schema=False,
    tags=["v0"],
)
async def h3_latency():
    _h3 = defaultdict(list)
    for receiverId, lat, lon in provider.beast_receivers:
        for client in provider.beast_clients:
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
