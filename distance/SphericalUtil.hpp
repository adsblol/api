//******************************************************************************
// Copyright 2013 Google Inc.
// https://github.com/googlemaps/android-maps-utils/blob/master/library/src/main/java/com/google/maps/android/SphericalUtil.java
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

#ifndef GEOMETRY_LIBRARY_SPHERICAL_UTIL
#define GEOMETRY_LIBRARY_SPHERICAL_UTIL

#include "MathUtil.hpp"
#include "LatLng.hpp"

class SphericalUtil {
public:
    /**
     * Returns the heading from one LatLng to another LatLng. Headings are
     * expressed in degrees clockwise from North within the range [-180,180).
     *
     * @return The heading in degrees clockwise from north.
     */
    inline static double computeHeading(const LatLng& from, const LatLng& to) {
        // http://williams.best.vwh.net/avform.htm#Crs
        double fromLat = deg2rad(from.lat);
        double fromLng = deg2rad(from.lng);
        double toLat = deg2rad(to.lat);
        double toLng = deg2rad(to.lng);
        double dLng = toLng - fromLng;
        double heading = atan2(
            sin(dLng) * cos(toLat),
            cos(fromLat) * sin(toLat) - sin(fromLat) * cos(toLat) * cos(dLng));

        return MathUtil::wrap(rad2deg(heading), -180, 180);
    }


    /**
     * Returns the LatLng resulting from moving a distance from an origin
     * in the specified heading (expressed in degrees clockwise from north).
     *
     * @param from     The LatLng from which to start.
     * @param distance The distance to travel.
     * @param heading  The heading in degrees clockwise from north.
     */
    inline static LatLng computeOffset(const LatLng& from, double distance, double heading) {
        distance /= MathUtil::EARTH_RADIUS;
        heading = deg2rad(heading);
        // http://williams.best.vwh.net/avform.htm#LL
        double fromLat = deg2rad(from.lat);
        double fromLng = deg2rad(from.lng);
        double cosDistance = cos(distance);
        double sinDistance = sin(distance);
        double sinFromLat = sin(fromLat);
        double cosFromLat = cos(fromLat);
        double sinLat = cosDistance * sinFromLat + sinDistance * cosFromLat * cos(heading);
        double dLng = atan2(
            sinDistance * cosFromLat * sin(heading),
            cosDistance - sinFromLat * sinLat);

        return LatLng(rad2deg(asin(sinLat)), rad2deg(fromLng + dLng));
    }



    /**
     * Returns the location of origin when provided with a LatLng destination,
     * meters travelled and original heading. Headings are expressed in degrees
     * clockwise from North. This function returns null when no solution is
     * available.
     *
     * @param to       The destination LatLng.
     * @param distance The distance travelled, in meters.
     * @param heading  The heading in degrees clockwise from north.
     */
    inline static LatLng computeOffsetOrigin(const LatLng& to, double distance, double heading) {
        heading = deg2rad(heading);
        distance /= MathUtil::EARTH_RADIUS;
        // http://lists.maptools.org/pipermail/proj/2008-October/003939.html
        double n1 = cos(distance);
        double n2 = sin(distance) * cos(heading);
        double n3 = sin(distance) * sin(heading);
        double n4 = sin(deg2rad(to.lat));
        // There are two solutions for b. b = n2 * n4 +/- sqrt(), one solution results
        // in the latitude outside the [-90, 90] range. We first try one solution and
        // back off to the other if we are outside that range.
        double n12 = n1 * n1;
        double discriminant = n2 * n2 * n12 + n12 * n12 - n12 * n4 * n4;
        
        // TODO: No real solution which would make sense in LatLng-space.
        // if (discriminant < 0) return null;
        
        double b = n2 * n4 + sqrt(discriminant);
        b /= n1 * n1 + n2 * n2;
        double a = (n4 - n2 * b) / n1;
        double fromLatRadians = atan2(a, b);
        if (fromLatRadians < -M_PI / 2 || fromLatRadians > M_PI / 2) {
            b = n2 * n4 - sqrt(discriminant);
            b /= n1 * n1 + n2 * n2;
            fromLatRadians = atan2(a, b);
        }

        // TODO: No solution which would make sense in LatLng-space.
        // if (fromLatRadians < -M_PI / 2 || fromLatRadians > M_PI / 2) return null;

        double fromLngRadians = rad2deg(to.lng) - atan2(n3, n1 * cos(fromLatRadians) - n2 * sin(fromLatRadians));
        return LatLng(rad2deg(fromLatRadians), rad2deg(fromLngRadians));
    }



    /**
     * Returns the LatLng which lies the given fraction of the way between the
     * origin LatLng and the destination LatLng.
     *
     * @param from     The LatLng from which to start.
     * @param to       The LatLng toward which to travel.
     * @param fraction A fraction of the distance to travel.
     * @return The interpolated LatLng.
     */
    inline static LatLng interpolate(const LatLng& from, const LatLng& to, double fraction) {
        // http://en.wikipedia.org/wiki/Slerp
        double fromLat = deg2rad(from.lat);
        double fromLng = deg2rad(from.lng);
        double toLat = deg2rad(to.lat);
        double toLng = deg2rad(to.lng);
        double cosFromLat = cos(fromLat);
        double cosToLat = cos(toLat);
        // Computes Spherical interpolation coefficients.
        double angle = SphericalUtil::computeAngleBetween(from, to);
        double sinAngle = sin(angle);
        if (sinAngle < 1e-6) {
            return from;
        }
        double a = sin((1 - fraction) * angle) / sinAngle;
        double b = sin(fraction * angle) / sinAngle;
        // Converts from polar to vector and interpolate.
        double x = a * cosFromLat * cos(fromLng) + b * cosToLat * cos(toLng);
        double y = a * cosFromLat * sin(fromLng) + b * cosToLat * sin(toLng);
        double z = a * sin(fromLat) + b * sin(toLat);
        // Converts interpolated vector back to polar.
        double lat = atan2(z, sqrt(x * x + y * y));
        double lng = atan2(y, x);
        return LatLng(rad2deg(lat), rad2deg(lng));
    }

    /**
     * Returns the angle between two LatLngs, in radians. This is the same as the distance
     * on the unit sphere.
     */
    inline static double computeAngleBetween(const LatLng& from, const LatLng& to) {
        return SphericalUtil::distanceRadians(deg2rad(from.lat), deg2rad(from.lng), deg2rad(to.lat), deg2rad(to.lng));
    }

    /**
     * Returns the distance between two LatLngs, in meters.
     */
    inline static double computeDistanceBetween(const LatLng& from, const LatLng& to) {
        return SphericalUtil::computeAngleBetween(from, to) * MathUtil::EARTH_RADIUS;
    }

    /**
     * Returns the length of the given path, in meters, on Earth.
     */
    template <typename LatLngList>
    inline static double computeLength(const LatLngList& path) {
        if (path.size() < 2U) {
            return 0;
        }
        double length = 0;
        LatLng prev = path[0];
        double prevLat = deg2rad(prev.lat);
        double prevLng = deg2rad(prev.lng);
        for (auto point : path) {
            double lat = deg2rad(point.lat);
            double lng = deg2rad(point.lng);
            length += SphericalUtil::distanceRadians(prevLat, prevLng, lat, lng);
            prevLat = lat;
            prevLng = lng;
        }
        return length * MathUtil::EARTH_RADIUS;
    }

    /**
     * Returns the area of a closed path on Earth.
     *
     * @param path A closed path.
     * @return The path's area in square meters.
     */
    template <typename LatLngList>
    inline static double computeArea(const LatLngList& path) {
        return abs(SphericalUtil::computeSignedArea(path));
    }

    /**
     * Returns the signed area of a closed path on Earth. The sign of the area may be used to
     * determine the orientation of the path.
     * "inside" is the surface that does not contain the South Pole.
     *
     * @param path A closed path.
     * @return The loop's area in square meters.
     */
    template <typename LatLngList>
    inline static double computeSignedArea(const LatLngList& path) {
        return SphericalUtil::computeSignedAreaP(path, MathUtil::EARTH_RADIUS);
    }


private:
    /**
     * Returns distance on the unit sphere; the arguments are in radians.
     */
    inline static double distanceRadians(double lat1, double lng1, double lat2, double lng2) {
        return MathUtil::arcHav(MathUtil::havDistance(lat1, lat2, lng1 - lng2));
    }

    /**
     * Returns the signed area of a closed path on a sphere of given radius.
     * The computed area uses the same units as the radius squared.
     * Used by SphericalUtilTest.
     */
    template <typename LatLngList>
    inline static double computeSignedAreaP(const LatLngList& path, double radius) {
        size_t size = path.size();
        if (size < 3U) { return 0; }
        double total = 0;
        LatLng prev = path[size - 1];
        double prevTanLat = tan((M_PI / 2 - deg2rad(prev.lat)) / 2);
        double prevLng = deg2rad(prev.lng);
        // For each edge, accumulate the signed area of the triangle formed by the North Pole
        // and that edge ("polar triangle").
        for (auto point : path) {
            double tanLat = tan((M_PI / 2 - deg2rad(point.lat)) / 2);
            double lng = deg2rad(point.lng);
            total += SphericalUtil::polarTriangleArea(tanLat, lng, prevTanLat, prevLng);
            prevTanLat = tanLat;
            prevLng = lng;
        }
        return total * (radius * radius);
    }

    /**
     * Returns the signed area of a triangle which has North Pole as a vertex.
     * Formula derived from "Area of a spherical triangle given two edges and the included angle"
     * as per "Spherical Trigonometry" by Todhunter, page 71, section 103, point 2.
     * See http://books.google.com/books?id=3uBHAAAAIAAJ&pg=PA71
     * The arguments named "tan" are tan((pi/2 - latitude)/2).
     */
    inline static double polarTriangleArea(double tan1, double lng1, double tan2, double lng2) {
        double deltaLng = lng1 - lng2;
        double t = tan1 * tan2;
        return 2 * atan2(t * sin(deltaLng), 1 + t * cos(deltaLng));
    }
};

#endif // GEOMETRY_LIBRARY_SPHERICAL_UTIL
