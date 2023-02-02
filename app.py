import asyncio
import aiohttp
import aiohttp_jinja2
import jinja2
import random
import uuid

from pygeodesy.sphericalTrigonometry import LatLon
from aiohttp import web
from collections import defaultdict

routes = web.RouteTableDef()


async def fetch_remote_data(app):
    try:
        while True:
            async with aiohttp.ClientSession() as session:
                # readsb update
                addrs = ["ingest-readsb:150"]
                readsb_clients = []
                readsb_receivers = []
                for addr in addrs:
                    async with session.get(f"http://{addr}/clients.json") as resp:
                        data = await resp.json()
                        readsb_clients.extend(data["clients"])

                    async with session.get(f"http://{addr}/receivers.json") as resp:
                        data = await resp.json()
                        readsb_receivers.extend(data["receivers"])

                clients_by_hex = merge_readsb_jsons(readsb_clients, readsb_receivers)

                # MLAT-server update
                addrs = ["mlat-mlat-server:150"]
                mlat_clients = []
                for addr in addrs:
                    async with session.get(f"http://{addr}/mlat-clients.json") as resp:
                        data = await resp.json()
                        mlat_clients.extend(data.values())

                for client in mlat_clients:
                    _hex = client["uuid"]
                    if _hex not in clients_by_hex:
                        continue

                    clients_by_hex[_hex]["mlat_enabled"] = True

                    mlat_name = client["user"]
                    clients_by_hex[_hex]["mlat_name"] = mlat_name

                    privacy = client["privacy"]
                    if not privacy:
                        lat, lon = client["lat"], client["lon"]
                        clients_by_hex[_hex]["lat"] = lat
                        clients_by_hex[_hex]["lon"] = lon

                clients_by_ip = defaultdict(list)
                receivers = []

                for _hex in clients_by_hex.keys():
                    # anonymize location data
                    lat, lon = round(clients_by_hex[_hex]["lat"], 2), round(clients_by_hex[_hex]["lon"], 2)
                    random.seed(app["rng_seed"] + uuid.UUID(_hex).int)
                    bearing = random.randint(0, 360)
                    r = 1000 * random.randint(2, 8)  # 2 - 8 km
                    new_lat, new_lon = LatLon(lat, lon).destination(r, bearing).latlon2(ndigits=2)
                    clients_by_hex[_hex]["lat"], clients_by_hex[_hex]["lon"] = new_lat, new_lon

                    # populate clients_by_ip dict
                    ip = clients_by_hex[_hex]["ip"]
                    clients_by_ip[ip].append(clients_by_hex[_hex])

                    # populate receivers list
                    mlat_enabled = clients_by_hex[_hex]["mlat_enabled"]
                    mlat_name = clients_by_hex[_hex]["mlat_name"]
                    lat, lon = clients_by_hex[_hex]["lat"], clients_by_hex[_hex]["lon"]
                    receivers.append({
                        "lat": lat,
                        "lon": lon,
                        "name": mlat_name,
                        "mlat": mlat_enabled,
                    })

                app["clients_by_hex"] = clients_by_hex
                app["clients_by_ip"] = clients_by_ip
                app["receivers"] = receivers

            await asyncio.sleep(30)
    except asyncio.CancelledError:
        print("Background task cancelled")

def merge_readsb_jsons(clients, receivers):
    clients_by_hex = {}

    for client in clients:
        _hex = client[0]
        ip = client[1].split()[1]
        kbps = client[2]
        conn_time = client[3]
        msg_s = client[4]
        position_s = client[5]
        reduce_signal = client[6]
        positions = client[8]

        client_dict = {
            "hex": _hex,
            "ip": ip,
            "kbps": kbps,
            "conn_time": conn_time,
            "msg_s": msg_s,
            "position_s": position_s,
            "reduce_signal": reduce_signal,
            "positions": positions,
            "lat": None,
            "lon": None,
            "mlat_enabled": False,
            "mlat_name": None,
        }

        clients_by_hex[_hex] = client_dict

    for client in receivers:
        _hex = client[0]
        lat, lon = client[8], client[9]

        clients_by_hex[_hex]["lat"] = lat
        clients_by_hex[_hex]["lon"] = lon

    return clients_by_hex


@routes.get("/")
async def index(request):
    req_ip = request.headers["X-Original-Forwarded-For"]
    clients = request.app["clients_by_ip"].get(req_ip, [])
    context = {
        "clients": clients,
        "ip": req_ip,
        "len": len(request.app["clients_by_hex"].keys())
    }

    return aiohttp_jinja2.render_template(
        "index.html", request, context
    )

    # Return a template index.html with the clients, pass the clients to the template which is a index.html file

@routes.get("/receivers")
async def receivers(request):
    return web.json_response(request.app["receivers"])

async def background_tasks(app):
    app["fetch_remote_data"] = asyncio.create_task(fetch_remote_data(app))

    yield

    app["fetch_remote_data"].cancel()
    await app["fetch_remote_data"]


# aiohttp server
app = web.Application()
app.add_routes(routes)
app["rng_seed"] = random.getrandbits(128)
app["clients_by_ip"] = {}
app["clients_by_hex"] = {}
app["receivers"] = []

# add background task
app.cleanup_ctx.append(background_tasks)

if __name__ == "__main__":
    aiohttp_jinja2.setup(app, loader=jinja2.FileSystemLoader('/app/templates'))
    web.run_app(app, host="0.0.0.0", port=80)
