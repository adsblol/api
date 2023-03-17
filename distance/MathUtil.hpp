//******************************************************************************
// Copyright 2013 Google Inc.
// https://github.com/googlemaps/android-maps-utils/blob/master/library/src/main/java/com/google/maps/android/MathUtil.java
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

#ifndef GEOMETRY_LIBRARY_MATH_UTIL
#define GEOMETRY_LIBRARY_MATH_UTIL

#include <cmath>
#include <algorithm>

#define M_PI 3.14159265358979323846

inline double deg2rad(double degrees) {
    return degrees * M_PI / 180.0;
}

inline double rad2deg(double angle) {
    return angle * 180.0 / M_PI;
}

class MathUtil {
public:
    /**
     * The earth's radius, in meters.
     * Mean radius as defined by IUGG.
     */
    static constexpr double EARTH_RADIUS = 6371009.0;

    /**
     * Restrict x to the range [low, high].
     */
    static inline double clamp(double x, double low, double high) {
        return x < low ? low : (x > high ? high : x);
    }

    /**
     * Wraps the given value into the inclusive-exclusive interval between min and max.
     * @param n   The value to wrap.
     * @param min The minimum.
     * @param max The maximum.
     */
    static inline double wrap(double n, double min, double max) {
        return (n >= min && n < max) ? n : (MathUtil::mod(n - min, max - min) + min);
    }

    /**
     * Returns the non-negative remainder of x / m.
     * @param x The operand.
     * @param m The modulus.
     */
    static inline double mod(double x, double m) {
        return remainder(remainder(x, m) + m, m);
    }

    /**
     * Returns mercator Y corresponding to latitude.
     * See http://en.wikipedia.org/wiki/Mercator_projection .
     */
    static inline double mercator(double lat) {
        return log(tan(lat * 0.5 + M_PI / 4.0));
    }

    /**
     * Returns latitude from mercator Y.
     */
    static inline double inverseMercator(double y) {
        return 2.0 * atan(exp(y)) - M_PI / 2.0;
    }

    /**
     * Returns haversine(angle-in-radians).
     * hav(x) == (1 - cos(x)) / 2 == sin(x / 2)^2.
     */
    static inline double hav(double x) {
        double sinHalf = sin(x * 0.5);
        return sinHalf * sinHalf;
    }

    /**
     * Computes inverse haversine. Has good numerical stability around 0.
     * arcHav(x) == acos(1 - 2 * x) == 2 * asin(sqrt(x)).
     * The argument must be in [0, 1], and the result is positive.
     */
    static inline double arcHav(double x) {
        return 2.0 * asin(sqrt(x));
    }

    // Given h==hav(x), returns sin(abs(x)).
    static inline double sinFromHav(double h) {
        return 2.0 * sqrt(h * (1.0 - h));
    }

    // Returns hav(asin(x)).
    static inline double havFromSin(double x) {
        double x2 = x * x;
        return x2 / (1.0 + sqrt(1.0 - x2)) * 0.5;
    }

    // Returns sin(arcHav(x) + arcHav(y)).
    static inline double sinSumFromHav(double x, double y) {
        double a = sqrt(x * (1 - x));
        double b = sqrt(y * (1 - y));
        return 2.0 * (a + b - 2 * (a * y + b * x));
    }

    /**
     * Returns hav() of distance from (lat1, lng1) to (lat2, lng2) on the unit sphere.
     */
    static inline double havDistance(double lat1, double lat2, double dLng) {
        return MathUtil::hav(lat1 - lat2) + MathUtil::hav(dLng) * cos(lat1) * cos(lat2);
    }
};

#endif // GEOMETRY_LIBRARY_MATH_UTIL
