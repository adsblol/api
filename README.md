# api

This is the source code for the [adsb.lol](https://adsb.lol) API.

It runs in Kubernetes and is written in Python / asyncio / aiohttp.

# Usage

| Endpoint | Method | Returns |
-----------|--------|---------
| [`/v2/hex/<hex[,hex,...]>`](https://api.adsb.lol/v2/hex/485788) | GET | All aircraft with an exact match on one of the given Mode S hex ids (limited to 1000) |
| [`/v2/callsign/<callsign[,callsign,...]>`](https://api.adsb.lol/v2/callsign/KLM643) | GET | All aircraft with an exact match on one of the given callsigns (limited to 1000 or 8000 characters for the request) |
| [`/v2/reg/<reg[,reg,...]>`](https://api.adsb.lol/v2/reg/PH-BHP) | GET | All aircraft with an exact match on one of the given registrations (limited to 1000 or 8000 characters for the request) |
| [`/v2/type/<type[,type,...]>`](https://api.adsb.lol/v2/type/A321) | GET | All aircraft that have one of the specified ICAO type codes (A321, B738, etc.) |
| [`/v2/squawk/<squawk[,squawk,...]>`](https://api.adsb.lol/v2/squawk/1200) | GET | All aircraft that are squawking the specified value |
| [`/v2/mil/`](https://api.adsb.lol/v2/mil/) | GET | All aircraft tagged as military |
| [`/v2/ladd/`](https://api.adsb.lol/v2/ladd/) | GET | All aircraft tagged as LADD |
| [`/v2/pia/`](https://api.adsb.lol/v2/pia/) | GET | All aircraft tagged as PIA |
| [`/v2/point/<lat>/<lon>/<radius>`](https://api.adsb.lol/v2/point/55/55/250) | GET | All aircraft within a certain radius of a given point up to 250 nm |

## Rate limits

Currently, there are no rate limits on the API. However, if you are using the API in a production environment, please contact me. I would like to know who is using the API and how it is being used.

In the future, I may add rate limits to the API.

In the future, you will require an API key which you can obtain by [feeding adsb.lol](https://adsb.lol/feed).

This will be a way to ensure that the API is being used responsibly and by people who are willing to contribute to the project.
