import asyncio
import csv
import gzip
import hashlib
import re
import traceback
import uuid
from collections import defaultdict
from datetime import datetime
from functools import lru_cache
from socket import gethostname
from email.utils import parsedate_to_datetime

import aiodns
import aiohttp
import humanhash
import orjson
import redis.asyncio as redis

from adsb_api.utils.reapi import ReAPI
from adsb_api.utils.settings import (
    INGEST_DNS,
    INGEST_HTTP_PORT,
    MLAT_SERVERS,
    REAPI_ENDPOINT,
    SALT_MLAT,
    SALT_MY,
    STATS_URL,
)

_HOSTNAME = gethostname()


async def _acquire_lock(r: redis.Redis, name: str, ttl: int = 10) -> bool:
    """Try to acquire a distributed lock. Returns True if acquired."""
    lock_key = f"lock:{name}"
    lock_value = f"{_HOSTNAME}:{uuid.uuid4()}"
    return await r.set(lock_key, lock_value, nx=True, ex=ttl)


async def _release_lock(r: redis.Redis, name: str):
    """Release a distributed lock (only if we own it)."""
    lock_key = f"lock:{name}"
    lock_value = f"{_HOSTNAME}:"
    # Use Lua to ensure we only delete our own lock
    lua = "if redis.call('get', KEYS[1]) and redis.call('get', KEYS[1]):find(ARGV[1]) == 1 then return redis.call('del', KEYS[1]) else return 0 end"
    await r.eval(lua, 1, lock_key, lock_value)


class Base: ...


def _parse_route(vrsroute: str, callsign: str, get_airport_fn) -> dict:
    """Parse route CSV and fetch airports."""
    _, code, number, airlinecode, airportcodes = vrsroute.split(",")
    airports = airportcodes.split("-")

    return {
        "callsign": callsign,
        "number": number,
        "airline_code": airlinecode,
        "airport_codes": airportcodes,
        "_airport_codes_iata": airportcodes,
        "_airports": [],
    }


async def _enrich_route(route: dict, get_airport_fn) -> dict:
    """Add airport data to route."""
    if route["airport_codes"] == "unknown":
        return route

    airports = route["airport_codes"].split("-")
    airport_data = await asyncio.gather(*(get_airport_fn(a) for a in airports))

    route["_airports"] = [a for a in airport_data if a]
    route["_airport_codes_iata"] = route["airport_codes"]

    for ap, data in zip(airports, airport_data):
        if data and len(ap) == 4 and len(data.get("iata", "")) == 3:
            route["_airport_codes_iata"] = route["_airport_codes_iata"].replace(ap, data["iata"])

    return route


class Provider(Base):
    def __init__(self, enabled_bg_tasks):
        self.beast_clients = []
        self.beast_receivers = []
        self.mlat_sync_json = {}
        self.mlat_totalcount_json = {}
        self.mlat_clients = {}
        self.aircraft_totalcount = 0
        self.ReAPI = ReAPI(REAPI_ENDPOINT)
        self.resolver = None
        self.redis = None
        self.redis_connection_string = None
        self.enabled_bg_tasks = enabled_bg_tasks
        self._bg_tasks = []
        self._session = None

    async def startup(self):
        self.redis = await redis.from_url(self.redis_connection_string)
        self._session = aiohttp.ClientSession(
            raise_for_status=False,  # Don't raise on 4xx/5xx
            timeout=aiohttp.ClientTimeout(total=5.0, connect=1.0, sock_connect=1.0),
        )
        self.resolver = aiodns.DNSResolver()

        tasks = []
        if "fetch_hub_stats" in self.enabled_bg_tasks:
            tasks.append(asyncio.create_task(self._fetch_hub_stats()))
        if "fetch_ingest" in self.enabled_bg_tasks:
            tasks.append(asyncio.create_task(self._fetch_ingest()))
        if "fetch_mlat" in self.enabled_bg_tasks:
            tasks.append(asyncio.create_task(self._fetch_mlat()))
        self._bg_tasks = tasks

    async def shutdown(self):
        for t in self._bg_tasks:
            t.cancel()
        await asyncio.gather(*self._bg_tasks, return_exceptions=True)
        await self._session.close()

    async def _fetch_hub_stats(self):
        while True:
            if await _acquire_lock(self.redis, "hub_stats", ttl=10):
                try:
                    async with self._session.get(STATS_URL) as resp:
                        if resp.status == 200:
                            self.aircraft_totalcount = (await resp.json())["aircraft_with_pos"]
                except Exception as e:
                    print(f"Error fetching stats: {e}")
                finally:
                    await _release_lock(self.redis, "hub_stats")
            await asyncio.sleep(10)

    async def _fetch_ingest(self):
        while True:
            if await _acquire_lock(self.redis, "ingest", ttl=8):
                try:
                    ips = [r.host for r in (await self.resolver.query(INGEST_DNS, "A"))]
                    results = await asyncio.gather(*(self._fetch_one_ingest(ip) for ip in ips))

                    clients = [c for r in results if r for c in r.get("clients", [])]
                    receivers = [r for res in results if res for r in res.get("receivers", [])]

                    self.beast_clients = list(_dedupe_clients(clients))
                    self.beast_receivers = receivers
                except Exception as e:
                    print(f"Error fetching ingest: {e}")
                    traceback.print_exc()
                finally:
                    await _release_lock(self.redis, "ingest")
            await asyncio.sleep(5)

    async def _fetch_one_ingest(self, ip: str) -> dict | None:
        try:
            url = f"http://{ip}:{INGEST_HTTP_PORT}/"
            clients, receivers = None, None

            async def fetch_clients():
                nonlocal clients
                async with self._session.get(url + "clients.json") as resp:
                    if resp.status == 200:
                        clients = (await resp.json()).get("clients", [])

            async def fetch_receivers():
                nonlocal receivers
                async with self._session.get(url + "receivers.json") as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        receivers = data.get("receivers", [])
                        # Pipeline redis writes
                        pipe = self.redis.pipeline()
                        for recv in receivers:
                            uuid = recv[0]
                            pipe.set(f"receiver:{uuid}", orjson.dumps(recv), ex=60)
                            hh = _humanhashy_cached(uuid, SALT_MY)
                            pipe.set(f"my:{hh}", uuid, ex=60)
                        await pipe.execute()

            await asyncio.gather(fetch_clients(), fetch_receivers())

            if receivers:
                for r in receivers:
                    r[8], r[9] = round(r[8], 1), round(r[9], 1)  # lat, lon

            return {"clients": clients, "receivers": receivers}
        except Exception as e:
            print(f"Error fetching ingest {ip}: {e}")
            return None

    async def _fetch_mlat(self):
        while True:
            if await _acquire_lock(self.redis, "mlat", ttl=8):
                try:
                    data, clients = {}, {}

                    async def fetch_server(server):
                        sv = server.split("-")[-1].upper()
                        try:
                            async with self._session.get(f"http://{server}:150/sync.json", timeout=aiohttp.ClientTimeout(total=10)) as resp:
                                if resp.status == 200:
                                    data[sv] = _anonymize_mlat(await resp.json())
                            async with self._session.get(f"http://{server}:150/clients.json", timeout=aiohttp.ClientTimeout(total=10)) as resp:
                                if resp.status == 200:
                                    clients[sv] = await resp.json()
                        except Exception:
                            pass

                    await asyncio.gather(*(fetch_server(s) for s in MLAT_SERVERS))

                    self.mlat_sync_json = data
                    self.mlat_clients = clients
                    self.mlat_totalcount_json = {"UPDATED": datetime.now().strftime("%a %b %d %H:%M:%S UTC %Y")}
                    for sv, d in data.items():
                        self.mlat_totalcount_json[sv] = [len(d), 1337, 0]
                except Exception as e:
                    print(f"Error fetching mlat: {e}")
                finally:
                    await _release_lock(self.redis, "mlat")
            await asyncio.sleep(5)

    def get_clients_per_client_ip(self, ip: str) -> list:
        return [{k: v for k, v in c.items() if not k.startswith("_")}
                for c in self.beast_clients if c["ip"] == ip]

    @lru_cache(maxsize=1024)
    def salty_uuid(self, original_uuid: str, salt: str) -> str:
        salted_bytes = original_uuid.encode() + salt.encode()
        hashed_bytes = hashlib.sha3_256(salted_bytes).digest()
        return str(uuid.UUID(bytes=hashed_bytes[:16]))

    @lru_cache(maxsize=1024)
    def _humanhashy(self, original_uuid: str, salt: str = None) -> str:
        uuid = self.salty_uuid(original_uuid, salt) if salt else original_uuid
        return humanhash.humanize(uuid.replace("-", ""), words=4)


def _humanhashy_cached(uuid: str, salt: str) -> str:
    return humanhash.humanize(uuid.replace("-", ""), words=4)


def _dedupe_clients(clients: list) -> dict:
    deduped = {}
    for c in clients:
        key = (c[0], c[1].split()[1])  # uuid, ip
        if key not in deduped:
            my_url = f"https://{_humanhashy_cached(c[0][:18], SALT_MY)}.my.adsb.lol"
            deduped[key] = {
                "uuid": c[0][:13] + "-...",
                "_uuid": c[0],
                "adsblol_my_url": my_url,
                "ip": c[1].split()[1],
                "kbps": c[2],
                "connected_seconds": c[3],
                "messages_per_second": c[4],
                "positions_per_second": c[5],
                "positions": c[8],
                "ms": c[7],
            }
    return deduped.values()


def _anonymize_mlat(data: dict) -> dict:
    result = {}
    for name, value in data.items():
        salty_name = _salty_uuid_cached(name, SALT_MLAT)
        peers = {_salty_uuid_cached(p, SALT_MLAT): v for p, v in value.get("peers", {}).items()}
        result[salty_name] = {
            "lat": value["lat"],
            "lon": value["lon"],
            "bad_syncs": value.get("bad_syncs", -1),
            "peers": peers,
        }
    return result


@lru_cache(maxsize=1024)
def _salty_uuid_cached(uuid: str, salt: str) -> str:
    salted_bytes = uuid.encode() + salt.encode()
    return str(uuid.UUID(bytes=hashlib.sha3_256(salted_bytes).digest()[:16]))


class RedisVRS(Base):
    def __init__(self):
        self.redis_connection_string = None
        self.redis = None
        self._bg_task = None

    async def connect(self):
        self.redis = await redis.from_url(self.redis_connection_string)

    async def shutdown(self):
        if self._bg_task:
            self._bg_task.cancel()
            await self._bg_task

    async def _bg_task_loop(self):
        while True:
            if await _acquire_lock(self.redis, "vrs_csv", ttl=3600):
                try:
                    await self._download_csvs()
                except Exception as e:
                    print(f"VRS bg error: {e}")
                finally:
                    await _release_lock(self.redis, "vrs_csv")
                await asyncio.sleep(3600)
            else:
                await asyncio.sleep(60)  # Wait before retrying to acquire lock

    async def dispatch_background_task(self):
        self._bg_task = asyncio.create_task(self._bg_task_loop())

    async def _download_csvs(self):
        urls = {
            "route": "https://vrs-standing-data.adsb.lol/routes.csv.gz",
            "airport": "https://vrs-standing-data.adsb.lol/airports.csv.gz",
        }
        async with aiohttp.ClientSession() as sess:
            for name, url in urls.items():
                try:
                    async with sess.get(url) as resp:
                        if resp.status != 200:
                            continue
                        data = gzip.decompress(await resp.read()).decode("utf-8")
                        pipe = self.redis.pipeline()
                        for row in data.splitlines():
                            pipe.set(f"vrs:{name}:{row.split(',')[0]}", row)
                        await pipe.execute()
                except Exception as e:
                    print(f"Error downloading {name}: {e}")

    async def mget(self, keys: list[str]) -> list[bytes | None]:
        if not keys:
            return []
        vals = await self.redis.mget(keys)
        return [v.decode() if v else None for v in vals]

    async def get_airport(self, icao: str) -> dict | None:
        data = await self.redis.get(f"vrs:airport:{icao}")
        if not data:
            return None
        try:
            _, name, _, iata, loc, country, lat, lon, alt = list(csv.reader([data.decode()]))[0]
            return {"name": name, "icao": icao, "iata": iata, "location": loc,
                    "countryiso2": country, "lat": float(lat), "lon": float(lon),
                    "alt_feet": float(alt), "alt_meters": round(float(alt) * 0.3048, 2)}
        except:
            return None

    async def get_route(self, callsign: str) -> dict:
        vrsroute = await self.redis.get(f"vrs:route:{callsign}")
        if not vrsroute:
            return {"callsign": callsign, "number": "unknown", "airline_code": "unknown",
                    "airport_codes": "unknown", "_airport_codes_iata": "unknown", "_airports": []}

        route = _parse_route(vrsroute.decode(), callsign, self.get_airport)
        return await _enrich_route(route, self.get_airport)

    async def get_routes_bulk(self, callsigns: list[str]) -> dict[str, dict]:
        if not callsigns:
            return {}
        keys = [f"vrs:route:{cs}" for cs in callsigns]
        vals = await self.mget(keys)

        results = {}
        for cs, v in zip(callsigns, vals):
            if not v:
                continue
            route = _parse_route(v, cs, self.get_airport)
            results[cs] = await _enrich_route(route, self.get_airport)
        return results

    async def get_cached_route(self, callsign: str) -> dict | None:
        v = await self.redis.get(f"vrs:routecache:{callsign}")
        return orjson.loads(v) if v else None

    async def get_cached_routes_bulk(self, callsigns: list[str]) -> dict[str, dict | None]:
        if not callsigns:
            return {}
        keys = [f"vrs:routecache:{cs}" for cs in callsigns]
        vals = await self.mget(keys)
        return {cs: (orjson.loads(v) if v else None) for cs, v in zip(callsigns, vals)}

    async def cache_route(self, callsign: str, plausible: bool, route: dict):
        await self.redis.set(f"vrs:routecache:{callsign}", orjson.dumps(route), ex=1200 if plausible else 60)


class FeederData(Base):
    def __init__(self):
        self.redis_connection_string = None
        self.redis = None
        self._bg_task = None
        self._session = None
        self._resolver = None
        self.ingest_aircrafts = {}
        self._redis_updated_at = 0
        self._receivers_updated_at = 0

    async def connect(self):
        self.redis = await redis.from_url(self.redis_connection_string)
        self._resolver = aiodns.DNSResolver()
        self._session = aiohttp.ClientSession(
            raise_for_status=False,
            timeout=aiohttp.ClientTimeout(total=5.0, connect=1.0, sock_connect=1.0),
        )

    async def shutdown(self):
        if self._bg_task:
            self._bg_task.cancel()
            await self._bg_task
        await self._session.close()

    async def dispatch_background_task(self):
        self._bg_task = asyncio.create_task(self._bg_loop())

    async def _bg_loop(self):
        while True:
            if await _acquire_lock(self.redis, "feeder_data", ttl=10):
                try:
                    async with asyncio.timeout(10):
                        await self._bg_tick()
                except asyncio.TimeoutError:
                    pass
                except Exception as e:
                    print(f"FeederData error: {e}")
                    traceback.print_exc()
                finally:
                    await _release_lock(self.redis, "feeder_data")
            await asyncio.sleep(5)

    async def _bg_tick(self):
        ips = [r.host for r in (await self._resolver.query(INGEST_DNS, "A"))]

        # Clean stale IPs
        for ip in list(self.ingest_aircrafts.keys()):
            if ip not in ips:
                del self.ingest_aircrafts[ip]

        # Parallel fetch all IPs
        results = await asyncio.gather(*(self._fetch_aircraft(ip) for ip in ips), return_exceptions=True)

        pipe = self.redis.pipeline()
        receivers = 0
        receiver_ingests = {}

        for ip, data in zip(ips, results):
            if isinstance(data, Exception) or not data:
                continue
            for ac in data.get("aircraft", []):
                for recv in ac.get("recentReceiverIds", []):
                    receivers += 1
                    receiver_ingests[recv] = ip
                    pipe.zadd(f"receiver_ac:{recv}", {ac["hex"]: int(asyncio.get_event_loop().time())})

        # Clean old receiver entries
        now = int(asyncio.get_event_loop().time())
        for recv, ip in receiver_ingests.items():
            pipe.zremrangebyscore(f"receiver_ac:{recv}", "-1", str(now - 60))
            pipe.expire(f"receiver_ac:{recv}", 30)
            pipe.set(f"receiver_ingest:{recv}", ip, ex=30)

        await pipe.execute()

    async def _fetch_aircraft(self, ip: str) -> dict | None:
        try:
            url = f"http://{ip}:{INGEST_HTTP_PORT}/aircraft.json"
            async with self._session.get(url) as resp:
                if resp.status == 200:
                    self.ingest_aircrafts[ip] = await resp.json()
                    return self.ingest_aircrafts[ip]
        except Exception:
            pass
        self.ingest_aircrafts.setdefault(ip, {"aircraft": []})
        return None

    async def get_aircraft(self, receiver: str) -> list | None:
        ingest = await self.redis.get(f"receiver_ingest:{receiver}")
        if not ingest:
            return None

        hexes = await self.redis.zrange(f"receiver_ac:{receiver}", "-1", "+inf", byscore=True)
        if not hexes:
            return []

        results = await asyncio.gather(*(self.redis.get(f"ac:{ingest.decode()}:{h.decode()}") for h in hexes))
        return [orjson.loads(r) for r in results if r]
