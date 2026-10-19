"""JPEG-only navigation export shared with the independent offline viewer."""
from pathlib import Path
from matplotlib import rcParams
from matplotlib.backends.backend_qtagg import NavigationToolbar2QT
from PySide6.QtWidgets import QFileDialog
from core.image_export import save_jpeg
from config.default_params import PICTURE_DIR


class JpegNavigationToolbar(NavigationToolbar2QT):
    def save_figure(self, *args):
        path, _ = QFileDialog.getSaveFileName(self, '导出高清 JPEG 图片',
            str(Path(PICTURE_DIR) / 'figure.jpg'), 'JPEG (*.jpg *.jpeg)')
        if path:
            return save_jpeg(self.canvas.figure, path)
