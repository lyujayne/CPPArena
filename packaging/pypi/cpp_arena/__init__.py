"""Launch the existing desktop application from a writable user directory."""
import argparse
from importlib.metadata import version
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import zipfile


def application_directory():
    """Keep the original app's source-relative data paths out of site-packages."""
    release = version("cpp-arena")
    root = Path(os.environ["CPP_ARENA_HOME"]) if "CPP_ARENA_HOME" in os.environ else (
        Path(os.environ["LOCALAPPDATA"]) / "CPP Arena")
    destination = root.resolve() / release
    if not destination.exists():
        root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=".install-", dir=root) as temporary:
            staged = Path(temporary) / release
            with zipfile.ZipFile(Path(__file__).with_name("application.zip")) as archive:
                archive.extractall(staged)
            # Publish the whole application together, so an interrupted extraction
            # cannot leave an apparently installed but incomplete application.
            staged.rename(destination)
    return destination


def _launch(history=False):
    parser = argparse.ArgumentParser(description=(
        "CPP Arena offline experiment viewer" if history else
        "CPP Arena UAV coverage path planning desktop application"))
    parser.add_argument("--version", action="version", version=version("cpp-arena"))
    if history:
        parser.add_argument("experiment", nargs="?", help="Experiment folder or archive")
    arguments = parser.parse_args()
    if sys.platform != "win32" or struct.calcsize("P") != 8:
        parser.error("CPP Arena currently requires 64-bit Python on Windows x64")
    directory = application_directory()
    entry = directory / ("HistoryViewer/viewer.py" if history else "main.py")
    command = [sys.executable, str(entry)]
    if history and arguments.experiment:
        command.append(str(Path(arguments.experiment).resolve()))
    return subprocess.call(command, cwd=directory)


def main():
    return _launch()


def history_main():
    return _launch(history=True)
