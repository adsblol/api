//******************************************************************************
// Copyright 2013 Google Inc.
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//      http://www.apache.org/licenses/LICENSE-2.0
//
// This software and the related documents are provided  as is,  with no express
// or implied  warranties,  other than  those that are  expressly stated  in the
// License.
//******************************************************************************

#ifndef GEOMETRY_LIBRARY_LATLNG
#define GEOMETRY_LIBRARY_LATLNG

#include <cmath>

class LatLng {
public:
    double lat; // The latitude  of this location
    double lng; // The longitude of this location

    /**
     * Constructs a location with a latitude/longitude pair.
     *
     * @param lat   The latitude  of this location.
     * @param lng   The longitude of this location.
     */
    LatLng(double lat, double lng)
        : lat(lat), lng(lng) {}

    LatLng(const LatLng & point) = default;

    LatLng& operator=(const LatLng & other) = default;

    bool operator==(const LatLng & other) const {
        return isCoordinateEqual(lat, other.lat) && 
               isCoordinateEqual(lng, other.lng);
    }


private:
    bool isCoordinateEqual(double first, double second) const {
        return std::fabs(first - second) < 1e-12;
    }
};

#endif // GEOMETRY_LIBRARY_LATLNG
