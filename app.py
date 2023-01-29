import asyncio
import aiohttp
import aiohttp_jinja2
import jinja2
from aiohttp import web
routes = web.RouteTableDef()

async def fetch_remote_data(app):
    try:
        while True:
            async with aiohttp.ClientSession() as session:
                ips = ["ingest-readsb:150"]
                for ip in ips:
                    clients = []
                    async with session.get(f"http://{ip}/clients.json") as resp:
                        data = await resp.json()
                        clients += data["clients"]
                        print(len(clients), "clients")
                    app["clients"] = dict_to_set(clients)
            
            await asyncio.sleep(1)
    except asyncio.CancelledError:
        print("Background task cancelled")

def dict_to_set(clients):
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
        clients_set.add((hex, ip, kbps, conn_time, msg_s, position_s, reduce_signal, positions))
    return clients_set

def get_clients_per_ip(clients, ip: str) -> list:
    return [client for client in clients if client[1] == ip]
    
@routes.get("/")
async def index(request):
    # print headers
    print(request.headers)
    clients = get_clients_per_ip(request.app["clients"], request.headers["X-Original-Forwarded-For"])
    context = {"clients": clients, "ip": request.headers["X-Original-Forwarded-For"], "len": len(request.app["clients"])}
    response = aiohttp_jinja2.render_template(
        'index.html', request, context
    )
    return response

    # Return a template index.html with the clients, pass the clients to the template which is a index.html file



async def background_tasks(app):
    app["fetch_remote_data"] = asyncio.create_task(fetch_remote_data(app))

    yield

    app["fetch_remote_data"].cancel()
    await app["fetch_remote_data"]


# aiohttp server
app = web.Application()
app.add_routes(routes)
app["clients"] = set()

# add background task
app.cleanup_ctx.append(background_tasks)

if __name__ == "__main__":
    aiohttp_jinja2.setup(app, loader=jinja2.FileSystemLoader('/app/templates'))
    web.run_app(app, host="0.0.0.0", port=80)
