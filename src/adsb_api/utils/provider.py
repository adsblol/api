import asyncio
import csv
import gzip
import traceback
import uuid
from datetime import datetime
from functools import lru_cache

import aiodns
import aiohttp
import bcrypt
import redis.asyncio as redis

from adsb_api.utils.reapi import ReAPI
from adsb_api.utils.settings import (INGEST_DNS, INGEST_HTTP_PORT,
                                     REAPI_ENDPOINT, STATS_URL)


class Provider:
    def __init__(self, enabled_bg_tasks):
        self.beast_clients = list()
        self.beast_receivers = []
        self.mlat_sync_json = {}
        self.mlat_totalcount_json = {}
        self.mlat_clients = {}
        self.aircraft_totalcount = 0
        self.ReAPI = ReAPI(REAPI_ENDPOINT)
        self.resolver = None
        self.bg_tasks = [
            {"name": "fetch_hub_stats", "task": self.fetch_hub_stats, "instance": None},
            {"name": "fetch_ingest", "task": self.fetch_ingest, "instance": None},
            {"name": "fetch_mlat", "task": self.fetch_mlat, "instance": None},
        ]
        self.enabled_bg_tasks = enabled_bg_tasks

    async def startup(self):
        self.client_session = aiohttp.ClientSession(
            raise_for_status=True,
            timeout=aiohttp.ClientTimeout(total=5.0, connect=1.0, sock_connect=1.0),
        )
        self.resolver = aiodns.DNSResolver()
        for task in self.bg_tasks:
            if task["name"] not in self.enabled_bg_tasks:
                continue
            task["instance"] = asyncio.create_task(task["task"]())
            print(f"Started background task {task['name']}")

    async def shutdown(self):
        for task in self.bg_tasks:
            if task["instance"] is not None:
                task["instance"].cancel()
                await task["instance"]

        await self.client_session.close()

    async def fetch_hub_stats(self):
        try:
            while True:
                try:
                    async with self.client_session.get(STATS_URL) as resp:
                        data = await resp.json()
                    self.aircraft_totalcount = data["aircraft_with_pos"]
                    await asyncio.sleep(10)
                except Exception as e:
                    traceback.print_exc()
                    print("Error fetching stats, retry in 10s:", e)
                    await asyncio.sleep(10)
        except asyncio.CancelledError:
            print("Background task cancelled")

    async def fetch_ingest(self):
        try:
            while True:
                try:
                    ips = [
                        record.host
                        for record in (await self.resolver.query(INGEST_DNS, "A"))
                    ]
                    clients, receivers = [], []
                    # beast update
                    for ip in ips:
                        url = f"http://{ip}:{INGEST_HTTP_PORT}/"

                        async with self.client_session.get(
                            url + "clients.json"
                        ) as resp:
                            data = await resp.json()
                            clients += data["clients"]
                            print(len(clients), "clients")

                        async with self.client_session.get(
                            url + "receivers.json"
                        ) as resp:
                            data = await resp.json()
                            for receiver in data["receivers"]:
                                lat, lon = round(receiver[8], 1), round(receiver[9], 1)
                                receivers.append([lat, lon])

                    self.set_beast_clients(clients)
                    self.beast_receivers = receivers

                    await asyncio.sleep(5)
                except Exception as e:
                    traceback.print_exc()
                    print("Error fetching ingest, retry in 10s:", e)
                    await asyncio.sleep(10)
        except asyncio.CancelledError:
            print("Background task cancelled")

    async def fetch_mlat(self):
        try:
            while True:
                try:
                    async with self.client_session.get(
                        "http://mlat-mlat-server:150/sync.json"
                    ) as resp:
                        data = await resp.json()
                    self.mlat_sync_json = self.anonymize_mlat_data(data)
                    self.mlat_totalcount_json = {
                        "0A": len(self.mlat_sync_json),
                        "UPDATED": datetime.now().strftime("%a %b %d %H:%M:%S UTC %Y"),
                    }
                    async with self.client_session.get(
                        "http://mlat-mlat-server:150/clients.json"
                    ) as resp:
                        data = await resp.json()
                    self.mlat_clients = data

                    await asyncio.sleep(5)
                except Exception as e:
                    traceback.print_exc()
                    print("Error in fetching mlat, retry in 10s:", e)
                    await asyncio.sleep(10)
        except asyncio.CancelledError:
            print("Background task cancelled")

    def set_beast_clients(self, client_rows):
        """Deduplicating setter."""
        clients = {}

        for client in client_rows:
            clients[(client[0], client[1].split()[1])] = {  # deduplicate by hex and ip
                "hex": client[0],
                "ip": client[1].split()[1],
                "kbps": client[2],
                "connected_seconds": client[3],
                "messages_per_second": client[4],
                "positions_per_second": client[5],
                "positions": client[8],
                "type": "beast",
            }

        self.beast_clients = clients.values()

    def mlat_clients_to_list(self, ip=None):
        """
        Return mlat clients with specified ip.
        """
        clients_list = []
        keys_to_copy = [
            "user",
            "privacy",
            "connection",
            "peer_count",
            "bad_sync_timeout",
            "outlier_percent",
        ]

        for name, client in self.mlat_clients.items():
            if ip is not None and client["source_ip"] == ip:
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

    def get_clients_per_client_ip(self, ip: str) -> list:
        """
        Return Beast clients with specified ip.
        """
        return [client for client in self.beast_clients if client["ip"] == ip]

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


class RedisVRS:
    def __init__(self, redis=None):
        self.redis_connection_string = redis
        self.redis = None
        self.background_task = None

    async def shutdown(self):
        self.background_task.cancel()
        await self.background_task

    async def download_csv_to_import(self):
        print("vrsx download_csv_to_import")
        CSVS = {
            "route": "https://vrs-standing-data.adsb.lol/routes.csv.gz",
            "airport": "https://vrs-standing-data.adsb.lol/airports.csv.gz",
        }
        async with aiohttp.ClientSession() as session:
            for name, url in CSVS.items():
                print("vrsx", name)
                # Download CSV
                async with session.get(url) as resp:
                    if resp.status != 200:
                        raise Exception(f"Unable to download {url}")
                    # Decompress
                    data = await resp.read()
                    data = gzip.decompress(data).decode("utf-8")
                    # Import to Redis!
                    # upsert. key= name:column0, value=rest of row
                    # make redis transaction
                    pipeline = self.redis.pipeline()

                    for row in csv.DictReader(data.splitlines()):
                        values = list(row.values())
                        key = f"vrs:{name}:{values[0]}"
                        rest_of_row = ",".join(values[1:])
                        pipeline = pipeline.set(key, rest_of_row)
                    print("vrsx y", len(pipeline))
                    await pipeline.execute()

    async def _background_task(self):
        try:
            while True:
                try:
                    await self.download_csv_to_import()
                    await asyncio.sleep(3600)
                except Exception as e:
                    print("Error in background task, retry in 1800s:", e)
                    await asyncio.sleep(1800)
        except asyncio.CancelledError:
            print("VRS Background task cancelled")

    async def dispatch_background_task(self):
        self.background_task = asyncio.create_task(self._background_task())

    async def connect(self):
        print(self.redis_connection_string)
        self.redis = await redis.from_url(self.redis_connection_string)

    async def get_route(self, callsign):
        vrsroute = await self.redis.get(f"vrs:route:{callsign}")
        if vrsroute is None:
            print("vrsx didn't have data on", callsign)
            ret = {
                "callsign": callsign,
                "number": "unknown",
                "airline_code": "unknown",
                "airport_codes": "unknown",
                "_airport_codes_iata": "unknown",
                "_airports": [],
            }
            return ret

        data = vrsroute.decode()
        print("vrsx", callsign, data)
        code, number, airlinecode, airportcodes = data.split(",")
        ret = {
            "callsign": callsign,
            "number": number,
            "airline_code": airlinecode,
            "airport_codes": airportcodes,
            "_airport_codes_iata": airportcodes,
            "_airports": [],
        }
        # _airport_codes_iata converts ICAO to IATA if possible.
        for airport in ret["airport_codes"].split("-"):
            airport_data = await self.get_airport(airport)
            if not airport_data:
                continue
            if len(airport) == 4:
                # Get IATA if exists
                if len(airport_data["iata"]) == 3:
                    ret["_airport_codes_iata"] = ret["_airport_codes_iata"].replace(
                        airport, airport_data["iata"]
                    )
            ret["_airports"].append(airport_data)
        return ret

    async def get_airport(self, icao):
        data = await self.redis.get(f"vrs:airport:{icao}")
        if data is None:
            return None
        data = data.decode()
        print("vrsx", icao, data)
        name, _, iata, location, countryiso2, lat, lon, alt_feet = list(csv.reader([data]))[0]
        ret = {
            "name": name,
            "icao": icao,
            "iata": iata,
            "location": location,
            "countryiso2": countryiso2,
            "lat": float(lat),
            "lon": float(lon),
            "alt_feet": float(alt_feet),
            "alt_meters": float(round(int(alt_feet) * 0.3048, 2)),
        }
        return ret

    # Add callsign to cache
    async def set_plausible(self, callsign):
        # set with expiry=1h
        self.redis.set(f"vrs:plausible:{callsign}", 1)
        self.redis.expire(f"vrs:plausible:{callsign}", 3600)

    async def is_plausible(self, callsign):
        # Check if callsign is plausible according to cache
        return self.redis.get(f"vrs:plausible:{callsign}") is not None
