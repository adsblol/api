import os

SALT_MY = os.environ.get("ADSBLOL_API_SALT_MY")
SALT_MLAT = os.environ.get("ADSBLOL_API_SALT_MLAT")
SALT_BEAST = os.environ.get("ADSBLOL_API_SALT_BEAST")
INSECURE = os.getenv("ADSBLOL_INSECURE") is not None
ENDPOINTS = os.getenv("ADSBLOL_ENDPOINTS", "").split(",")
REDIS_HOST = os.getenv("ADSBLOL_REDIS_HOST", "redis://redis")
REDIS_TTL = int(os.getenv("ADSBLOL_REDIS_TTL", "5"))
