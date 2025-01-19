import asyncio
import csv
import gzip
import hashlib
import re
import traceback
import uuid
from datetime import datetime
from functools import lru_cache
from socket import gethostname

import aiodns
import aiohttp
import humanhash
import orjson
import redis.asyncio as redis

from adsb_api.utils.reapi import ReAPI
from adsb_api.utils.settings import (INGEST_DNS, INGEST_HTTP_PORT,
                                     MLAT_SERVERS, REAPI_ENDPOINT, SALT_MLAT,
                                     SALT_MY, STATS_URL)


class Base:
    async def _lock(self, name):
        key = f"lock:{name}"
        value = gethostname()

        if  not isinstance(self.redis, redis.Redis):
            print("Lock: Redis is not connected")
            return False
        try:
            print(f"Trying to Lock {key} as {value}")
            if await self.redis.set(key, value, nx=True, ex=10):
                print(f"Locked {key}:{value}")
                return True

            current_locker = await self.redis.get(key)
            if current_locker is None:
                print(f"Lock {name} is not locked")
                return False
            current_locker = current_locker.decode()
            if current_locker == value:
                print(f"Already Locked {key}")
                return True
            print(f"Lock {name} is locked by {current_locker}")
            return False
        except Exception as e:
            print("Error Locking:", e)
            return False
class Provider(Base):
    def __init__(self, enabled_bg_tasks):
        self.aircrafts = {}
        self.beast_clients = list()
        self.beast_receivers = []
        self.mlat_sync_json = {}
        self.mlat_totalcount_json = {}
        self.mlat_clients = {}
        self.aircraft_totalcount = 0
        self.ReAPI = ReAPI(REAPI_ENDPOINT)
        self.resolver = None
        self.redis = None
        self.redis_connection_string = None
        self.bg_tasks = [
            {"name": "fetch_hub_stats", "task": self.fetch_hub_stats, "instance": None},
            {"name": "fetch_ingest", "task": self.fetch_ingest, "instance": None},
            {"name": "fetch_mlat", "task": self.fetch_mlat, "instance": None},
        ]
        self.enabled_bg_tasks = enabled_bg_tasks


    async def startup(self):
        self.redis = await redis.from_url(self.redis_connection_string)
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

    # since there are multiple instances of the same API, we lock certain redis operations
    # we lock it to the hostname, because it's unique
    # we expire it after 10 seconds, because we don't want to lock it forever
    # each lock has a name (hub_stats, ingest, mlat, ...)
    # the lock returns True if it was able to lock it OR if it is locked by the same hostname
    # the lock returns False if it is locked by another hostname

    async def fetch_hub_stats(self):
        try:
            while True:
                if not await self._lock("hub_stats"):
                    print(f"hub_stats not Locked...")
                    await asyncio.sleep(5)
                    continue
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
                if not await self._lock("ingest"):
                    print(f"ingest not Locked...")
                    await asyncio.sleep(5)
                    continue
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
                            # print(len(clients), "clients")

                        async with self.client_session.get(
                            url + "receivers.json"
                        ) as resp:
                            data = await resp.json()
                            pipeline = self.redis.pipeline()
                            for receiver in data["receivers"]:
                                key = f"receiver:{receiver[0]}"
                                pipeline = pipeline.set(
                                    key, orjson.dumps(receiver), ex=60
                                )
                                # set the humanhashy of salted my uuid
                                my_humanhashy = self._humanhashy(receiver[0], SALT_MY)
                                pipeline = pipeline.set(
                                    f"my:{my_humanhashy}", receiver[0], ex=60
                                )
                                lat, lon = round(receiver[8], 1), round(receiver[9], 1)
                                receivers.append([receiver[0], lat, lon])
                            await pipeline.execute()

                    await self.set_beast_clients(clients)
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
                if not await self._lock("mlat"):
                    print(f"mlat not Locked...")
                    await asyncio.sleep(5)
                    continue
                try:
                    data_per_server = {}
                    for server in MLAT_SERVERS:
                        # server is "mlat-mlat-server-0a"
                        # let's take just 0a and make it uppercase
                        this = server.split("-")[-1].upper()
                        async with self.client_session.get(
                            f"http://{server}:150/sync.json"
                        ) as resp:
                            data_per_server[this] = self.anonymize_mlat_data(
                                await resp.json()
                            )
                    self.mlat_totalcount_json = {
                        "UPDATED": datetime.now().strftime("%a %b %d %H:%M:%S UTC %Y"),
                    }
                    for this, data in data_per_server.items():
                        self.mlat_sync_json[this] = data
                        self.mlat_totalcount_json[this] = len(data)

                    # now, we take care of the clients
                    SENSITIVE_clients = {}
                    # we put for each server the clients
                    for server in MLAT_SERVERS:
                        this = server.split("-")[-1].upper()
                        async with self.client_session.get(
                            f"http://{server}:150/clients.json"
                        ) as resp:
                            data = await resp.json()
                            SENSITIVE_clients[this] = data
                    self.mlat_clients = SENSITIVE_clients

                    await asyncio.sleep(5)
                except Exception as e:
                    traceback.print_exc()
                    print("Error in fetching mlat, retry in 10s:", e)
                    await asyncio.sleep(10)
        except asyncio.CancelledError:
            print("Background task cancelled")

    async def set_beast_clients(self, client_rows):
        """Deduplicating setter."""
        clients = {}

        for client in client_rows:
            my_url = (
                "https://" + self._humanhashy(client[0][:18], SALT_MY) + ".my.adsb.lol"
            )
            clients[(client[0], client[1].split()[1])] = {  # deduplicate by hex and ip
                # "adsblol_beast_id": self.salty_uuid(client[0], SALT_BEAST),
                # "adsblol_beast_hash": self._humanhashy(client[0], SALT_BEAST),
                "uuid": client[0][:13] + "-...",
                "_uuid": client[0],
                "adsblol_my_url": my_url,
                "ip": client[1].split()[1],
                "kbps": client[2],
                "connected_seconds": client[3],
                "messages_per_second": client[4],
                "positions_per_second": client[5],
                "positions": client[8],
                "ms": client[7],
            }

        self.beast_clients = clients.values()

    # def try_updating_redis_entry(self, key, value, salt, expiry=60):
    #     """
    #     Try to update redis entry with key and salt.
    #     """
    #     try:
    #         key = key + ":" + value
    #         self.redis.set(key, self.salty_uuid(key, salt), ex=expiry)
    #     except Exception as e:
    #         print("Error updating redis entry:", e)

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
        # format of mlat_clients:
        # { "0A": {"user": {data}}, "0B": {"user": {data}}
        for server, data in self.mlat_clients.items():
            # for name, client in self.mlat_clients.items():
            for name, client in data.items():
                if ip is not None and client["source_ip"] == ip:
                    clients_list.append(
                        {key: client[key] for key in keys_to_copy if key in client}
                    )
                    # for uuid, special handle because it's a list OR a string.
                    try:
                        if isinstance(client["uuid"], list):
                            clients_list[-1]["uuid"] = (
                                client["uuid"][0][:13] + "-..." if client["uuid"] else None
                            )
                        elif isinstance(client["uuid"], str):
                            clients_list[-1]["uuid"] = (
                                client["uuid"][:13] + "-..." if client["uuid"] else None
                            )
                        else:
                            clients_list[-1]["uuid"] = None
                    except:
                        clients_list[-1]["uuid"] = None
        return clients_list

    def anonymize_mlat_data(self, data):
        sanitized_data = {}
        for name, value in data.items():
            sanitised_peers = {}
            for peer, peer_value in value["peers"].items():
                sanitised_peers[self.maybe_salty_uuid(peer, SALT_MLAT)] = peer_value

            sanitized_data[self.maybe_salty_uuid(name, SALT_MLAT)] = {
                "lat": value["lat"],
                "lon": value["lon"],
                "bad_syncs": value.get("bad_syncs", -1),
                "peers": sanitised_peers,
            }

        return sanitized_data

    def get_clients_per_client_ip(self, ip: str, hide: bool = True) -> list:
        """
        Return Beast clients with specified ip.
        :param ip: IP address to filter on.
        :param hide: Whether to keys that starts with _.
        """
        ret = [client for client in self.beast_clients if client["ip"] == ip]
        if hide:
            ret = [
                {k: v for k, v in client.items() if not k.startswith("_")}
                for client in ret
            ]
            # sort by uuid
            ret.sort(key=lambda x: x["uuid"])
        return ret

    def get_clients_per_key_name(self, key_name: str, value: str) -> list:
        """
        Return Beast clients with specified key name.
        """
        return [client for client in self.beast_clients if client[key_name] == value]

    @lru_cache(maxsize=1024)
    def salty_uuid(self, original_uuid: str, salt: str) -> str:
        salted_bytes = original_uuid.encode() + salt.encode()
        hashed_bytes = hashlib.sha3_256(salted_bytes).digest()
        return str(uuid.UUID(bytes=hashed_bytes[:16]))

    def maybe_salty_uuid(self, string_that_might_contain_uuid: str, salt: str) -> str:
        # If the string is a UUID, return a salty UUID
        # If the string contains an UUID, return a salty UUID of the UUID, but with the rest of the string
        try:
            return self.salty_uuid(str(uuid.UUID(string_that_might_contain_uuid)), salt)
        except:
            try:
                return re.sub(
                    r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})",
                    lambda match: self.salty_uuid(str(uuid.UUID(match.group(1))), salt),
                    string_that_might_contain_uuid,
                )
            except:
                return string_that_might_contain_uuid

    @lru_cache(maxsize=1024)
    def _humanhashy(self, original_uuid: str, salt: str = None, words: int = 4) -> str:
        """
        Return a human readable hash of a UUID. The salt is optional.
        """
        if salt:
            original_uuid = self.salty_uuid(original_uuid, salt)
        # print("humanhashy", original_uuid, salt)
        return humanhash.humanize(original_uuid.replace("-", ""), words=words)


class RedisVRS(Base):
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
                    # upsert. key= name:column0, value=full row
                    # make redis transaction
                    pipeline = self.redis.pipeline()

                    for row in data.splitlines():
                        key = f"vrs:{name}:{row.split(',')[0]}"
                        pipeline = pipeline.set(key, row)
                    print("vrsx y", len(pipeline))
                    await pipeline.execute()

    async def _background_task(self):
        try:
            while True:
                if not await self._lock("background_vrs"):
                    print(f"background_vrs not Locked...")
                    await asyncio.sleep(5)
                    continue
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
            # print("vrsx didn't have data on", callsign)
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
        # print("vrsx", callsign, data)
        _, code, number, airlinecode, airportcodes = data.split(",")
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
        # print("vrsx", icao, data)
        try:
            __, name, _, iata, location, countryiso2, lat, lon, alt_feet = list(
                csv.reader([data])
            )[0]
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
        except:
            # print(f"CSV-parsing: exception for {data}")
            ret = None
        return ret

    # Add callsign to cache
    async def set_plausible(self, callsign: str, valid: int):
        expiry = 3600 if valid == 1 else 60
        await self.redis.set(f"vrs:plausible:{callsign}", valid, ex=expiry)

    async def is_plausible(self, callsign):
        cached = await self.redis.get(f"vrs:plausible:{callsign}")
        if not cached:
            return None
        return int(cached.decode())


class FeederData(Base):
    def __init__(self, redis=None):
        self.redis_connection_string = redis
        self.redis = None
        self.background_task = None
        self.resolver = None
        self.client_session = None
        self.redis_aircrafts_updated_at = 0
        self.receivers_ingests_updated_at = 0
        self.ingest_aircrafts = {}

    async def connect(self):
        self.redis = await redis.from_url(self.redis_connection_string)
        self.resolver = aiodns.DNSResolver()
        self.client_session = aiohttp.ClientSession(
            raise_for_status=True,
            timeout=aiohttp.ClientTimeout(total=5.0, connect=1.0, sock_connect=1.0),
        )

    async def shutdown(self):
        self.background_task.cancel()
        await self.background_task
        await self.client_session.close()

    async def _update_redis_aircrafts(self, ip):
        self.redis_aircrafts_updated_at = datetime.now().timestamp()
        pipeline = self.redis.pipeline()
        aircrafts = self.ingest_aircrafts[ip]["aircraft"]
        # print(f"xxx updating redis aircrafts {ip} {len(aircrafts)}")
        for aircraft in aircrafts:
            pipeline = pipeline.set(
                f"ac:{ip}:{aircraft['hex']}",
                orjson.dumps(aircraft),
                ex=10,
            )
        await pipeline.execute()

    async def _update_aircrafts(self, ip):
        # Update aircrafts list
        # If redis_aircrafts_updated_at is more than 1s ago, update it
        url = f"http://{ip}:{INGEST_HTTP_PORT}/"
        async with self.client_session.get(url + "aircraft.json") as resp:
            data = await resp.json()
            self.ingest_aircrafts[ip] = data

        # If redis_aircrafts_updated_at is more than 1s ago, update it
        # We do this by exiting here if it has been updated recently
        if datetime.now().timestamp() - self.redis_aircrafts_updated_at > 0.5:
            self.redis_aircrafts_updated_at = datetime.now().timestamp()
            # print("xxx trying to update redis aircrafts")
            await self._update_redis_aircrafts(ip)

    async def _background_task(self):
        try:
            while True:
                if not await self._lock("background_feederdata"):
                    print(f"background_feederdata not Locked...")
                    await asyncio.sleep(5)
                    continue
                try:
                    ips = [
                        record.host
                        for record in (await self.resolver.query(INGEST_DNS, "A"))
                    ]
                    receivers = 0
                    receivers_ingests = {}
                    for ip in list(self.ingest_aircrafts.keys()):
                        if ip not in ips:
                            del self.ingest_aircrafts[ip]
                    for ip in ips:
                        await self._update_aircrafts(ip)
                        data = self.ingest_aircrafts[ip]
                        pipeline = self.redis.pipeline()
                        for aircraft in data["aircraft"]:
                            for receiver in aircraft.get("recentReceiverIds", []):
                                receivers += 1
                                receivers_ingests[receiver] = ip
                                # zadd to key with score=now,
                                key = f"receiver_ac:{receiver}"
                                pipeline = pipeline.zadd(
                                    key,
                                    {aircraft["hex"]: int(datetime.now().timestamp())},
                                )
                    pipeline = self._try_updating_receivers_ingests(
                        pipeline, receivers_ingests
                    )
                    # print("Pipeline: ", pipeline)
                    await pipeline.execute()

                    # print("FeederData: Got data from", receivers, "receivers")

                    await asyncio.sleep(0.1)

                except Exception as e:
                    traceback.print_exc()
                    print("Error in background task, retry in 5s:", e)
                    await asyncio.sleep(5)
        except asyncio.CancelledError:
            print("FeederData cancelled")

    def _try_updating_receivers_ingests(self, pipeline, receivers_ingests):
        if datetime.now().timestamp() - self.receivers_ingests_updated_at < 0.2:
            # ^ if it has been updated recently, don't update it
            return pipeline
        self.receivers_ingests_updated_at = datetime.now().timestamp()
        for receiver, ip in receivers_ingests.items():
            pipeline = pipeline.zremrangebyscore(
                f"receiver_ac:{receiver}",
                -1,
                int(datetime.now().timestamp() - 60),
            )
            pipeline = pipeline.expire(f"receiver_ac:{receiver}", 30)
            pipeline = pipeline.set(
                "receiver_ingest:" + receiver,
                ip,
                ex=30,
            )
        return pipeline

    async def dispatch_background_task(self):
        self.background_task = asyncio.create_task(self._background_task())

    async def get_aircraft(self, receiver):
        # get only last 10 seconds
        data = await self.redis.zrange(
            f"receiver_ac:{receiver}",
            -1,
            int(datetime.now().timestamp()),
            byscore=True,
        )
        # print("get_aircraft", receiver, data)
        if not data:
            return None
        ret = []
        if ingest := await self.redis.get("receiver_ingest:" + receiver):
            ingest = ingest.decode()
        else:
            print("error ingest not found")
            return ret

        for ac in data:
            ac = ac.decode()
            ac_data = await self.redis.get(f"ac:{ingest}:{ac}")
            if ac_data is None:
                continue
            ret.append(orjson.loads(ac_data.decode()))
        return ret
