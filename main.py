# -*- coding: utf-8 -*-
"""CPPBench —— 无人机覆盖路径规划算法比较平台（程序入口）。

一键启动：双击 start.bat，或在项目根目录执行
    python main.py
"""
import os
import sys

# 保证以项目根目录为工作目录时导入无碍（双击 .bat / 任意 cwd 均可）
_BASE = os.path.dirname(os.path.abspath(__file__))
if _BASE not in sys.path:
    sys.path.insert(0, _BASE)

from PySide6.QtWidgets import QApplication  # noqa: E402

from config.default_params import APP_NAME, APP_VERSION  # noqa: E402
from gui.main_window import MainWindow  # noqa: E402


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
    app.setOrganizationName("CPPBench")

    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
