"""Build the thin CGAL C ABI with MinGW-w64 (the application itself stays Python)."""
import argparse
from pathlib import Path
import subprocess


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--include-dir', type=Path, required=True,
                        help='Directory containing CGAL/ and boost/ headers')
    parser.add_argument('--boost-include-dir', type=Path)
    parser.add_argument('--compiler', default='g++')
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    command = [args.compiler, '-std=c++17', '-O2', '-DNDEBUG', '-DCGAL_NO_GMP=1',
               '-DCGAL_NO_MPFR=1', '-DCGAL_NO_CORE=1', '-shared',
               '-static-libgcc', '-static-libstdc++', '-I', str(args.include_dir.resolve())]
    if args.boost_include_dir:
        command += ['-I', str(args.boost_include_dir.resolve())]
    subprocess.run(command + [str(root/'partition.cpp'), '-o', str(root/'arena_partition.dll')],
                   check=True)
