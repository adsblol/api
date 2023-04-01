import subprocess
import orjson


def plausible(
    posLat: str,
    posLng: str,
    airportALat: str,
    airportALon: str,
    airportBLat: str,
    airportBLon: str,
):
    # check if the position is within 50nm or 10% of the total distance of the great circle route
    distanceResult = subprocess.run(
        [
            "/usr/local/bin/distance",
            posLat,
            posLng,
            airportALat,
            airportALon,
            airportBLat,
            airportBLon,
            "50",
            "20"
        ],
        capture_output=True,
    )
    distance = orjson.loads(distanceResult.stdout)
    return distance['withinThreshold'], distance['distAB']

