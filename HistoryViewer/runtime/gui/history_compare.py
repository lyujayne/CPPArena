"""Bind prepared offline metrics without recalculating every saved route."""
from gui.compare_panel import ComparePanel
from config.default_params import ALGORITHM_META


class HistoryComparePanel(ComparePanel):
    def set_record(self, record, datasets):
        self._results = record['results']
        self._datasets = {dataset.name: dataset for dataset in datasets}
        self._camera = dict(record['camera'])
        self._baseline = record.get('comparison', {}).get(
            'baseline', next(iter(next(iter(self._results.values()), {})), None))
        self._algos_meta = ALGORITHM_META
        self._params_by_algo = {}
        self._seeds = record.get('seeds', [])
        self._project_name = record.get('experiment_name') or record.get('project', '历史实验')
        self.ds_combo.blockSignals(True)
        self.ds_combo.clear()
        for name in self._results:
            self.ds_combo.addItem(name, name)
        self.ds_combo.blockSignals(False)
        self._refresh_waypoint_algos()
        self.rebuild()
        self._set_enabled(self.ds_combo.count() > 0)
