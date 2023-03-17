import os

ENDPOINTS = os.getenv("ADSBLOL_ENDPOINTS", "").split(",")
REDIS_HOST = os.getenv("ADSBLOL_REDIS_HOST", "redis://redis")
REDIS_TTL = int(os.getenv("ADSBLOL_REDIS_TTL", "5"))
REAPI_ENDPOINT = os.getenv(
    "ADSBLOL_REAPI_ENDPOINT", "http://reapi-readsb:30152/re-api/"
)
STATS_URL = os.getenv("ADSBLOL_STATS_URL", "http://hub-readsb:150/stats.json")
ENABLED_BG_TASKS = os.getenv(
    "ADSBLOL_ENABLED_BG_TASKS", "fetch_hub_stats,fetch_ingest,fetch_mlat"
).split(",")
