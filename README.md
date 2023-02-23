# api

This is the source code for the [adsb.lol](https://adsb.lol) API.

It runs in Kubernetes and is written in Python / asyncio / aiohttp.

**This API is compatible with the ADSBExchange Rapid API. It is a drop-in replacement.**

## Documentation

Interactive documentation for the API lives at [api.adsb.lol/docs](https://api.adsb.lol/docs)

## Rate limits

Currently, there are no rate limits on the API. If you are using the API in a production environment, let me know so I don't break your app in case the API changes.

In the future, I may add rate limits to the API.

In the future, you will require an API key which you can obtain by [feeding adsb.lol](https://adsb.lol/feed).

This will be a way to ensure that the API is being used responsibly and by people who are willing to contribute to the project.
