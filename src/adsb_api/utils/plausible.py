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
    distanceResult = subprocess.run(
        [
            "/usr/local/bin/distance",
            posLat,
            posLng,
            airportALat,
            airportALon,
            airportBLat,
            airportBLon,
        ],
        capture_output=True,
    )
    distance = orjson.loads(distanceResult.stdout)
    # lame assumption that the plane should be within
    # 50nm or 5% or route distance of the great circle route
    # no concern for direction, no handling of multi segment routes
    threshold = 50
    fivePercent = distance["distAB"] / 20
    if fivePercent > threshold:
        threshold = fivePercent
    return distance["distPAB"] < threshold, distance["distAB"]
