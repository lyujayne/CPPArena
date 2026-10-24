"""Read offline experiments outside the Qt event loop."""
from pathlib import Path
from zipfile import BadZipFile

from PySide6.QtCore import QObject, QRunnable, Signal

from compare.coverage_metrics import coverage_details
from compare.metrics import successful_run
from compare.route_metrics import attach_route_metrics
from core.experiment_bundle import import_experiment, load_experiment_directory
from data.dataset import Dataset


def prepare_record(record):
    datasets = [Dataset.from_dict(data) for data in record['datasets']]
    for dataset in datasets:
        for runs in record['results'].get(dataset.name, {}).values():
            for run in runs:
                if not successful_run(run) or not run.get('waypoints'):
                    continue
                required = {'executed_distance_m', 'unique_route_length_m', 'redundancy_pct'}
                if dataset.regions:
                    required.add('outside_distance_m')
                if run.get('internal_paths'):
                    required.update(('internal_distance_m', 'subregion_transfer_m'))
                sequence = run.get('subregion_sequence') or []
                if sequence and all(item.get('entry') is not None and item.get('exit') is not None
                                    for item in sequence):
                    required.add('subregion_transfer_m')
                if sequence and all('scan_segments' in item for item in sequence):
                    required.update(('scan_distance_m', 'non_scan_distance_m'))
                metadata = run.get('metadata') or {}
                if metadata.get('turn_metrics', {}).get('sweep_reversals') is not None:
                    required.add('sweep_reversals')
                if not required.issubset(metadata.get('route_metrics') or {}):
                    attach_route_metrics(run, dataset)
                coverage = coverage_details(run, dataset, record['camera'])
                if coverage:
                    run['metadata']['coverage'] = coverage
    return datasets


def record_key(directory):
    index = Path(directory) / 'experiment.json'
    stat = index.stat()
    return str(index.parent.resolve()), stat.st_mtime_ns, stat.st_size


class LoadSignals(QObject):
    finished = Signal(int, object, object, object)


def load_record(path, library):
    stored, library = Path(path).resolve(), Path(library).resolve()
    if not (stored.is_dir() and stored.parent == library):
        stored = import_experiment(stored, library)
    record = load_experiment_directory(stored)
    datasets = prepare_record(record)
    return stored, (record, datasets, record_key(stored))


class LoadExperiment(QRunnable):
    def __init__(self, request, path, library):
        super().__init__()
        self.request, self.path, self.library = request, Path(path), Path(library)
        self.signals = LoadSignals()

    def run(self):
        try:
            # A record already in this library needs a single read, not an import
            # validation followed by another full JSON decode.
            stored, payload = load_record(self.path, self.library)
        except (OSError, ValueError, TypeError, KeyError, RuntimeError, BadZipFile) as exc:
            self.signals.finished.emit(self.request, None, None, exc)
        else:
            self.signals.finished.emit(self.request, stored, payload, None)
