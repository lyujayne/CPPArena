"""Keep GUI tests from changing the user's persistent dataset library."""
import pytest


@pytest.fixture(autouse=True)
def isolate_dataset_library(tmp_path, monkeypatch):
    import data.dataset_library
    monkeypatch.setattr(data.dataset_library, 'DATASET_LIBRARY_DIR', str(tmp_path / 'datasets'))
