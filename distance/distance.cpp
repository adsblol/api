#include <iostream>
#include <string>
#include <vector>

#include "SphericalUtil.hpp"
#include "PolyUtil.hpp"

void usage() {
    std::cout << "Usage:\n\n\tdistance latP lngP latA lngA latB lngB absoluteDelta relativeDelta\n\n\tcheck if a point P is within the given thresholdsa (in meters or percentage of the distance A-B) of the great circle route between A and B.\n";
}

int main(int argc, char** argv) {
	if (argc != 9) {
		usage();
		exit(1);
	}
	LatLng p = { std::stod(argv[1]), std::stod(argv[2]) };
	LatLng a = { std::stod(argv[3]), std::stod(argv[4]) };
	LatLng b = { std::stod(argv[5]), std::stod(argv[6]) };
	double distThreshold = std::stod(argv[7]) * 1852;
	double distPercentage = std::stod(argv[8]);
	
	double distPA = SphericalUtil::computeDistanceBetween(p, a);
	double distPB = SphericalUtil::computeDistanceBetween(p, b);
	double distAB = SphericalUtil::computeDistanceBetween(a, b);

	// calculate if the point is within the given tolerance of the route
	std::vector<LatLng> route = { a, b};
	double threshold = std::max(distThreshold, distPercentage * distAB / 100.0);
	bool withinThreshold = PolyUtil::isLocationOnPath(p, route, threshold);

	std::cout << "{\"distPA\": " << distPA / 1852.0;
	std::cout << ",\"distPB\": " << distPB / 1852.0;
	std::cout << ",\"distAB\": " << distAB / 1852.0;
	std::cout << ",\"withinThreshold\": " << withinThreshold << "}";

	return 0;
}
