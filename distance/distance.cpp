#include <iostream>
#include <string>
#include <vector>

#include "SphericalUtil.hpp"
#include "PolyUtil.hpp"

void usage() {
    std::cout << "Usage:\n\n\tdistance latP lngP latA lngA [latB lngB]\n\n\tprint the sperical distance of point P from point A or of P from the great circle between A and B\n";
}

int main(int argc, char** argv) {
	if (argc != 5 && argc != 7) {
		usage();
		exit(1);
	}
	std::string pLat = argv[1];
	std::string pLng = argv[2];
	std::string aLat = argv[3];
	std::string aLng = argv[4];

	LatLng p = { std::stod(pLat), std::stod(pLng) };
	LatLng a = { std::stod(aLat), std::stod(aLng) };

	std::string bLat, bLng;
	LatLng b = { 0.0, 0.0 };
	
	double distPA = SphericalUtil::computeDistanceBetween(p, a);

	std::cout << "{\"distPA\": " << distPA / 1852.0;

	if (argc ==7) {
		std::string bLat = argv[5];
		std::string bLng = argv[6];
		LatLng b = { std::stod(bLat), std::stod(bLng) };

		double distPB = SphericalUtil::computeDistanceBetween(p, b);
		std::cout << ",\"distPB\": " << distPB / 1852.0;

		double distAB = SphericalUtil::computeDistanceBetween(a, b);
		std::cout << ",\"distAB\": " << distAB / 1852.0;

		double distPAB = PolyUtil::distanceToLine(p, a, b);
		std::cout << ",\"distPAB\": " << distPAB / 1852.0;
	}
	std::cout << "}";

	return 0;
}
