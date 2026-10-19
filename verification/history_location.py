"""Locate the portable viewer in a fresh checkout or an older local deployment."""
from pathlib import Path


def history_viewer_directory():
    source = Path(__file__).resolve().parents[1]
    packaged = source / 'HistoryViewer'
    return packaged if (packaged / 'viewer.py').is_file() else source.parent / 'HistoryViewer'
