# -*- mode: python ; coding: utf-8 -*-
"""CPP Arena PyInstaller 打包配置（单文件 onefile，Windows）。

构建：
    E:\\anaconda\\python.exe -m PyInstaller --clean --noconfirm CPPArena.spec
产物：
    dist\\CPPArena.exe
"""
from PyInstaller.utils.hooks import collect_all

# pyproj 需要 proj.db 等投影数据；shapely 依赖 GEOS DLL。
# 显式全量收集，避免不同 PyInstaller 版本 hook 差异导致运行时缺数据。
datas = []
binaries = []
hiddenimports = []
for _pkg in ("pyproj", "shapely"):
    _d, _b, _h = collect_all(_pkg)
    datas += _d
    binaries += _b
    hiddenimports += _h

# setuptools 80.x 中 pkg_resources 依赖 vendored jaraco；
# 运行时钩子 pyi_rth_pkgres 需要这些模块，排除 setuptools 会导致
# 启动时报 ModuleNotFoundError: No module named 'jaraco.text'。
hiddenimports += [
    "pkg_resources",
    "jaraco.text",
    "jaraco.context",
    "jaraco.functools",
    "setuptools._vendor.jaraco.text",
    "setuptools._vendor.jaraco.context",
    "setuptools._vendor.jaraco.functools",
]

# 应用资源与示例数据
datas += [
    ("assets", "assets"),
    ("data/samples", "data/samples"),
]

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "tkinter", "PyQt5", "PyQt6", "PySide2", "pytest", "IPython",
        "notebook", "jupyter", "sphinx",
        # 本项目不使用的重型环境包（Anaconda 自带，排除以避免钩子崩溃/体积膨胀）
        "torch", "torchvision", "torchaudio",
        "sklearn", "scipy", "sympy", "numba", "llvmlite",
        # pandas/可视化库的可选依赖，本程序不使用；避免导入额外JIT和云存储工具。
        "datashader", "holoviews", "hvplot", "panel", "bokeh", "plotly",
        "cv2", "skimage", "dask", "distributed", "xarray",
        "fsspec", "s3fs", "botocore", "boto3", "tables", "h5py",
        "pytest", "pip",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="CPPArena-v2.1",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    icon="assets/app_icon.ico",
    version="version_info.txt",
)
