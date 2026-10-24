// Thin C ABI around the unmodified CGAL 6.0.1 reference algorithms.
// CGAL Partition_2 is GPL-3.0-or-later OR LicenseRef-Commercial; see README.md.
#include <CGAL/Exact_predicates_inexact_constructions_kernel.h>
#include <CGAL/Partition_traits_2.h>
#include <CGAL/partition_2.h>
#include <CGAL/version.h>
#include <algorithm>
#include <cstring>
#include <exception>
#include <list>
#include <map>
#include <vector>

#ifdef _WIN32
#define ARENA_EXPORT extern "C" __declspec(dllexport)
#else
#define ARENA_EXPORT extern "C"
#endif

#define ARENA_STRINGIFY_IMPL(value) #value
#define ARENA_STRINGIFY(value) ARENA_STRINGIFY_IMPL(value)
ARENA_EXPORT const char* arena_cgal_version() { return ARENA_STRINGIFY(CGAL_VERSION); }

// xy contains n CCW vertices of a valid simple polygon. No new vertices are
// introduced, so at most 3*n indices and n+1 offsets are required by the caller.
ARENA_EXPORT int arena_partition(const double* xy, int n, int optimal,
                                int* indices, int* offsets,
                                char* error, int error_size) {
    try {
        using Kernel = CGAL::Exact_predicates_inexact_constructions_kernel;
        using Traits = CGAL::Partition_traits_2<Kernel>;
        using Point = Kernel::Point_2;
        std::vector<Point> points;
        points.reserve(n);
        std::map<Point, int, Kernel::Less_xy_2> identifiers;
        for (int i = 0; i < n; ++i) {
            points.emplace_back(xy[2*i], xy[2*i+1]);
            identifiers.emplace(points.back(), i);
        }
        std::list<Traits::Polygon_2> result;
        if (optimal)
            CGAL::optimal_convex_partition_2(points.begin(), points.end(),
                                            std::back_inserter(result));
        else
            CGAL::approx_convex_partition_2(points.begin(), points.end(),
                                           std::back_inserter(result));
        int count = 0, cursor = 0;
        offsets[0] = 0;
        for (const auto& polygon : result) {
            for (auto it = polygon.vertices_begin(); it != polygon.vertices_end(); ++it)
                indices[cursor++] = identifiers.at(*it);
            offsets[++count] = cursor;
        }
        return count;
    } catch (const std::exception& failure) {
        const auto length = std::min(std::strlen(failure.what()), size_t(error_size-1));
        std::memcpy(error, failure.what(), length);
        error[length] = 0;
        return -1;
    }
}
