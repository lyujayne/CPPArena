# CGAL reference partition backend

The included Windows x64 `arena_partition.dll` calls the unmodified CGAL 6.0.1
`approx_convex_partition_2` (Hertel–Mehlhorn) and
`optimal_convex_partition_2` (Greene) implementations. The C ABI source is
`partition.cpp`; Python loads it with ctypes, so no Python-version-specific
binding or system-wide CGAL installation is needed to run this source release.
Missing native libraries cause an explicit error; there is no substitute algorithm.

Kernel: `Exact_predicates_inexact_constructions_kernel`. Exact predicate fallback
uses Boost.Multiprecision with GMP/MPFR/CORE disabled. The reference triangulation,
edge traversal/removal, and optimal DP are unchanged. This removes the old Python
ear clipping, longest-shared-edge rule, and bounded diagonal recursion. Wrapper
normalization, data conversion, and final Shapely validation add application
overhead; identical wall-clock time to another CGAL build is not promised.

Build environment: MinGW-w64 GCC 13.1.0 x64, `-std=c++17 -O2`, CGAL 6.0.1 and
Boost 1.86.0. The supplied DLL statically links GCC/libstdc++ runtimes.

With the CGAL and Boost headers installed:

```powershell
python algorithms/native/build.py --include-dir C:/deps/include
```

If Boost headers are separate, add `--boost-include-dir C:/boost_1_86_0`.
Pin the reference versions for reproducible triangulation and merge order.
Other operating systems require building and adapting the loader's library name.

The exact header packages used for this build are available without an account:

- [CGAL header package](https://conda.anaconda.org/conda-forge/win-64/cgal-cpp-6.0.1-hc4f255e_1.conda), SHA-256 `a1f688c4534805745ecdf5af56693e51cc9f08ca229aa0833b9bcd8d38809319`.
- [Boost headers](https://conda.anaconda.org/conda-forge/win-64/libboost-headers-1.86.0-h57928b3_5.conda), SHA-256 `010d6a8326620357cb644538f6b6f9d3653415b7e043a1dd648bad4f283551e6`.

Each `.conda` is a ZIP containing `pkg-*.tar.zst`; extract that archive, then use
its `Library/include` directory. These packages supply headers, not a Python
runtime dependency. Full upstream source: [CGAL v6.0.1](https://github.com/CGAL/cgal/tree/v6.0.1)
and [Boost 1.86.0](https://www.boost.org/releases/1.86.0/).

CGAL Partition_2 is licensed GPL-3.0-or-later OR LicenseRef-Commercial. Other CGAL
components include LGPL-3.0-or-later code. Upstream notices and both license texts
are supplied here. Boost uses the Boost Software License 1.0 (`LICENSE_1_0.txt`).
See the upstream source notices for the license of each component.
