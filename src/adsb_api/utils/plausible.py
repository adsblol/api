from asyncio import to_thread
from functools import lru_cache
from math import asin, cos, radians, sin, sqrt

EARTH_RADIUS = 6371000  # meters


def _hav(x: float) -> float:
    return (1 - cos(x)) / 2


def _hav_distance(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    return _hav(lat2 - lat1) + cos(lat1) * cos(lat2) * _hav(lng2 - lng1)


def _distance(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great circle distance in meters."""
    return EARTH_RADIUS * 2 * asin(sqrt(_hav_distance(lat1, lng1, lat2, lng2)))


@lru_cache(maxsize=4096)
def _plausible_sync(pos_lat: float, pos_lng: float,
                   a_lat: float, a_lng: float,
                   b_lat: float, b_lng: float) -> tuple[bool, float]:
    """Check if position is within threshold of great circle route A-B."""
    p_lat, p_lng = radians(pos_lat), radians(pos_lng)
    a_lat_r, a_lng_r = radians(a_lat), radians(a_lng)
    b_lat_r, b_lng_r = radians(b_lat), radians(b_lng)

    dist_ab = _distance(a_lat_r, a_lng_r, b_lat_r, b_lng_r) / 1852  # nautical miles
    threshold = max(50 * 1852, 0.20 * dist_ab * 1852)  # 50nm or 20%

    # Simplified check: point close to either endpoint or cross-track distance small
    hav_tolerance = _hav(threshold / EARTH_RADIUS)
    hav_dist_pa = _hav_distance(a_lat_r, a_lng_r, p_lat, p_lng)
    if hav_dist_pa <= hav_tolerance:
        return True, dist_ab

    # Cross-track approximation
    sin_dist_pa = 2 * sqrt(hav_dist_pa * (1 - hav_dist_pa))
    hav_cross_track = hav_dist_pa * (1 - cos(b_lng_r - a_lng_r)) / 2
    if hav_cross_track <= hav_tolerance:
        return True, dist_ab

    return False, dist_ab


async def plausible(pos_lat: float, pos_lng: float,
                   airport_a_lat: str, airport_a_lon: str,
                   airport_b_lat: str, airport_b_lon: str) -> tuple[bool, float]:
    """Non-blocking - runs in thread pool to avoid blocking event loop."""
    return await to_thread(
        _plausible_sync,
        pos_lat, pos_lng,
        float(airport_a_lat), float(airport_a_lon),
        float(airport_b_lat), float(airport_b_lon)
    )
