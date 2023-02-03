import os
from string import printable
import asyncio
import aiohttp
import aiohttp_jinja2
import jinja2
from aiohttp import web
import bcrypt
import secrets
from datetime import datetime

routes = web.RouteTableDef()


async def fetch_remote_data(app):
    try:
        timeout = aiohttp.ClientTimeout(total=1)
        while True:
            # clients update
            ips = ["ingest-readsb:150"]
            print("Fetching data from", ips)
            for ip in ips:
                clients = []
                receivers = []
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.get(f"http://{ip}/clients.json") as resp:
                        data = await resp.json()
                        clients += data["clients"]
                        print(len(clients), "clients")
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.get(f"http://{ip}/receivers.json") as resp:
                        data = await resp.json()
                        for receiver in data["receivers"]:
                            lat, lon = round(receiver[8], 2), round(receiver[9], 2)
                            receivers.append([lat, lon])
                print(len(receivers), "receivers")

            app["clients"] = clients_dict_to_set(clients)
            app["receivers"] = receivers

            # mlat update
            print("Fetching mlat data")
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get("http://mlat-mlat-server:150/sync.json") as resp:
                    data = await resp.json()
                    print(data)
            print("Fetched mlat data")
            temporary_dict = {}

            for name, value in data.items():
                temporary_peers = {}
                hashed_name = cachehash(app, name)
                for peer_name, _ in value["peers"].items():
                    temporary_peers[cachehash(app, peer_name)] = value

                temporary_dict[hashed_name] = [
                    value["lat"],
                    value["lon"],
                    value["bad_syncs"],
                    temporary_peers,
                ]

            app["mlat_sync_json"] = temporary_dict
            app["mlat_totalcount_json"] = {
                "0A": len(app["mlat_sync_json"]),
                "UPDATED": datetime.now().strftime("%a %b %d %H:%M:%S UTC %Y"),
            }
            print("Looped..")
            await asyncio.sleep(1)
    except asyncio.CancelledError:
        await session.close()
        print("Background task cancelled")


def clients_dict_to_set(clients):
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


def get_clients_per_ip(clients, ip: str) -> list:
    return [client for client in clients if client[1] == ip]


def cachehash(app, name):
    salt = b"$2b$04$OGq0aceBoTGtzkUfT0FGme"
    if name not in app["mlat_cached_names"]:
        print("Hashing...")
        hash = bcrypt.hashpw(name.encode(), salt).decode()
        app["mlat_cached_names"][name] = name[0:2] + "_" + hash[-12:]
    return app["mlat_cached_names"][name]


@routes.get("/")
async def index(request):
    clients = get_clients_per_ip(
        request.app["clients"], request.headers["X-Original-Forwarded-For"]
    )
    context = {
        "clients": clients,
        "ip": request.headers["X-Original-Forwarded-For"],
        "len": len(request.app["clients"]),
    }
    response = aiohttp_jinja2.render_template("index.html", request, context)
    return response

    # Return a template index.html with the clients, pass the clients to the template which is a index.html file


@routes.get("/receivers")
async def receivers(request):
    return web.json_response(request.app["receivers"])


@routes.get("/api/0/mlat-server/0A/sync.json")
async def mlat_receivers(request):
    return web.json_response(request.app["mlat_sync_json"])


@routes.get("/api/0/mlat-server/totalcount.json")
async def mlat_totalcount_json(request):
    return web.json_response(app["mlat_totalcount_json"])


async def background_tasks(app):
    app["fetch_remote_data"] = asyncio.create_task(fetch_remote_data(app))

    yield

    app["fetch_remote_data"].cancel()
    await app["fetch_remote_data"]


# aiohttp server
app = web.Application()
app.add_routes(routes)
app["clients"] = set()
app["receivers"] = []
app["mlat_sync_json"] = {}
app["mlat_totalcount_json"] = {}
app["mlat_cached_names"] = {}

# add background task
app.cleanup_ctx.append(background_tasks)

if __name__ == "__main__":
    aiohttp_jinja2.setup(app, loader=jinja2.FileSystemLoader("/app/templates"))
    web.run_app(app, host="0.0.0.0", port=80)
