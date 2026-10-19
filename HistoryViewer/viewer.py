"""Independent offline viewer. This folder can be copied without CPP Arena."""
import argparse
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
parser = argparse.ArgumentParser(description='CPP Arena offline experiment viewer')
parser.add_argument('experiment', nargs='?', help='Optional .cppx/.zip/.json experiment')
parser.add_argument('--check', metavar='OUTPUT_JSON', help='Verify startup and exit without an interactive event loop')
arguments = parser.parse_args()
if arguments.check:
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(ROOT / 'runtime'))

from PySide6.QtWidgets import QApplication
from gui.history_window import HistoryWindow
from gui.theme import apply_theme


def main():
    app = QApplication([sys.argv[0]])
    app.setApplicationName('CPP Arena History Viewer')
    apply_theme(app)
    window = HistoryWindow()
    if arguments.experiment:
        window.library.setCurrentItem(window._add_path(arguments.experiment))
        window.open_path(arguments.experiment)
    window.show()
    if arguments.check:
        app.processEvents()
        assert not any(name == 'algorithms' or name.startswith('algorithms.') for name in sys.modules)
        output = {'window': window.windowTitle(), 'standalone': True,
                  'algorithm_modules_loaded': False, 'experiment_loaded': window._record is not None,
                  'runs_in_selector': window.run_combo.count()}
        destination = Path(arguments.check)
        destination.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding='utf-8')
        window.grab().save(str(destination.with_suffix('.png')))
        window.close()
        return 0
    return app.exec()


if __name__ == '__main__':
    sys.exit(main())
