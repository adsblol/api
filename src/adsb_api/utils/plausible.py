import subprocess
import orjson


def plausible(
    posLat: float,
    posLng: float,
    airportALat: str,
    airportALon: str,
    airportBLat: str,
    airportBLon: str,
):
    # turn the lat/lng into strings
    posLat, posLng = str(posLat), str(posLng)
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
            "20",
        ],
        capture_output=True,
    )
    distance = orjson.loads(distanceResult.stdout)
    return distance["withinThreshold"], distance["distAB"]
