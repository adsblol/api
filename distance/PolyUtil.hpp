//******************************************************************************
// Copyright 2013 Google Inc.
// https://github.com/googlemaps/android-maps-utils/blob/master/library/src/main/java/com/google/maps/android/PolyUtil.java
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

#ifndef GEOMETRY_LIBRARY_POLY_UTIL
#define GEOMETRY_LIBRARY_POLY_UTIL

#include "MathUtil.hpp"
#include "SphericalUtil.hpp"


class PolyUtil {
public:
    static constexpr double DEFAULT_TOLERANCE = 0.1;  // meters

    /**
     * Computes whether the given point lies inside the specified polygon.
     * The polygon is always cosidered closed, regardless of whether the last point equals
     * the first or not.
     * Inside is defined as not containing the South Pole -- the South Pole is always outside.
     * The polygon is formed of great circle segments if geodesic is true, and of rhumb
     * (loxodromic) segments otherwise.
     */
    template <typename LatLngList>
    static inline bool containsLocation(const LatLng& point, const LatLngList& polygon, bool geodesic = false) {
        size_t size = polygon.size();

        if (size == 0) {
            return false;
        }
        double lat3 = deg2rad(point.lat);
        double lng3 = deg2rad(point.lng);
        LatLng prev = polygon[size - 1];
        double lat1 = deg2rad(prev.lat);
        double lng1 = deg2rad(prev.lng);

        size_t nIntersect = 0;

        for (auto val : polygon) {
            double dLng3 = MathUtil::wrap(lng3 - lng1, -M_PI, M_PI);
            // Special case: point equal to vertex is inside.
            if (lat3 == lat1 && dLng3 == 0) {
                return true;
            }

            double lat2 = deg2rad(val.lat);
            double lng2 = deg2rad(val.lng);

            // Offset longitudes by -lng1.
            if (PolyUtil::intersects(lat1, lat2, MathUtil::wrap(lng2 - lng1, -M_PI, M_PI), lat3, dLng3, geodesic)) {
                ++nIntersect;
            }
            lat1 = lat2;
            lng1 = lng2;
        }
        return (nIntersect & 1) != 0;
    }


    /**
     * Computes whether the given point lies on or near the edge of a polygon, within a specified
     * tolerance in meters. The polygon edge is composed of great circle segments if geodesic
     * is true, and of Rhumb segments otherwise. The polygon edge is implicitly closed -- the
     * closing segment between the first point and the last point is included.
     */
    template <typename LatLngList>
    static inline bool isLocationOnEdge(const LatLng& point, const LatLngList& polygon, double tolerance = PolyUtil::DEFAULT_TOLERANCE, bool geodesic = true) {
        return PolyUtil::isLocationOnEdgeOrPath(point, polygon, true, geodesic, tolerance);
    }


    /**
     * Computes whether the given point lies on or near a polyline, within a specified
     * tolerance in meters. The polyline is composed of great circle segments if geodesic
     * is true, and of Rhumb segments otherwise. The polyline is not closed -- the closing
     * segment between the first point and the last point is not included.
     */
    template <typename LatLngList>
    static inline bool isLocationOnPath(const LatLng& point, const LatLngList& polyline, double tolerance = PolyUtil::DEFAULT_TOLERANCE, bool geodesic = true) {
        return PolyUtil::isLocationOnEdgeOrPath(point, polyline, false, geodesic, tolerance);
    }

    /**
     * Computes whether (and where) a given point lies on or near a polyline, within a specified tolerance.
     * If closed, the closing segment between the last and first points of the polyline is not considered.
     *
     * @param point          our needle
     * @param poly           our haystack
     * @param closed         whether the polyline should be considered closed by a segment connecting the last point back to the first one
     * @param geodesic       the polyline is composed of great circle segments if geodesic
     *                       is true, and of Rhumb segments otherwise
     * @param toleranceEarth tolerance (in meters)
     * @return -1 if point does not lie on or near the polyline.
     * 0 if point is between poly[0] and poly[1] (inclusive),
     * 1 if between poly[1] and poly[2],
     * ...,
     * poly.size()-2 if between poly[poly.size() - 2] and poly[poly.size() - 1]
     */
    template <typename LatLngList>
    static inline bool isLocationOnEdgeOrPath(const LatLng& point, const LatLngList& poly, bool closed, bool geodesic, double toleranceEarth) {
        size_t size = poly.size();

        if (size == 0U) {
            return false;
        }

        double tolerance = toleranceEarth / MathUtil::EARTH_RADIUS;
        double havTolerance = MathUtil::hav(tolerance);
        double lat3 = deg2rad(point.lat);
        double lng3 = deg2rad(point.lng);
        LatLng prev = poly[closed ? size - 1 : 0];
        double lat1 = deg2rad(prev.lat);
        double lng1 = deg2rad(prev.lng);

        if (geodesic) {
            for (auto val : poly) {
                double lat2 = deg2rad(val.lat);
                double lng2 = deg2rad(val.lng);
                if (PolyUtil::isOnSegmentGC(lat1, lng1, lat2, lng2, lat3, lng3, havTolerance)) {
                    return true;
                }
                lat1 = lat2;
                lng1 = lng2;
            }
        }else {
            // We project the points to mercator space, where the Rhumb segment is a straight line,
            // and compute the geodesic distance between point3 and the closest point on the
            // segment. This method is an approximation, because it uses "closest" in mercator
            // space which is not "closest" on the sphere -- but the error is small because
            // "tolerance" is small.
            double minAcceptable = lat3 - tolerance;
            double maxAcceptable = lat3 + tolerance;
            double y1 = MathUtil::mercator(lat1);
            double y3 = MathUtil::mercator(lat3);
            double xTry[3];
            for (auto val : poly) {
                double lat2 = deg2rad(val.lat);
                double y2 = MathUtil::mercator(lat2);
                double lng2 = deg2rad(val.lng);
                if (std::max(lat1, lat2) >= minAcceptable && std::min(lat1, lat2) <= maxAcceptable) {
                    // We offset longitudes by -lng1; the implicit x1 is 0.
                    double x2 = MathUtil::wrap(lng2 - lng1, -M_PI, M_PI);
                    double x3Base = MathUtil::wrap(lng3 - lng1, -M_PI, M_PI);
                    xTry[0] = x3Base;
                    // Also explore wrapping of x3Base around the world in both directions.
                    xTry[1] = x3Base + 2 * M_PI;
                    xTry[2] = x3Base - 2 * M_PI;

                    for (auto x3 : xTry) {
                        double dy = y2 - y1;
                        double len2 = x2 * x2 + dy * dy;
                        double t = len2 <= 0 ? 0 : MathUtil::clamp((x3 * x2 + (y3 - y1) * dy) / len2, 0, 1);
                        double xClosest = t * x2;
                        double yClosest = y1 + t * dy;
                        double latClosest = MathUtil::inverseMercator(yClosest);
                        double havDist = MathUtil::havDistance(lat3, latClosest, x3 - xClosest);
                        if (havDist < havTolerance) {
                            return true;
                        }
                    }
                }
                lat1 = lat2;
                lng1 = lng2;
                y1 = y2;
            }
        }
        return false;
    }

    /**
       * Computes the distance on the sphere between the point p and the line segment start to end.
     *
     * @param p the point to be measured
     * @param start the beginning of the line segment
     * @param end the end of the line segment
     * @return the distance in meters (assuming spherical earth)
     */
    static inline double distanceToLine(const LatLng& p, const LatLng& start, const LatLng& end) {
        if (start == end) {
            return SphericalUtil::computeDistanceBetween(end, p);
        }
        double s0lat = deg2rad(p.lat);
        double s0lng = deg2rad(p.lng);
        double s1lat = deg2rad(start.lat);
        double s1lng = deg2rad(start.lng);
        double s2lat = deg2rad(end.lat);
        double s2lng = deg2rad(end.lng);
        double s2s1lat = s2lat - s1lat;
        double s2s1lng = s2lng - s1lng;
        double u = ((s0lat - s1lat) * s2s1lat + (s0lng - s1lng) * s2s1lng)
            / (s2s1lat * s2s1lat + s2s1lng * s2s1lng);
        if (u <= 0) {
            return SphericalUtil::computeDistanceBetween(p, start);
        }
        if (u >= 1) {
            return SphericalUtil::computeDistanceBetween(p, end);
        }
        LatLng su(start.lat + u * (end.lat - start.lat), start.lng + u * (end.lng - start.lng));
        return SphericalUtil::computeDistanceBetween(p, su);
    }


private:
    /**
     * Returns tan(latitude-at-lng3) on the great circle (lat1, lng1) to (lat2, lng2). lng1==0.
     * See http://williams.best.vwh.net/avform.htm .
     */
    static inline double tanLatGC(double lat1, double lat2, double lng2, double lng3) {
        return (tan(lat1) * sin(lng2 - lng3) + tan(lat2) * sin(lng3)) / sin(lng2);
    }

    /**
     * Returns mercator(latitude-at-lng3) on the Rhumb line (lat1, lng1) to (lat2, lng2). lng1==0.
     */
    static inline double mercatorLatRhumb(double lat1, double lat2, double lng2, double lng3) {
        return (MathUtil::mercator(lat1) * (lng2 - lng3) + MathUtil::mercator(lat2) * lng3) / lng2;
    }

    /**
     * Computes whether the vertical segment (lat3, lng3) to South Pole intersects the segment
     * (lat1, lng1) to (lat2, lng2).
     * Longitudes are offset by -lng1; the implicit lng1 becomes 0.
     */
    static inline double intersects(double lat1, double lat2, double lng2, double lat3, double lng3, bool geodesic) {
        // Both ends on the same side of lng3.
        if ((lng3 >= 0 && lng3 >= lng2) || (lng3 < 0 && lng3 < lng2)) {
            return false;
        }
        // Point is South Pole.
        if (lat3 <= -M_PI / 2) {
            return false;
        }
        // Any segment end is a pole.
        if (lat1 <= -M_PI / 2 || lat2 <= -M_PI / 2 || lat1 >= M_PI / 2 || lat2 >= M_PI / 2) {
            return false;
        }
        if (lng2 <= -M_PI) {
            return false;
        }
        double linearLat = (lat1 * (lng2 - lng3) + lat2 * lng3) / lng2;
        // Northern hemisphere and point under lat-lng line.
        if (lat1 >= 0 && lat2 >= 0 && lat3 < linearLat) {
            return false;
        }
        // Southern hemisphere and point above lat-lng line.
        if (lat1 <= 0 && lat2 <= 0 && lat3 >= linearLat) {
            return true;
        }
        // North Pole.
        if (lat3 >= M_PI / 2) {
            return true;
        }
        // Compare lat3 with latitude on the GC/Rhumb segment corresponding to lng3.
        // Compare through a strictly-increasing function (tan() or mercator()) as convenient.
        return geodesic ?
            tan(lat3) >= PolyUtil::tanLatGC(lat1, lat2, lng2, lng3) :
            MathUtil::mercator(lat3) >= PolyUtil::mercatorLatRhumb(lat1, lat2, lng2, lng3);
    }

    /**
     * Returns sin(initial bearing from (lat1,lng1) to (lat3,lng3) minus initial bearing
     * from (lat1, lng1) to (lat2,lng2)).
     */
    static inline double sinDeltaBearing(double lat1, double lng1, double lat2, double lng2, double lat3, double lng3) {
        double sinLat1 = sin(lat1);
        double cosLat2 = cos(lat2);
        double cosLat3 = cos(lat3);
        double lat31 = lat3 - lat1;
        double lng31 = lng3 - lng1;
        double lat21 = lat2 - lat1;
        double lng21 = lng2 - lng1;
        double a = sin(lng31) * cosLat3;
        double c = sin(lng21) * cosLat2;
        double b = sin(lat31) + 2 * sinLat1 * cosLat3 * MathUtil::hav(lng31);
        double d = sin(lat21) + 2 * sinLat1 * cosLat2 * MathUtil::hav(lng21);
        double denom = (a * a + b * b) * (c * c + d * d);
        return denom <= 0 ? 1 : (a * d - b * c) / sqrt(denom);
    }

    static inline bool isOnSegmentGC(double lat1, double lng1, double lat2, double lng2, double lat3, double lng3, double havTolerance) {
        double havDist13 = MathUtil::havDistance(lat1, lat3, lng1 - lng3);
        if (havDist13 <= havTolerance) {
            return true;
        }
        double havDist23 = MathUtil::havDistance(lat2, lat3, lng2 - lng3);
        if (havDist23 <= havTolerance) {
            return true;
        }
        double sinBearing = PolyUtil::sinDeltaBearing(lat1, lng1, lat2, lng2, lat3, lng3);
        double sinDist13 = MathUtil::sinFromHav(havDist13);
        double havCrossTrack = MathUtil::havFromSin(sinDist13 * sinBearing);
        if (havCrossTrack > havTolerance) {
            return false;
        }
        double havDist12 = MathUtil::havDistance(lat1, lat2, lng1 - lng2);
        double term = havDist12 + havCrossTrack * (1 - 2 * havDist12);
        if (havDist13 > term || havDist23 > term) {
            return false;
        }
        if (havDist12 < 0.74) {
            return true;
        }
        double cosCrossTrack = 1 - 2 * havCrossTrack;
        double havAlongTrack13 = (havDist13 - havCrossTrack) / cosCrossTrack;
        double havAlongTrack23 = (havDist23 - havCrossTrack) / cosCrossTrack;
        double sinSumAlongTrack = MathUtil::sinSumFromHav(havAlongTrack13, havAlongTrack23);
        return sinSumAlongTrack > 0;  // Compare with half-circle == PI using sign of sin().
    }
};

#endif // GEOMETRY_LIBRARY_POLY_UTIL
