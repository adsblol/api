import asyncio
import csv
import gzip
import hashlib
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
from adsb_api.utils.settings import (INGEST_DNS, INGEST_HTTP_PORT, MLAT_SERVERS, REAPI_ENDPOINT, REDIS_KEY_BEAST_CLIENTS, REDIS_KEY_BEAST_RECEIVERS, REDIS_KEY_HUB_AIRCRAFT, REDIS_KEY_MLAT_CLIENTS, REDIS_KEY_MLAT_SYNC, REDIS_KEY_MLAT_TOTALCOUNT, SALT_MLAT, SALT_MY, STATS_URL)

_HOSTNAME = gethostname()
_UNKNOWN_ROUTE = {"callsign": "", "number": "unknown", "airline_code": "unknown", "airport_codes": "unknown", "_airport_codes_iata": "unknown", "_airports": []}


async def _locked(r: redis.Redis, name: str, ttl: int, coro):
    """Execute coro only if lock acquired."""
    if await r.set(f"lock:{name}", f"{_HOSTNAME}:{uuid.uuid4()}", nx=True, ex=ttl):
        try:
            return await coro()
        finally:
            await r.eval("if redis.call('get', KEYS[1]):find(ARGV[1]) == 1 then return redis.call('del', KEYS[1]) end", 1, f"lock:{name}", f"{_HOSTNAME}:")


class Base: ...

def _background_task(interval: int, lock: str, lock_expire: int, success_interval: int | None = None):
    """Decorator to mark a method as a background task.

    Args:
        interval: Default sleep interval between runs (seconds)
        lock: Redis lock name prefix
        lock_expire: Lock TTL (seconds)
        success_interval: Optional sleep interval when task returns True
    """
    def decorator(func):
        func._bg_task_config = {
            "interval": interval,
            "lock": lock,
            "lock_expire": lock_expire,
            "success_interval": success_interval,
        }
        return func
    return decorator


class BackgroundTaskMixin:
    """Mixin for classes that run background tasks with Redis locking."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._bg_task_handles = []

    async def start_bg_tasks(self, enabled_tasks: set[str] | None = None):
        """Start all @background_task decorated methods."""
        for attr_name in dir(self):
            attr = getattr(self, attr_name)
            if hasattr(attr, "_bg_task_config"):
                config = attr._bg_task_config
                matched = enabled_tasks is None or attr_name in enabled_tasks or attr_name.lstrip("_") in enabled_tasks
                if matched:
                    self._bg_task_handles.append(asyncio.create_task(self._run_bg_task(attr_name, attr, config)))

    async def stop_bg_tasks(self):
        """Cancel all background tasks."""
        for handle in self._bg_task_handles:
            handle.cancel()
        if self._bg_task_handles:
            await asyncio.gather(*self._bg_task_handles, return_exceptions=True)
        self._bg_task_handles.clear()

    async def _run_bg_task(self, name: str, coro, config: dict):
        """Run a background task with Redis locking and sleep interval."""
        interval = config["interval"]
        lock = config["lock"]
        lock_expire = config["lock_expire"]
        success_interval = config.get("success_interval")

        while True:
            try:
                async def _():
                    return await coro()

                result = await _locked(self.redis, lock, lock_expire, _)
            except Exception as e:
                print(f"[{self.__class__.__name__}] Task {name} error: {e}")
                traceback.print_exc()

            # Determine sleep interval
            sleep_time = interval
            if success_interval is not None and result is True:
                sleep_time = success_interval

            await asyncio.sleep(sleep_time)


@lru_cache(1024)
def _salty(uuid_val: str, salt: str) -> str:
    return str(uuid.UUID(bytes=hashlib.sha3_256(f"{uuid_val}{salt}".encode()).digest()[:16]))


def _humanhash(uuid: str, salt: str) -> str:
    return humanhash.humanize(_salty(uuid, salt).replace("-", ""), words=4)


class Provider(BackgroundTaskMixin, Base):
    # Redis helpers for JSON data
    async def _json_get(self, key: str):
        data = await self.redis.get(key)
        return orjson.loads(data) if data else None

    async def _json_gets(self, keys: list[str]) -> dict:
        """Get multiple JSON values in parallel."""
        vals = await self.redis.mget(keys)
        return {k: orjson.loads(v) for k, v in zip(keys, vals) if v}
    def __init__(self, enabled_bg_tasks):
        super().__init__()
        self.ReAPI = ReAPI(REAPI_ENDPOINT)
        self.redis = self.resolver = None
        self.redis_connection_string = None
        self.enabled_bg_tasks = enabled_bg_tasks
        self._session = None

    async def startup(self):
        self.redis = await redis.from_url(self.redis_connection_string)
        self._session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=5, connect=1))
        self.resolver = aiodns.DNSResolver()
        await self.start_bg_tasks(self.enabled_bg_tasks)

    async def shutdown(self):
        await self.stop_bg_tasks()
        await self._session.close()

    @_background_task(interval=10, lock="hub_stats", lock_expire=10)
    async def _fetch_hub_stats(self):
        print(f"[_fetch_hub_stats] Fetching from {STATS_URL}")
        try:
            async with self._session.get(STATS_URL) as r:
                print(f"[_fetch_hub_stats] Status: {r.status}")
                if r.status == 200:
                    data = await r.json()
                    aircraft_count = data.get("aircraft_with_pos")
                    print(f"[_fetch_hub_stats] aircraft_with_pos: {aircraft_count}")
                    await self.redis.set(REDIS_KEY_HUB_AIRCRAFT, aircraft_count, ex=15)
                    print(f"[_fetch_hub_stats] Set Redis key {REDIS_KEY_HUB_AIRCRAFT}")
        except Exception as e:
            print(f"[_fetch_hub_stats] Error: {e}")
            traceback.print_exc()

    @_background_task(interval=5, lock="ingest", lock_expire=8)
    async def _fetch_ingest(self):
        print(f"[_fetch_ingest] Resolving {INGEST_DNS}")
        try:
            print(f"[_fetch_ingest] resolver={self.resolver}, session={self._session}")
            ips = [x.host for x in await self.resolver.query(INGEST_DNS, "A")]
            print(f"[_fetch_ingest] Resolved IPs: {ips}, fetching from {len(ips)} servers")
            results = await asyncio.gather(*(self._fetch_one(ip) for ip in ips))
            print(f"[_fetch_ingest] Gather results: {results}")

            clients, receivers = [], []
            for r in results:
                if r:
                    clients.extend(r.get("clients", []))
                    receivers.extend(r.get("receivers", []))

            print(f"[_fetch_ingest] Got {len(clients)} clients, {len(receivers)} receivers")
            await self.redis.set(REDIS_KEY_BEAST_CLIENTS, orjson.dumps(self._dedupe(clients)), ex=15)
            await self.redis.set(REDIS_KEY_BEAST_RECEIVERS, orjson.dumps(receivers), ex=15)
            print(f"[_fetch_ingest] Set Redis keys")
        except Exception as e:
            print(f"[_fetch_ingest] Error: {e}")
            traceback.print_exc()

    async def _fetch_one(self, ip: str) -> dict | None:
        try:
            url = f"http://{ip}:{INGEST_HTTP_PORT}/"
            clients, receivers = None, None

            async def get_clients():
                nonlocal clients
                async with self._session.get(url + "clients.json") as r:
                    clients = (await r.json()).get("clients", []) if r.status == 200 else []

            async def get_receivers():
                nonlocal receivers
                async with self._session.get(url + "receivers.json") as r:
                    if r.status == 200:
                        receivers = (await r.json()).get("receivers", [])
                        pipe = self.redis.pipeline()
                        for recv in receivers:
                            pipe.set(f"receiver:{recv[0]}", orjson.dumps(recv), ex=60)
                            pipe.set(f"my:{_humanhash(recv[0], SALT_MY)}", recv[0], ex=60)
                        await pipe.execute()

            await asyncio.gather(get_clients(), get_receivers())
            for r in receivers or []:
                r[8], r[9] = round(r[8], 1), round(r[9], 1)
            print(f"[_fetch_one {ip}] Got {len(clients or [])} clients, {len(receivers or [])} receivers")
            return {"clients": clients, "receivers": receivers}
        except Exception as e:
            print(f"[_fetch_one {ip}] Error: {e}")
            traceback.print_exc()
            return None

    def _dedupe(self, clients: list) -> list:
        seen, uniq = set(), []
        for c in clients:
            key = (c[0], c[1].split()[1])
            if key not in seen:
                seen.add(key)
                uniq.append({"uuid": c[0][:13] + "-...", "_uuid": c[0], "adsblol_my_url": f"https://{_humanhash(c[0][:18], SALT_MY)}.my.adsb.lol",
                            "ip": c[1].split()[1], "kbps": c[2], "connected_seconds": c[3], "messages_per_second": c[4],
                            "positions_per_second": c[5], "positions": c[8], "ms": c[7]})
        return uniq

    @_background_task(interval=5, lock="mlat", lock_expire=8)
    async def _fetch_mlat(self):
        data, clients = {}, {}

        async def fetch(srv):
            sv = srv.split("-")[-1].upper()
            try:
                async with self._session.get(f"http://{srv}:150/sync.json", timeout=aiohttp.ClientTimeout(total=10)) as r:
                    if r.status == 200:
                        data[sv] = {n: {"lat": v["lat"], "lon": v["lon"], "bad_syncs": v.get("bad_syncs", -1), "peers": {_salty(p, SALT_MLAT): pv for p, pv in v.get("peers", {}).items()}} for n, v in (await r.json()).items()}
                        print(f"[_fetch_mlat] Fetched sync from {sv}: {len(data[sv])} entries")
                async with self._session.get(f"http://{srv}:150/clients.json", timeout=aiohttp.ClientTimeout(total=10)) as r:
                    if r.status == 200:
                        clients[sv] = await r.json()
                        print(f"[_fetch_mlat] Fetched clients from {sv}")
            except Exception as e:
                print(f"[_fetch_mlat] Error fetching from {srv}: {e}")

        print(f"[_fetch_mlat] Fetching from {MLAT_SERVERS}")
        await asyncio.gather(*(fetch(s) for s in MLAT_SERVERS))
        print(f"[_fetch_mlat] Got data from {len(data)} servers, clients from {len(clients)} servers")
        await self.redis.set(REDIS_KEY_MLAT_SYNC, orjson.dumps(data), ex=15)
        await self.redis.set(REDIS_KEY_MLAT_CLIENTS, orjson.dumps(clients), ex=15)
        await self.redis.set(REDIS_KEY_MLAT_TOTALCOUNT, orjson.dumps({"UPDATED": datetime.now().strftime("%a %b %d %H:%M:%S UTC %Y"), **{sv: [len(d), 1337, 0] for sv, d in data.items()}}), ex=15)
        print(f"[_fetch_mlat] Set Redis keys")

    async def get_clients_per_client_ip(self, ip: str) -> list:
        clients = await self._json_get(REDIS_KEY_BEAST_CLIENTS) or []
        return [{k: v for k, v in c.items() if not k.startswith("_")} for c in clients if c["ip"] == ip]

    async def mlat_clients_to_list(self, ip: str) -> list:
        keys = ("user", "privacy", "connection", "peer_count", "bad_sync_timeout", "outlier_percent")
        mlat_clients = await self._json_get(REDIS_KEY_MLAT_CLIENTS) or {}
        r = []
        for d in mlat_clients.values():
            for c in d.values():
                if c.get("source_ip") == ip:
                    o = {k: c[k] for k in keys if k in c}
                    u = c.get("uuid")
                    if isinstance(u, list) and u:
                        o["uuid"] = u[0][:13] + "-..."
                    elif isinstance(u, str):
                        o["uuid"] = u[:13] + "-..."
                    else:
                        o["uuid"] = None
                    r.append(o)
        return r


class RedisVRS(BackgroundTaskMixin, Base):
    def __init__(self):
        super().__init__()
        self.redis = self._session = None
        self.redis_connection_string = None

    async def connect(self):
        self.redis = await redis.from_url(self.redis_connection_string)
        self._session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10))

    async def shutdown(self):
        await self.stop_bg_tasks()
        if self._session:
            await self._session.close()

    async def dispatch_background_task(self):
        await self.start_bg_tasks()

    @_background_task(interval=60, lock="vrs_csv", lock_expire=3600, success_interval=3600)
    async def _loop(self):
        print("[RedisVRS._loop] Starting CSV fetch")
        for name, url in (("route", "https://vrs-standing-data.adsb.lol/routes.csv.gz"), ("airport", "https://vrs-standing-data.adsb.lol/airports.csv.gz")):
            try:
                async with self._session.get(url) as r:
                    if r.status == 200:
                        pipe = self.redis.pipeline()
                        count = 0
                        for row in gzip.decompress(await r.read()).decode().splitlines():
                            pipe.set(f"vrs:{name}:{row.split(',')[0]}", row)
                            count += 1
                        await pipe.execute()
                        print(f"[RedisVRS._loop] Fetched {name}: {count} rows")
                    else:
                        print(f"[RedisVRS._loop] Failed to fetch {name}: status {r.status}")
            except Exception as e:
                print(f"[RedisVRS._loop] Error fetching {name}: {e}")
                traceback.print_exc()
        return True

    async def mget(self, keys: list[str]) -> list:
        return [v.decode() if v else None for v in await self.redis.mget(keys)] if keys else []

    async def get_airport(self, icao: str) -> dict | None:
        d = await self.redis.get(f"vrs:airport:{icao}")
        if not d:
            return None
        try:
            _, n, _, i, l, c, la, lo, a = list(csv.reader([d.decode()]))[0]
            return {"name": n, "icao": icao, "iata": i, "location": l, "countryiso2": c, "lat": float(la), "lon": float(lo), "alt_feet": float(a), "alt_meters": round(float(a) * 0.3048, 2)}
        except (ValueError, IndexError, csv.Error):
            return None

    async def _route(self, callsign: str, vrsroute: str) -> dict:
        _, _, num, airline, airports = vrsroute.split(",")
        route = {**_UNKNOWN_ROUTE, "callsign": callsign, "number": num, "airline_code": airline, "airport_codes": airports}
        if airports == "unknown":
            return route

        ap_data = await asyncio.gather(*(self.get_airport(a) for a in airports.split("-")))
        route["_airports"] = [a for a in ap_data if a]
        route["_airport_codes_iata"] = airports

        for ap, data in zip(airports.split("-"), ap_data):
            if data and len(ap) == 4 and data.get("iata"):
                route["_airport_codes_iata"] = route["_airport_codes_iata"].replace(ap, data["iata"])
        return route

    async def get_route(self, callsign: str) -> dict:
        v = await self.redis.get(f"vrs:route:{callsign}")
        return await self._route(callsign, v.decode()) if v else {**_UNKNOWN_ROUTE, "callsign": callsign}

    async def get_routes_bulk(self, callsigns: list[str]) -> dict:
        if not callsigns:
            return {}
        vals = await self.mget([f"vrs:route:{cs}" for cs in callsigns])
        # Parallel _route() calls instead of sequential
        pairs = [(cs, v) for cs, v in zip(callsigns, vals) if v]
        results = await asyncio.gather(*(self._route(cs, v) for cs, v in pairs))
        return {cs: route for (cs, _), route in zip(pairs, results)}

    async def get_cached_route(self, callsign: str) -> dict | None:
        v = await self.redis.get(f"vrs:routecache:{callsign}")
        return orjson.loads(v) if v else None

    async def get_cached_routes_bulk(self, callsigns: list[str]) -> dict:
        if not callsigns:
            return {}
        vals = await self.mget([f"vrs:routecache:{cs}" for cs in callsigns])
        return {cs: (orjson.loads(v) if v else None) for cs, v in zip(callsigns, vals)}

    async def cache_route(self, callsign: str, plausible: bool, route: dict):
        await self.redis.set(f"vrs:routecache:{callsign}", orjson.dumps(route), ex=1200 if plausible else 60)


class FeederData(BackgroundTaskMixin, Base):
    def __init__(self):
        super().__init__()
        self.redis = self._session = self._resolver = None
        self.redis_connection_string = None

    async def connect(self):
        self.redis = await redis.from_url(self.redis_connection_string)
        self._resolver = aiodns.DNSResolver()
        self._session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=5, connect=1))

    async def shutdown(self):
        await self.stop_bg_tasks()
        await self._session.close()

    async def dispatch_background_task(self):
        await self.start_bg_tasks()

    @_background_task(interval=5, lock="feeder_data", lock_expire=10)
    async def _loop(self):
        try:
            async with asyncio.timeout(10):
                print("[FeederData._loop] Resolving ingest DNS")
                ips = [x.host for x in await self._resolver.query(INGEST_DNS, "A")]
                print(f"[FeederData._loop] Resolved IPs: {ips}")
                results = await asyncio.gather(*(self._fetch(ip) for ip in ips), return_exceptions=True)
                pipe, recv_ingest = self.redis.pipeline(), {}

                for ip, data in zip(ips, results):
                    if isinstance(data, Exception):
                        print(f"[FeederData._loop] Error from {ip}: {data}")
                        continue
                    if not data:
                        continue
                    aircraft_count = len(data.get("aircraft", []))
                    print(f"[FeederData._loop] Got {aircraft_count} aircraft from {ip}")
                    for ac in data.get("aircraft", []):
                        for r in ac.get("recentReceiverIds", []):
                            recv_ingest[r] = ip
                            pipe.zadd(f"receiver_ac:{r}", {ac["hex"]: int(asyncio.get_event_loop().time())})

                now = int(asyncio.get_event_loop().time())
                for r, ip in recv_ingest.items():
                    pipe.zremrangebyscore(f"receiver_ac:{r}", "-1", now - 60)
                    pipe.expire(f"receiver_ac:{r}", 30)
                    pipe.set(f"receiver_ingest:{r}", ip, ex=30)
                await pipe.execute()
                print(f"[FeederData._loop] Updated {len(recv_ingest)} receivers")
        except Exception as e:
            print(f"[FeederData._loop] Error: {e}")
            traceback.print_exc()

    async def _fetch(self, ip: str) -> dict | None:
        try:
            async with self._session.get(f"http://{ip}:{INGEST_HTTP_PORT}/aircraft.json") as r:
                if r.status == 200:
                    return await r.json()
        except Exception as e:
            print(f"[_fetch] Error fetching from {ip}: {e}")
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
