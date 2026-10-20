"""Development-only synchronization; the deployed viewer has no main-app dependency."""
from pathlib import Path
import shutil

source = Path(__file__).resolve().parents[1]
packaged = source / 'HistoryViewer'
standalone = source.parent / 'HistoryViewer'
# The repository carries a complete portable viewer. The user's existing
# sibling deployment remains independent and is synchronized when present.
seed = packaged if (packaged / 'viewer.py').is_file() else standalone
if not (seed / 'viewer.py').is_file():
    raise FileNotFoundError('The standalone HistoryViewer source is missing')
for name in ('viewer.py', 'start.bat', 'requirements.txt', 'README.md', 'runtime/gui/history_window.py'):
    for deployment in [packaged] + ([standalone] if (standalone / 'viewer.py').is_file() else []):
        destination = deployment / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        if (seed / name).resolve() != destination.resolve():
            shutil.copy2(seed / name, destination)
files = ['gui/__init__.py', 'gui/theme.py', 'gui/path_canvas.py', 'gui/result_panel.py', 'gui/compare_panel.py',
         'gui/export_toolbar.py', 'gui/route_export_dialog.py', 'core/image_export.py',
         'compare/route_metrics.py', 'compare/coverage_metrics.py',
         'core/__init__.py', 'core/base_algorithm.py', 'core/experiment_bundle.py', 'core/path_annotations.py',
         'data/__init__.py', 'data/dataset.py', 'data/kml_handler.py', 'data/coord_transform.py', 'data/waypoint_export.py',
         'config/__init__.py', 'config/default_params.py', 'compare/__init__.py', 'compare/metrics.py',
         'compare/statistics.py', 'compare/report_gen.py']
targets = [packaged] + ([standalone] if (standalone / 'viewer.py').is_file() else [])
for viewer in targets:
    target = viewer / 'runtime'
    for name in files:
        destination = target / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source / name, destination)
    configuration = target / 'config/default_params.py'
    text = configuration.read_text(encoding='utf-8').replace(
        'return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))',
        'return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))')
    configuration.write_text(text, encoding='utf-8')
print('Independent viewer runtime synchronized')
