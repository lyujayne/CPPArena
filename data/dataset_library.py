"""Durable imported datasets and background assets, independent of source KML paths."""
import hashlib
import json
from pathlib import Path
import shutil
import tempfile

from config.default_params import DATASET_LIBRARY_DIR
from data.dataset import Dataset


class DatasetLibrary:
    def __init__(self, directory=None):
        self.directory = Path(directory or DATASET_LIBRARY_DIR)
        self.path = self.directory / 'library.json'

    def load(self):
        if not self.path.exists():
            return []
        record = json.loads(self.path.read_text(encoding='utf-8'))
        if not isinstance(record, dict) or record.get('schema') != 'cpp-arena-datasets':
            raise ValueError('数据集库格式无效')
        return [Dataset.from_dict(item) for item in record['datasets']]

    def save(self, datasets):
        self.directory.mkdir(parents=True, exist_ok=True)
        assets = self.directory / 'assets'
        assets.mkdir(exist_ok=True)
        for ds in datasets:
            if ds.bg_image_path and Path(ds.bg_image_path).is_file():
                source = Path(ds.bg_image_path)
                stem = hashlib.sha256(ds.id.encode()).hexdigest()[:20]
                destination = assets / (stem + source.suffix.lower())
                if source.resolve() != destination.resolve():
                    shutil.copy2(source, destination)
                ds.bg_image_path = str(destination.resolve())
        payload = {'schema': 'cpp-arena-datasets', 'version': 1, 'datasets': [ds.to_dict() for ds in datasets]}
        with tempfile.NamedTemporaryFile(dir=self.directory, suffix='.tmp', delete=False) as stream:
            temporary = Path(stream.name)
        try:
            temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
            temporary.replace(self.path)
        finally:
            temporary.unlink(missing_ok=True)
