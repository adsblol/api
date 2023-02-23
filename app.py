import json
import typing
import uuid
from datetime import datetime

from aiohttp import web
from fastapi import FastAPI, Header, Query, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from utils.models import ApiUuidRequest, PrettyJSONResponse
from utils.provider import Provider
from utils.api_v2 import router as v2_router

app = FastAPI()
app.include_router(v2_router)

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="/app/templates")


provider = Provider()

@app.on_event("startup")
async def startup_event():
    await provider.startup()


@app.on_event("shutdown")
async def shutdown_event():
    await provider.shutdown()


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def index(
    request: Request, x_original_forwarded_for: str | None = Header(default=None)
):
    """
    Return the index.html page with the client numbers.
    """
    client_ip = x_original_forwarded_for
    clients_beast = provider.get_clients_per_client_ip(
        provider.beast_clients, client_ip
    )
    clients_mlat = provider.mlat_clients_to_list(provider.mlat_clients, client_ip)
    context = {
        "clients_beast": clients_beast,
        "clients_mlat": clients_mlat,
        "own_mlat_clients": len(clients_mlat),
        "ip": client_ip,
        "len_beast": len(provider.beast_clients),
        "len_mlat": len(provider.mlat_clients),
        "request": request,
    }
    response = templates.TemplateResponse("index.html", context)
    return response


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
    json_log = json.dumps({"uuid": generated_uuid, "data": data.dict()})
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
    ]
    return Response(content="\n".join(metrics), media_type="text/plain")


@app.get("/api/0/me", response_class=PrettyJSONResponse)
async def api_me(
    x_original_forwarded_for: str | None = Header(default=None, include_in_schema=False)
):
    client_ip = x_original_forwarded_for
    beast_clients_set = provider.get_clients_per_client_ip(
        provider.beast_clients, client_ip
    )
    beast_clients_list = []
    for client in beast_clients_set:
        beast_clients_list.append(
            {
                "type": "beast",
                "hex": client[0],
                "kbps": client[2],
                "connected_seconds": client[3],
                "positions": client[7],
                "messages_per_second": client[4],
                "positions_per_second": client[5],
            }
        )
    mlat_clients = provider.mlat_clients_to_list(provider.mlat_clients, client_ip)
    response = {
        "feeding": {
            "beast": len(beast_clients_list) > 0,
            "mlat": len(mlat_clients) > 0,
        },
        "clients": {
            "beast": beast_clients_list,
            "mlat": mlat_clients,
        },
        "client_ip": client_ip,
    }

    return response



if __name__ == "__main__":
    print("Run with:")
    print("uvicorn app:app --host 0.0.0.0 --port 80")
