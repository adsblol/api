import pathlib
import secrets
import time
import traceback
import uuid
import ipaddress
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
from adsb_api.utils.settings import (INSECURE, REDIS_HOST, SALT_BEAST,
                                     SALT_MLAT, SALT_MY)

PROJECT_PATH = pathlib.Path(__file__).parent.parent.parent

description = """
The adsb.lol API is a free and open source
API for the [adsb.lol](https://adsb.lol) project.

## Usage
You can use the API by sending a GET request
to the endpoint you want to use.
The API will return a JSON response.

## Terms of Service
You can use the API for free.

In the future, I might add a rate limit to the API.

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
    version="0.0.1",
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

@app.get("/api/0/receivers", response_class=PrettyJSONResponse, include_in_schema=False)
async def receivers():
    return provider.beast_receivers


@app.get(
    "/api/0/mlat-server/0A/sync.json",
    response_class=PrettyJSONResponse,
    include_in_schema=False,
)
async def mlat_receivers():
    return provider.mlat_sync_json


@app.get(
    "/api/0/mlat-server/totalcount.json",
    response_class=PrettyJSONResponse,
    include_in_schema=False,
)
async def mlat_totalcount_json():
    return provider.mlat_totalcount_json


@app.post("/api/0/uuid", response_class=PrettyJSONResponse, include_in_schema=False)
async def post_uuid(data: ApiUuidRequest):
    generated_uuid = str(uuid.uuid4())
    json_log = orjson.dumps({"uuid": generated_uuid, "data": data.dict()})
    print(json_log)
    return {"uuid": generated_uuid}


@app.get("/metrics", include_in_schema=False)
async def metrics():
    """
    Return metrics for Prometheus
    """
    metrics = [
        "adsb_api_beast_total_receivers {}".format(len(provider.beast_receivers)),
        "adsb_api_beast_total_clients {}".format(len(provider.beast_clients)),
        "adsb_api_mlat_total {}".format(len(provider.mlat_sync_json)),
        "adsb_api_aircraft_total {}".format(provider.aircraft_totalcount),
    ]
    return Response(content="\n".join(metrics), media_type="text/plain")


@app.get("/api/0/me", response_class=PrettyJSONResponse, tags=["v0"])
async def api_me(
    x_original_forwarded_for: str | None = Header(default=None, include_in_schema=False)
):
    client_ip = x_original_forwarded_for
    my_beast_clients = provider.get_clients_per_client_ip(client_ip)
    mlat_clients = provider.mlat_clients_to_list(client_ip)
    response = {
        "feeding": {
            "beast": len(my_beast_clients) > 0,
            "mlat": len(mlat_clients) > 0,
        },
        "clients": {
            "beast": my_beast_clients,
            "mlat": mlat_clients,
        },
        "client_ip": client_ip,
        "global": {
            "beast": len(provider.beast_clients),
            "mlat": len(provider.mlat_clients),
            "planes": provider.aircraft_totalcount,
        },
    }

    return response


@app.get("/0/mylocalip/{ips}", response_class=PrettyJSONResponse, tags=["v0"])
async def mylocalip_put(
    ips = str,
    x_original_forwarded_for: str | None = Header(default=None, include_in_schema=False)
):
    client_ip = x_original_forwarded_for
    # ips can be separated by ,
    # ensure each IP is also somewhat valid.
    ips = [ip for ip in ips.split(",") if ipaddress.ip_address(ip)]
    if not ips:
        return {"error": "no valid IPs found"}
    await redisVRS.redis.setex("mylocalip:" + client_ip, 60, ",".join(ips))
    return {"success": True, "ips": ips}

@app.get("/0/mylocalip", tags=["v0"])
async def mylocalip_get(
    request: Request,
    x_original_forwarded_for: str | None = Header(default=None, include_in_schema=False)
):
    client_ip = x_original_forwarded_for
    # this is the page the user loads if they want to see their local IPs
    # if there is only one ip, redirect them to it
    # if there are multiple, show them some clickable links for each
    # if there are none, show them a message saying no IPs found
    my_ips = await redisVRS.redis.get("mylocalip:" + client_ip)
    if my_ips:
        my_ips = my_ips.decode().split(",")
        if len(my_ips) == 1:
            return RedirectResponse(url="http://" + my_ips[0] + ":5000/")
        else:
            return templates.TemplateResponse(
                "mylocalip.html", {"ips": my_ips, "request": request}
            )
    else:
        return templates.TemplateResponse(
            "mylocalip.html", {"ips": [], "request": request}
        )

@app.get("/api/0/my", tags=["v0"])
async def api_my(
    x_original_forwarded_for: str | None = Header(default=None, include_in_schema=False)
):
    client_ip = x_original_forwarded_for
    my_beast_clients = provider.get_clients_per_client_ip(client_ip)
    uids = []
    if len(my_beast_clients) == 0:
        return RedirectResponse(
            url="https://adsb.lol#sorry-but-i-could-not-find-your-receiver?"
        )
    for client in my_beast_clients:
        uids.append(client["adsblol_my_hash"])
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


if __name__ == "__main__":
    print("Run with:")
    print("uvicorn app:app --host 0.0.0.0 --port 80")
    print("or for development:")
    print("uvicorn app:app --host 0.0.0.0 --port 80 --reload")
