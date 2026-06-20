# FreeCAD + OCCT local development workspace

This outer directory is the development orchestration layer for two independent source repositories:

```text
freecad/          workspace configuration, scripts, and documentation
├── FreeCAD/      FreeCAD source repository and Pixi/Ninja debug build
├── occt/         OCCT source repository, Makefiles debug build, and local install
├── scripts/      configure, build, run, debug, and diagnostic entry points
├── .vscode/      the single VS Code configuration for both repositories
└── docs/         workspace-specific documentation
```

The outer Git repository intentionally ignores `FreeCAD/` and `occt/`; each keeps its own branch, diff, and remote history. It also ignores `.omx/` and `myFold/`, which contain local agent state and user models.

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
