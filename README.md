# FreeCAD + OCCT local development workspace

This outer directory is the development orchestration layer for two independent source repositories:

```text
freecad/          workspace configuration, scripts, and documentation
├── FreeCAD/      FreeCAD source repository and Pixi/Ninja debug build   (not in this repo)
├── occt/         OCCT source repository, Makefiles debug build, install (not in this repo)
├── scripts/      configure, build, run, debug, and diagnostic entry points
├── .vscode/      the single VS Code configuration for both repositories
├── templates/    files that live inside the ignored source trees (e.g. the local CMake preset)
├── patches/      local source edits to re-apply after cloning the source trees
└── docs/         workspace-specific documentation
```

The outer Git repository intentionally ignores `FreeCAD/` and `occt/`; each keeps its own branch, diff, and remote history. It also ignores `.omx/` and `myFold/`, which contain local agent state and user models.

This means **a fresh clone of this repository does not contain the FreeCAD or OCCT source** — only the configuration layer. Follow [Bootstrap from a fresh clone](#bootstrap-from-a-fresh-clone) to materialize a buildable, debuggable environment.

## Bootstrap from a fresh clone

Run on macOS Apple Silicon. Prerequisites: `git`, [`pixi`](https://pixi.sh) (provides the locked Clang/CMake/Qt toolchain), and the Xcode Command Line Tools. The directory layout matters: OCCT must be cloned into `occt/` and FreeCAD into `FreeCAD/`, as siblings, because the CMake preset references the OCCT install via `${sourceParentDir}/occt/install/debug`.

```bash
# 1. Clone this kit; the outer directory name becomes the workspace root.
git clone https://github.com/liyongzheng666/freecad-occt-debug-kit.git freecad
cd freecad

# 2. OCCT 7.8.1 source, then re-apply the local debug/build edits.
git clone --branch V7_8_1 https://github.com/Open-Cascade-SAS/OCCT.git occt
git -C occt apply ../patches/occt-debug-build.patch

# 3. FreeCAD source baseline. This is upstream only — the local FreeCAD
#    integration/agent changes are NOT part of this kit and stay on your fork.
git clone --branch weekly-2026.05.06 https://github.com/FreeCAD/FreeCAD.git FreeCAD

# 4. Restore the local-only CMake preset (FreeCAD's own .gitignore drops it).
cp templates/CMakeUserPresets.json FreeCAD/CMakeUserPresets.json

# 5. Materialize the locked Pixi toolchain (Clang 18, CMake, Ninja, Qt, ...).
cd FreeCAD && pixi install --frozen && cd ..

# 6. Build OCCT (debug + install), then FreeCAD against that local OCCT.
scripts/configure-occt.sh
scripts/rebuild-occ.sh
cd FreeCAD
pixi run --frozen -- cmake --preset local-occt-macos-debug
pixi run --frozen -- cmake --build build/debug -j 8
cd ..

# 7. Verify the toolchain, indexing, and runtime library resolution.
scripts/workspace-doctor.sh --runtime
```

Notes:

- `patches/occt-debug-build.patch` carries two edits against `V7_8_1`: keeping the debug map in Debug builds so LLDB can bind breakpoints (otherwise `-Wl,-s` strips it), and a FreeType `tags` cast that Clang 18 requires. A `reset`/`checkout`/`pull` of `occt/` reverts the first edit — re-apply if breakpoints regress. See the troubleshooting table in [docs/occt-debugging.md](docs/occt-debugging.md).
- The FreeCAD `weekly-2026.05.06` tag is the nearest published anchor; the environment is reproduced from it, not the in-progress local branch.
- After the build, open the workspace with `code .` and continue from [Start here](#start-here).

## Start here

Open this outer directory, not either source repository by itself:

```bash
code .
scripts/workspace-doctor.sh
```

Install the extensions recommended by `.vscode/extensions.json`. Clangd then uses the path-scoped `.clangd` configuration:

- `FreeCAD/**` → `FreeCAD/build/debug/compile_commands.json`
- `occt/**` → `occt/build/debug/compile_commands.json`

## Common commands

```bash
scripts/configure-occt.sh                    # configure OCCT and generate its CDB
scripts/rebuild-occ.sh                       # incrementally build + install OCCT
scripts/fc-cmd.sh scripts/debug_target.py    # run the geometry smoke scenario
scripts/fc-lldb.sh scripts/debug_target.py   # debug the scenario in command-line LLDB
scripts/fc-gui.sh                            # run the FreeCAD GUI with local OCCT
scripts/workspace-doctor.sh --runtime        # include dynamic-library resolution check
```

VS Code exposes equivalent configure/build tasks. The normal CodeLLDB launch configurations run `Debug: sync local toolchain` before starting; use the explicitly named `skip build` configuration only when inspecting an already-built process.

## Build boundaries

- FreeCAD dependencies and compilers come from `FreeCAD/.pixi/envs/default`.
- FreeCAD uses the local-only `FreeCAD/CMakeUserPresets.json` preset named `local-occt-macos-debug`.
- OCCT builds in `occt/build/debug` and installs into `occt/install/debug`.
- The local preset puts `occt/install/debug/lib` before Pixi in the build RPATH; run/debug entry points also set `DYLD_LIBRARY_PATH` as a safeguard.

Generated directories are intentionally excluded from ordinary VS Code search and file watching. Do not delete `.pixi`, build, or install directories as routine cleanup.

## Documentation

- [docs/vscode-build-and-pixi.md](docs/vscode-build-and-pixi.md) — how the VS Code build/link pipeline and Pixi fit together (beginner-friendly intro to Pixi and CMake).
- [docs/occt-debugging.md](docs/occt-debugging.md) — the debugging workflow and troubleshooting guide.
- [docs/vscode-debug-breakpoints.md](docs/vscode-debug-breakpoints.md) — breakpoint setup and tips.
