import asyncio
import csv
import traceback
import uuid
from datetime import datetime
from functools import lru_cache

import aiohttp
import bcrypt
import redis.asyncio as redis

from .reapi import ReAPI
from .settings import REAPI_ENDPOINT, STATS_URL


class Provider(object):
    def __init__(self):
        self.beast_clients = list()
        self.beast_receivers = []
        self.mlat_sync_json = {}
        self.mlat_totalcount_json = {}
        self.mlat_clients = {}
        self.aircraft_totalcount = 0
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
                    # global update
                    print("Fetching data from", STATS_URL)
                    async with self.client_session.get(STATS_URL) as resp:
                        data = await resp.json()
                    self.aircraft_totalcount = data["aircraft_with_pos"]

                    # clients update
                    ips = ["ingest-readsb:150"]
                    print("Fetching data from", ips)
                    clients = []
                    receivers = []

                    # beast update
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

                    self.set_beast_clients(clients)
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

    def set_beast_clients(self, client_rows):
        """Deduplicating setter."""
        clients = {}

        for client in client_rows:
            clients[(client[0], client[1].split()[1])] = {  # deduplicate by hex and ip
                "hex": client[0],
                "ip": client[1].split()[1],
                "kbps": client[2],
                "conn_time": client[3],
                "msg_s": client[4],
                "position_s": client[5],
                "reduce_signal": client[6],
                "positions": client[8],
                "type": "beast",
            }

        self.beast_clients = clients.values()

    def mlat_clients_to_list(self, ip=None):
        """
        Return mlat clients with specified ip.
        """
        clients_list = []
        keys_to_copy = "user privacy connection peer_count bad_sync_timeout outlier_percent".split()

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

    def shutdown(self):
        self.background_task.cancel()

    async def download_csv_to_import(self):
        print("vrsx download_csv_to_import")
        CSVS = {
            "route": "https://vrs-standing-data.adsb.lol/routes.csv",
            "airport": "https://vrs-standing-data.adsb.lol/airports.csv",
        }
        async with aiohttp.ClientSession() as session:
            for name, url in CSVS.items():
                print("vrsx", name)
                # Download CSV
                async with session.get(url) as resp:
                    if resp.status != 200:
                        raise Exception(f"Unable to download {url}")
                    data = await resp.text()
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
            if len(airport) == 4:
                # Get IATA if exists
                if len(airport_data["iata"]) == 3:
                    ret["_airport_codes_iata"] = ret["_airport_codes_iata"].replace(
                        airport, airport_data["iata"]
                    )
            ret["_airports"].append(airport_data)
        return ret

    async def get_airport(self, icao):
        data = (await self.redis.get(f"vrs:airport:{icao}")).decode()
        print("vrsx", icao, data)
        if data is None:
            return None
        name, _, iata, location, countryiso2, lat, lon, alt_feet = data.split(",")
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
