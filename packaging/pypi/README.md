# CPP Arena

CPP Arena is a desktop comparison platform for UAV coverage path planning.
It provides polygon import, nine decomposition methods, seven route planners,
experiment comparisons, waypoint export, and an offline experiment viewer.

## Install and launch

Requires **Windows x64 and 64-bit Python 3.10 or newer**. The bundled CGAL
partition backend is a Windows x64 native library.

```powershell
python -m pip install cpp-arena
cpp-arena
```

You can also launch the application with `python -m cpp_arena`.
To open the independent offline experiment viewer:

```powershell
cpp-arena-history
cpp-arena-history "D:\experiments\my-experiment"
```

On first launch, the packaged application is extracted to
`%LOCALAPPDATA%\CPP Arena\2.9`. Settings, datasets, projects, pictures, and
experiment records are saved inside that writable directory. Existing local
experiments are not included in the distribution; import them with the viewer.
Set `CPP_ARENA_HOME` before launch to use a different parent directory. Each
release keeps its own application and data directory; uninstalling the Python
package leaves those files in place.

## Scope

The application compares decomposition and planning implementations with
explicit implementation budgets and assumptions. Algorithm alignment notes are
included in the packaged `PAPER_ALIGNMENT.md` and `UPGRADE_v2.9.md`. Results
are research outputs; exported waypoints do not include camera trigger commands.

The source distribution contains the application Python sources in
`cpp_arena/application.zip`, plus the native wrapper source, build instructions,
and third-party notices. Extract the ZIP to inspect or run the original source.
CGAL and Boost header download URLs and hashes are in
`algorithms/native/README.md` inside that archive.

## License and source

CPP Arena is distributed under **GPL-3.0-or-later**. The bundled CGAL and Boost
components retain their own notices and license texts. See `LICENSE`, `NOTICE`,
and `third_party` in the distribution.

[Source repository](https://github.com/lyujayne/CPPArena)
