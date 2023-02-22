import asyncio
import aiohttp
from aiohttp import web
import bcrypt
from datetime import datetime
import uuid
import traceback
import json
import typing
from utils.reapi import ReAPI
from functools import lru_cache

from fastapi import FastAPI
from fastapi import Header, Query, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

app = FastAPI()

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="/app/templates")


class ApiUuidRequest(BaseModel):
    version: str


class PrettyJSONResponse(Response):
    media_type = "application/json"

    def render(self, content: typing.Any) -> bytes:
        return json.dumps(
            content,
            ensure_ascii=False,
            allow_nan=False,
            indent=2,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")


class Provider(object):
    def __init__(self):
        self.beast_clients = set()
        self.beast_receivers = []
        self.mlat_sync_json = {}
        self.mlat_totalcount_json = {}
        self.mlat_clients = {}
        self.ReAPI = ReAPI("http://reapi-readsb:30152/re-api/")

    async def startup(self):
        self.client_session = aiohttp.ClientSession(
            raise_for_status=True,
            timeout=aiohttp.ClientTimeout(total=5.0, connect=1.0, sock_connect=1.0),
        )
        self.bg_task = asyncio.create_task(self.fetch_remote_data())

    async def shutdown(self):
        self.bg_task.cancel()
        await self.client_session.close()

    async def fetch_remote_data(self):
        try:
            while True:
                try:
                    # clients update
                    ips = ["ingest-readsb:150"]
                    print("Fetching data from", ips)
                    clients = []
                    receivers = []
                    for ip in ips:
                        async with self.client_session.get(
                            f"http://{ip}/clients.json"
                        ) as resp:
                            data = await resp.json()
                            clients += data["clients"]
                            print(len(clients), "clients")

                        async with self.client_session.get(
                            f"http://{ip}/receivers.json"
                        ) as resp:
                            data = await resp.json()
                            for receiver in data["receivers"]:
                                lat, lon = round(receiver[8], 2), round(receiver[9], 2)
                                receivers.append([lat, lon])
                    print(len(receivers), "receivers")

                    self.beast_clients = self.beast_clients_to_set(clients)
                    self.beast_receivers = receivers

                    # mlat update
                    print("Fetching mlat data")
                    async with self.client_session.get(
                        "http://mlat-mlat-server:150/sync.json"
                    ) as resp:
                        data = await resp.json()
                    print("Fetched mlat sync.json")
                    self.mlat_sync_json = self.anonymize_mlat_data(data)
                    self.mlat_totalcount_json = {
                        "0A": len(self.mlat_sync_json),
                        "UPDATED": datetime.now().strftime("%a %b %d %H:%M:%S UTC %Y"),
                    }

                    # mlat clients.json
                    print("Fetching mlat clients.json")
                    async with self.client_session.get(
                        "http://mlat-mlat-server:150/clients.json"
                    ) as resp:
                        data = await resp.json()
                    self.mlat_clients = data

                    print("Looped..")
                    await asyncio.sleep(1)
                except Exception as e:
                    traceback.print_exc()
                    print("Error in background task, retry in 10s:", e)
                    await asyncio.sleep(10)
        except asyncio.CancelledError:
            print("Background task cancelled")

    @staticmethod
    def beast_clients_to_set(clients):
        clients_set = set()
        for client in clients:
            hex = client[0]
            ip = client[1].split()[1]
            kbps = client[2]
            conn_time = client[3]
            msg_s = client[4]
            position_s = client[5]
            reduce_signal = client[6]
            positions = client[8]

            clients_set.add(
                (hex, ip, kbps, conn_time, msg_s, position_s, reduce_signal, positions)
            )
        return clients_set

    @staticmethod
    def mlat_clients_to_list(clients, ip=None):
        clients_list = []
        keys_to_copy = "user privacy connection peer_count bad_sync_timeout outlier_percent".split()
        for name, client in clients.items():
            print(client)
            if ip is not None and client["source_ip"] != ip:
                continue
            clients_list.append(
                {key: client[key] for key in keys_to_copy if key in client}
            )
        return clients_list

    def anonymize_mlat_data(self, data):
        sanitized_data = {}
        for name, value in data.items():
            sanitised_peers = {}
            for peer, peer_value in value["peers"].items():
                sanitised_peers[self.cachehash(peer)] = peer_value

            sanitized_data[self.cachehash(name)] = {
                "lat": value["lat"],
                "lon": value["lon"],
                "peers": sanitised_peers,
            }

        return sanitized_data

    @staticmethod
    def get_clients_per_client_ip(clients, ip: str) -> list:
        return [client for client in clients if client[1] == ip]

    @lru_cache(maxsize=1024)
    def cachehash(self, name):
        # Only hash UUIDs
        try:
            uuid.UUID(name)
            salt = b"$2b$04$OGq0aceBoTGtzkUfT0FGme"
            _hash = bcrypt.hashpw(name.encode(), salt).decode()
            candidate = "".join([c for c in _hash if c.isalnum()])[-13:]
            name_id = name[0:3] + "_" + candidate[-13:]
            return name_id
        except ValueError:
            print(f"Unable to hash {name[:4]}...")
            return name


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


@app.get("/v2/pia", response_class=PrettyJSONResponse)
async def v2_pia(
    x_original_forwarded_for: str
    | None = Header(default=None, include_in_schema=False),
):
    """
    Returns all aircraft with [PIA](https://nbaa.org/aircraft-operations/security/privacy/privacy-icao-address-pia/) addresses.
    """
    client_ip = x_original_forwarded_for
    params = ["all", "filter_pia"]

    res = await provider.ReAPI.request(params=params, client_ip=client_ip)
    return res


@app.get("/v2/mil", response_class=PrettyJSONResponse)
async def v2_mil(
    x_original_forwarded_for: str
    | None = Header(default=None, include_in_schema=False),
):
    """
    Returns all military registered aircraft.
    """
    client_ip = x_original_forwarded_for
    params = ["all", "filter_mil"]

    res = await provider.ReAPI.request(params=params, client_ip=client_ip)
    return res


@app.get("/v2/ladd", response_class=PrettyJSONResponse)
async def v2_ladd(
    x_original_forwarded_for: str
    | None = Header(default=None, include_in_schema=False),
):
    """
    Returns all aircrafto on [LADD](https://www.faa.gov/pilots/ladd) filter.
    """
    client_ip = x_original_forwarded_for
    params = ["all", "filter_ladd"]

    res = await provider.ReAPI.request(params=params, client_ip=client_ip)
    return res


@app.get("/v2/all", response_class=PrettyJSONResponse)
async def v2_all(
    x_original_forwarded_for: str
    | None = Header(default=None, include_in_schema=False),
):
    """
    Returns all [aircraft](https://en.wikipedia.org/wiki/Aircraft).
    """
    client_ip = x_original_forwarded_for
    params = ["all"]

    res = await provider.ReAPI.request(params=params, client_ip=client_ip)
    return res


@app.get("/v2/squawk/{filter_string}", response_class=PrettyJSONResponse)
async def v2_squawk_filter(
    filter_string: str = Query(default=..., example="1200"),
    x_original_forwarded_for: str
    | None = Header(default=None, include_in_schema=False),
):
    """
    Returns aircraft filtered by "squawk" [transponder code](https://en.wikipedia.org/wiki/List_of_transponder_codes).
    """
    client_ip = x_original_forwarded_for
    params = ["all", f"filter_squawk={filter_string}"]

    res = await provider.ReAPI.request(params=params, client_ip=client_ip)
    return res


@app.get("/v2/type/{filter_string}", response_class=PrettyJSONResponse)
async def v2_type_filter(
    filter_string: str = Query(default=..., example="A332"),
    x_original_forwarded_for: str
    | None = Header(default=None, include_in_schema=False),
):
    """
    Returns aircraft filtered by [aircraft type designator code](https://en.wikipedia.org/wiki/List_of_aircraft_type_designators).
    """
    client_ip = x_original_forwarded_for
    params = [f"find_type={filter_string}"]

    res = await provider.ReAPI.request(params=params, client_ip=client_ip)
    return res


@app.get("/v2/reg/{filter_string}", response_class=PrettyJSONResponse)
async def v2_reg_filter(
    filter_string: str = Query(default=..., example="G-KELS"),
    x_original_forwarded_for: str
    | None = Header(default=None, include_in_schema=False),
):
    """
    Returns aircraft filtered by [aircarft registration code](https://en.wikipedia.org/wiki/Aircraft_registration).
    """
    client_ip = x_original_forwarded_for
    params = [f"find_reg={filter_string}"]

    res = await provider.ReAPI.request(params=params, client_ip=client_ip)
    return res


@app.get("/v2/hex/{filter_string}", response_class=PrettyJSONResponse)
async def v2_hex_filter(
    filter_string: str = Query(default=..., example="4CA87C"),
    x_original_forwarded_for: str
    | None = Header(default=None, include_in_schema=False),
):
    """
    Returns aircraft filtered by [transponder hex code](https://en.wikipedia.org/wiki/Aviation_transponder_interrogation_modes#ICAO_24-bit_address).
    """
    client_ip = x_original_forwarded_for
    params = [f"find_hex={filter_string}"]

    res = await provider.ReAPI.request(params=params, client_ip=client_ip)
    return res


@app.get("/v2/callsign/{filter_string}", response_class=PrettyJSONResponse)
async def v2_callsign_filter(
    filter_string: str = Query(default=..., example="JBU1942"),
    x_original_forwarded_for: str
    | None = Header(default=None, include_in_schema=False),
):
    """
    Returns aircraft filtered by [callsign](https://en.wikipedia.org/wiki/Aviation_call_signs).
    """
    client_ip = x_original_forwarded_for
    params = [f"find_callsign={filter_string}"]

    res = await provider.ReAPI.request(params=params, client_ip=client_ip)
    return res


@app.get("/v2/point/{lat}/{lon}/{radius}", response_class=PrettyJSONResponse)
async def v2_point(
    lat: float,
    lon: float,
    radius: int,
    x_original_forwarded_for: str
    | None = Header(default=None, include_in_schema=False),
):
    """
    Return aircraft located in a circle described by the latitude and longtidude of it's center and it's radius.
    """
    radius = min(radius, 250)
    client_ip = x_original_forwarded_for

    res = await provider.ReAPI.request(
        params=[f"circle={lat},{lon},{radius}"], client_ip=client_ip
    )
    return res


if __name__ == "__main__":
    print("Run with:")
    print("uvicorn app:app --host 0.0.0.0 --port 80")
