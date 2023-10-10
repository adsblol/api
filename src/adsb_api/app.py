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
from adsb_api.utils.dependencies import browser, redisVRS
from adsb_api.utils.models import ApiUuidRequest, PrettyJSONResponse
from adsb_api.utils.settings import INSECURE, REDIS_HOST, SALT_BEAST, SALT_MLAT, SALT_MY

PROJECT_PATH = pathlib.Path(__file__).parent.parent.parent

description = """
The OARC ADS-B API is a free and open source route
API for the [OARC ADS-B](https://adsb.oarc.uk) project.

## Usage of
You can use the API by sending a GET request
to the endpoint you want to use.
The API will return a JSON response.

## Terms of Service
You can use the API for free.

If you want to use the API for production purposes,
please contact me so I do not break your application by accident.

## License

The license for the API as well as all data OARC ADS-B
makes public is [ODbL](https://opendatacommons.org/licenses/odbl/summary/).

This is the same license
[OpenStreetMap](https://www.openstreetmap.org/copyright) uses.
"""

app = FastAPI(
    title="OARC ADS-B Route API",
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

app.include_router(routes_router)

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory=PROJECT_PATH / "templates")


@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return FileResponse("static/favicon.ico")


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
    redisVRS.redis_connection_string = REDIS_HOST
    await provider.startup()
    await redisVRS.connect()
    await redisVRS.dispatch_background_task()
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


if __name__ == "__main__":
    print("Run with:")
    print("uvicorn app:app --host 0.0.0.0 --port 80")
    print("or for development:")
    print("uvicorn app:app --host 0.0.0.0 --port 80 --reload")
