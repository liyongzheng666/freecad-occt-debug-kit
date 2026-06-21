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

A clone of this kit contains only the configuration layer. One command turns it into a buildable, debuggable environment:

```bash
git clone https://github.com/liyongzheng666/freecad-occt-debug-kit.git freecad
cd freecad
scripts/bootstrap.sh            # clone pinned sources, patch, build OCCT + FreeCAD, verify
```

Prerequisites (macOS Apple Silicon): `git`, [`pixi`](https://pixi.sh) (provides the locked Clang/CMake/Qt toolchain), and the Xcode Command Line Tools. `scripts/bootstrap.sh` is **idempotent** — re-running skips any step already completed, so it also serves as a repair entry point. Pass a job count to override the default `-j 8`, e.g. `scripts/bootstrap.sh 12`.

The directory layout matters: OCCT lives in `occt/` and FreeCAD in `FreeCAD/`, as siblings, because the CMake preset references the OCCT install via `${sourceParentDir}/occt/install/debug`.

### What the script does, equivalently by hand

```bash
# 1. OCCT 7.8.1 source, then re-apply the local debug/build edits.
git clone --depth 1 --branch V7_8_1 https://github.com/Open-Cascade-SAS/OCCT.git occt
git -C occt apply ../patches/occt-debug-build.patch

# 2. FreeCAD source pinned to the exact commit this kit was captured against.
git clone --filter=blob:none https://github.com/FreeCAD/FreeCAD.git FreeCAD
git -C FreeCAD checkout 2b7e9a6896bc9b5dc4555c2f6faa9adc0a7caf47

# 3. Restore the files that belong inside FreeCAD/ but are not in FreeCAD's git:
#    the local-only CMake preset (dropped by FreeCAD's own .gitignore) and the
#    toponaming reference note.
cp templates/CMakeUserPresets.json FreeCAD/CMakeUserPresets.json
cp templates/TOPONAMING.md         FreeCAD/src/Mod/Part/App/TOPONAMING.md

# 4. Materialize the locked Pixi toolchain (Clang 18, CMake, Ninja, Qt, ...).
( cd FreeCAD && pixi install --frozen )

# 5. Build OCCT (debug + install), then FreeCAD against that local OCCT.
scripts/configure-occt.sh
scripts/rebuild-occ.sh
( cd FreeCAD
  pixi run --frozen -- cmake --preset local-occt-macos-debug
  pixi run --frozen -- cmake --build build/debug -j 8 )

# 6. Verify the toolchain, indexing, and runtime library resolution.
scripts/workspace-doctor.sh --runtime
```

Notes:

- `patches/occt-debug-build.patch` carries two edits against `V7_8_1`: keeping the debug map in Debug builds so LLDB can bind breakpoints (otherwise `-Wl,-s` strips it), and a FreeType `tags` cast that Clang 18 requires. A `reset`/`checkout`/`pull` of `occt/` reverts the first edit — re-apply if breakpoints regress. See the troubleshooting table in [docs/occt-debugging.md](docs/occt-debugging.md).
- FreeCAD is pinned to commit `2b7e9a6896b` (an ancestor of `FreeCAD/main`), so the source reproduces exactly. The kit does not carry any FreeCAD source changes — that commit is vanilla upstream; the only restored file is the `TOPONAMING.md` reference note.
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
scripts/bootstrap.sh                         # one-click: clone sources + build everything (see below)
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

- [docs/occ-fillet-debug-agent-architecture.md](docs/occ-fillet-debug-agent-architecture.md) - architecture and implementation plan for the incremental FreeCAD/OCCT fillet-debugging agent and geometry viewer.
- [docs/lldb-dynamic-geometry-capture.md](docs/lldb-dynamic-geometry-capture.md) - debugger-first geometry capture commands that emit points, curves, topology, and BREP assets without rebuilding for each observation.

- [docs/vscode-build-and-pixi.md](docs/vscode-build-and-pixi.md) — how the VS Code build/link pipeline and Pixi fit together (beginner-friendly intro to Pixi and CMake).
- [docs/occt-debugging.md](docs/occt-debugging.md) — the debugging workflow and troubleshooting guide.
- [docs/vscode-debug-breakpoints.md](docs/vscode-debug-breakpoints.md) — breakpoint setup and tips.
