import asyncio
import csv
import gzip
import hashlib
import re
import traceback
import uuid
from datetime import datetime
from functools import lru_cache

import aiodns
import aiohttp
import humanhash
import orjson
import redis.asyncio as redis
from async_lru import alru_cache


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
            "route": "https://127.0.0.1/routes.csv.gz",
            "airport": "https://127.0.0.1/airports.csv.gz",
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

    @alru_cache(maxsize=1024)
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

    @alru_cache(maxsize=1024)
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
