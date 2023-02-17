import aiohttp


class ReAPI:
    def __init__(self, host):
        self.host = host

    async def request(self, params, request):
        ip = request.headers.get("X-Original-Forwarded-For")
        params = params.split("&")
        params.append("jv2")
        log = {"ip": ip, "params": params, "type": "reapi"}
        url = self.host + "?" + "&".join(params)

        log = {"ip": ip, "params": params, "url": url, "type": "reapi"}
        print(log)

        timeout = aiohttp.ClientTimeout(total=5.0, connect=1.0, sock_connect=1.0)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url) as response:
                response.raise_for_status()
                return await response.json()


if __name__ == "__main__":
    import asyncio

    async def main():
        reapi = ReAPI("https://re-api.adsb.lol/re-api/")
        params = "all&jv2"
        response = await reapi.request(params)
        print(response)

    asyncio.run(main())
