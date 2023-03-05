import asyncio
import traceback
import uuid
from datetime import datetime
from functools import lru_cache

import aiohttp
import bcrypt

from .reapi import ReAPI
from .settings import REAPI_ENDPOINT


class Provider(object):
    def __init__(self):
        self.beast_clients = set()
        self.beast_receivers = []
        self.mlat_sync_json = {}
        self.mlat_totalcount_json = {}
        self.mlat_clients = {}
        self.ReAPI = ReAPI(REAPI_ENDPOINT)

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
