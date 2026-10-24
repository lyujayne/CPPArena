"""Use CGAL's reference HM and Greene algorithms through a small native C ABI."""
import ctypes
from functools import lru_cache
from pathlib import Path

import numpy as np
from shapely.geometry import Polygon

from config.default_params import RESOURCE_DIR
from core.execution_control import checkpoint


@lru_cache(maxsize=1)
def _library():
    path = Path(RESOURCE_DIR) / 'algorithms/native/arena_partition.dll'
    if not path.is_file():
        raise RuntimeError('缺少CGAL原生分割库，请按 algorithms/native/README.md 构建；不回退到近似算法')
    lib = ctypes.CDLL(str(path))
    lib.arena_cgal_version.restype = ctypes.c_char_p
    lib.arena_partition.argtypes = [
        ctypes.POINTER(ctypes.c_double), ctypes.c_int, ctypes.c_int,
        ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int),
        ctypes.POINTER(ctypes.c_char), ctypes.c_int]
    lib.arena_partition.restype = ctypes.c_int
    return lib


def convex_partition(vertices, optimal=False):
    points = np.ascontiguousarray(vertices, dtype=np.float64)
    n = len(points)
    indices = (ctypes.c_int * (3*n))()
    offsets = (ctypes.c_int * (n+1))()
    error = ctypes.create_string_buffer(2048)
    name = 'Greene 最优凸分解' if optimal else 'Hertel–Mehlhorn 凸分解'
    checkpoint('CGAL ' + name, force=True)
    lib = _library()
    count = lib.arena_partition(points.ctypes.data_as(ctypes.POINTER(ctypes.c_double)),
                                n, int(optimal), indices, offsets, error, len(error))
    checkpoint()
    if count < 0:
        raise RuntimeError('CGAL分割失败：' + error.value.decode('utf-8', errors='replace'))
    parts = [Polygon(points[[indices[j] for j in range(offsets[i], offsets[i+1])]])
             for i in range(count)]
    return parts, {'backend': 'CGAL', 'backend_version': lib.arena_cgal_version().decode(),
                   'reference_function': ('optimal_convex_partition_2' if optimal
                                          else 'approx_convex_partition_2')}
