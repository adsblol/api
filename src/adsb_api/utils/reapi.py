import re

import aiohttp
import orjson


class ReAPI:
    def __init__(self, host):
        self.host = host

        # allow alphanumeric + , + = + _ + .
        self.allowed = re.compile(r"^[a-zA-Z0-9,=_\.-]+$")

    def are_params_valid(self, params):
        for param in params:
            if not self.allowed.match(param):
                return False
        return True

    async def request(self, params, client_ip=None):
        if not self.are_params_valid(params):
            return {"error": "invalid params"}

        params.append("jv2")

        url = self.host + "?" + "&".join(params)
        log = {"ip": client_ip, "params": params, "url": url, "type": "reapi"}
        print(log)

        timeout = aiohttp.ClientTimeout(total=5.0, connect=1.0, sock_connect=1.0)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url) as response:
                return await response.text()


if __name__ == "__main__":
    import asyncio

    async def main():
        reapi = ReAPI("https://re-api.adsb.lol/re-api/")
        params = ["all", "jv2"]
        response = await reapi.request(params)
        print(response)

    asyncio.run(main())
