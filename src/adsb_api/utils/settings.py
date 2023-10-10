import os

ENDPOINTS = os.getenv("ADSBLOL_ENDPOINTS", "").split(",")
REDIS_HOST = os.getenv("ADSBLOL_REDIS_HOST", "redis://redis")
REDIS_TTL = int(os.getenv("ADSBLOL_REDIS_TTL", "5"))
