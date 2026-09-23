# -*- coding: utf-8 -*-
"""CPP Arena —— 无人机覆盖路径规划算法比较平台（程序入口）。

一键启动：双击 start.bat，或在项目根目录执行
    python main.py
"""
import os
import sys

# 保证以项目根目录为工作目录时导入无碍（双击 .bat / 任意 cwd 均可）
_BASE = os.path.dirname(os.path.abspath(__file__))
if _BASE not in sys.path:
    sys.path.insert(0, _BASE)

from PySide6.QtGui import QIcon  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from config.default_params import APP_NAME, APP_VERSION  # noqa: E402
from gui.main_window import MainWindow  # noqa: E402


def main():
    # Windows 任务栏：为进程设置独立 AppUserModelID，
    # 避免任务栏按钮套用 python.exe / 环境的默认图标
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                "CPP.Arena.1.2")
        except Exception:
            pass

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
    app.setOrganizationName("CPP Arena")

    icon_path = os.path.join(_BASE, "assets", "app_icon.png")
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))

    window = MainWindow()
    if os.path.exists(icon_path):
        window.setWindowIcon(QIcon(icon_path))
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
