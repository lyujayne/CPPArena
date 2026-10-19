"""Shared desktop styling for planning and offline history windows."""
def apply_theme(app):
    from PySide6.QtGui import QFont, QFontDatabase
    from pathlib import Path
    import os
    import matplotlib
    matplotlib.rcParams['font.sans-serif'] = ['Microsoft YaHei', 'SimHei', 'DejaVu Sans']
    matplotlib.rcParams['axes.unicode_minus'] = False
    from config.default_params import PICTURE_DIR
    matplotlib.rcParams['savefig.directory'] = PICTURE_DIR
    if 'Microsoft YaHei' not in QFontDatabase.families():
        font = Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts' / 'msyh.ttc'
        if font.is_file():
            QFontDatabase.addApplicationFont(str(font))
    app.setStyle('Fusion')
    app.setFont(QFont('Microsoft YaHei', 9))
    app.setStyleSheet('''
        QMainWindow, QDialog { background:#f1f5f9; }
        QWidget { color:#22354b; }
        QGroupBox { background:#ffffff; border:1px solid #d8e2eb;
                    border-radius:8px; margin-top:14px; padding:8px; font-weight:600; }
        QGroupBox::title { subcontrol-origin:margin; left:12px; padding:0 5px; color:#126b72; }
        QPushButton { background:#fff; border:1px solid #cbd5e1; border-radius:5px; padding:6px 9px; }
        QPushButton:hover { background:#e6f3f2; border-color:#48a39b; }
        QPushButton:disabled { color:#94a3b8; background:#e9eef4; }
        QPushButton#PrimaryButton { background:#087f8c; color:white; border-color:#087f8c; font-weight:600; }
        QTabWidget::pane { border:1px solid #d8e2eb; border-radius:6px; background:white; }
        QTabBar::tab { background:#e6edf4; padding:8px 12px; margin-right:2px; }
        QTabBar::tab:selected { background:#fff; color:#087f8c; }
        QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QPlainTextEdit, QTextBrowser,
        QListWidget, QTableWidget { background:white; border:1px solid #d4dfe9; border-radius:4px; padding:4px; }
        QHeaderView::section { background:#eaf1f5; padding:6px; border:0; border-bottom:1px solid #d4dfe9; }
        QProgressBar { border:1px solid #d4dfe9; border-radius:4px; text-align:center; min-height:16px; }
        QProgressBar::chunk { background:#31b3a1; }
        QToolBar { background:#fff; border-bottom:1px solid #d8e2eb; spacing:8px; padding:4px; }
        QSplitter::handle { background:#e2e8f0; width:5px; }
        QStatusBar { background:#e8f0f5; }
    ''')
