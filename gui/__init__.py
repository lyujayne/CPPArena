# -*- coding: utf-8 -*-
"""GUI 包：matplotlib 中文字体初始化。"""
import matplotlib

matplotlib.use("QtAgg")
import matplotlib.pyplot as plt  # noqa: E402

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei",
                                   "Arial Unicode MS", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False
