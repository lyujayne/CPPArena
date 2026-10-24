"""Build an allowlisted snapshot of the current source without local user data."""
import argparse
import ast
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import tomllib
import zipfile


def main():
    here = Path(__file__).resolve().parent
    source = here.parent.parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--outdir", type=Path, default=source / "pypi-dist")
    arguments = parser.parse_args()
    output = arguments.outdir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    metadata = tomllib.loads((here / "pyproject.toml").read_text(encoding="utf-8"))
    constants = ast.parse((source / "config/default_params.py").read_text(encoding="utf-8"))
    current = next(ast.literal_eval(node.value) for node in constants.body
                   if isinstance(node, ast.Assign)
                   and any(isinstance(target, ast.Name) and target.id == "APP_VERSION"
                           for target in node.targets))
    if metadata["project"]["version"] != current:
        raise SystemExit("Update packaging/pypi/pyproject.toml to match APP_VERSION")

    with tempfile.TemporaryDirectory(prefix=".pypi-build-", dir=output) as temporary:
        staging = Path(temporary)
        for name in ("pyproject.toml", "setup.py", "README.md"):
            shutil.copy2(here / name, staging / name)
        shutil.copytree(here / "cpp_arena", staging / "cpp_arena",
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        for name in ("LICENSE", "NOTICE"):
            shutil.copy2(source / name, staging / name)
        third_party = staging / "third_party"
        third_party.mkdir()
        for name in ("CGAL-LICENSE.txt", "LICENSE.GPL", "LICENSE.LGPL", "LICENSE_1_0.txt"):
            shutil.copy2(source / "algorithms/native" / name, third_party / name)

        files = set()
        for name in ("algorithms", "compare", "config", "core", "data", "gui"):
            files.update(path for path in (source / name).rglob("*.py")
                         if "__pycache__" not in path.parts)
        for name in ("HistoryViewer/runtime",):
            files.update(path for path in (source / name).rglob("*.py")
                         if "__pycache__" not in path.parts)
        for name in ("main.py", "requirements.txt", "README.md", "CHANGELOG.md",
                     "LICENSE", "NOTICE", "PAPER_ALIGNMENT.md", "UPGRADE_v2.9.md",
                     "PERFORMANCE.md", "FOLLOWUP_FIXES.md", "HistoryViewer/viewer.py",
                     "HistoryViewer/README.md", "HistoryViewer/requirements.txt",
                     "assets/app_icon.png", "assets/app_icon.ico",
                     "data/samples/示例农田.kml", "components/README.md",
                     "algorithms/plugins/README.md", "docs/decomposition_v2.9.png"):
            files.add(source / name)
        for name in ("arena_partition.dll", "partition.cpp", "build.py", "build_info.json",
                     "README.md", "CGAL-LICENSE.txt", "LICENSE.GPL", "LICENSE.LGPL",
                     "LICENSE_1_0.txt"):
            files.add(source / "algorithms/native" / name)
        with zipfile.ZipFile(staging / "cpp_arena/application.zip", "w",
                             compression=zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(files):
                archive.write(path, path.relative_to(source).as_posix())
        (staging / "MANIFEST.in").write_text(
            "include cpp_arena/application.zip\nrecursive-include third_party *\n",
            encoding="utf-8")
        subprocess.run([sys.executable, "-m", "build", "--no-isolation", "--outdir",
                        str(output), str(staging)], check=True, env=os.environ.copy())


if __name__ == "__main__":
    main()
