# Debugging local OCCT through FreeCAD

This workspace uses FreeCAD as the application driver and the sibling OCCT checkout as the editable geometry kernel. It is configured for macOS Apple Silicon, Pixi, Clang, and CodeLLDB.

## Architecture

| Layer | Location | Role |
| --- | --- | --- |
| FreeCAD | `FreeCAD/` | Application, Python API, GUI, and Part integration |
| Local OCCT | `occt/` | Editable OCCT 7.8.1 source and Debug libraries |
| Toolchain | `FreeCAD/.pixi/envs/default/` | Clang 18, CMake, Ninja, Qt, Python, and dependencies |
| Integration | `scripts/`, `.vscode/`, `.clangd` | Build, runtime library selection, indexing, and debugging |

The representative fillet path starts in `FreeCAD/src/Mod/Part/App/FeatureFillet.cpp`, enters `BRepFilletAPI_MakeFillet`, and then reaches the `ChFi3d` implementation in OCCT.

## Configure and build

```bash
scripts/configure-occt.sh
scripts/rebuild-occ.sh
```

The configure step preserves the existing Debug build while enabling `occt/build/debug/compile_commands.json`. The rebuild step installs updated libraries into `occt/install/debug/lib`.

FreeCAD is configured with its ignored local preset and then built through Pixi:

```bash
cd FreeCAD
pixi run --frozen -- cmake --preset local-occt-macos-debug
pixi run --frozen -- cmake --build build/debug -j 8
```

## VS Code indexing and navigation

Open the outer directory with `code .`. The outer `.vscode/settings.json` and `.clangd` are the only workspace configuration.

After changing CMake configuration, run **clangd: Restart language server**. In the clangd output, each opened C++ file should report a compile command from one of these databases:

- `FreeCAD/build/debug/compile_commands.json`
- `occt/build/debug/compile_commands.json`

Go to Definition, Go to Declaration, and Go to Implementations should then work for FreeCAD symbols, OCCT symbols, and FreeCAD calls into OCCT. If navigation returns immediately with no location, run `scripts/workspace-doctor.sh` and check that clangd is not using a fallback command.

## CodeLLDB workflow

Useful launch configurations include:

- `FreeCAD GUI · local OCCT · build first`
- `FreeCADCmd · current Python file · build first`
- `FreeCADCmd · debug_target.py · build first`
- `FreeCADCmd · debug_target.py · skip build`
- `Attach to running FreeCAD`

The build-first configurations incrementally build and install OCCT before incrementally building FreeCAD. Run the explicit `Workspace: configure debug` task after changing CMake options or recreating a build directory. All launch configurations import the OCCT and Qt formatters and launch with the local OCCT library directory first.

Suggested fillet breakpoints:

- `FreeCAD/src/Mod/Part/App/FeatureFillet.cpp` at `Part::Fillet::execute`
- `occt/src/BRepFilletAPI/BRepFilletAPI_MakeFillet.cxx` at `Add` or `Build`
- `occt/src/ChFi3d/ChFi3d_Builder_C1.cxx` at `PerformIntersectionAtEnd`

An OCCT breakpoint may remain pending until `libTKFillet` is loaded. It should resolve after the Part module performs its first fillet operation.

For organizing breakpoints into reusable collections and visualizing geometry objects while stepping, see `docs/vscode-debug-breakpoints.md`.

## Reproducible smoke scenario

```bash
scripts/fc-cmd.sh scripts/debug_target.py
```

The baseline behavior is:

- a 2 mm fillet on a 10 mm box succeeds and produces a valid shape;
- an intentionally excessive 20 mm fillet fails with an OCCT `StdFail_NotDone` error.

Use the same script under CodeLLDB to compare source edits without changing the test geometry.

## Runtime library verification

The FreeCAD Part module links OCCT libraries through `@rpath`. The local preset makes its build RPATH start with `occt/install/debug/lib`, ahead of Pixi. Supported launch scripts additionally set:

```text
DYLD_LIBRARY_PATH=<workspace>/occt/install/debug/lib
```

Verify the effective runtime path with:

```bash
scripts/workspace-doctor.sh --runtime
```

The check passes only when the process loads `libTKFillet` from this workspace's `occt/install/debug/lib`.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| Definitions/declarations do not open | Confirm both CDB files exist, restart clangd, and inspect the clangd output for fallback commands |
| OCCT headers are all red | Run `scripts/configure-occt.sh`; do not add broad fallback include paths |
| Breakpoint stays pending | Build/install OCCT, trigger the Part module, then inspect the loaded `libTKFillet` path |
| Source edit has no effect | Run the build-first launch or `scripts/rebuild-occ.sh`; compare source/object/library timestamps |
| LLDB expression fails | Stop in a frame where the variable is in scope; an expression error is not automatically a symbol-loading failure |
| Bare `FreeCADCmd` uses the wrong OCCT | Re-run the local FreeCAD preset and build, then use `workspace-doctor.sh --runtime`; workspace launch profiles also enforce `DYLD_LIBRARY_PATH` |
| OCCT breakpoints never bind (stay pending after `libTKFillet` loads) even though the build is Debug and the local library is loaded | OCCT's `occt/adm/cmake/occt_defs_flags.cmake` unconditionally adds `-Wl,-s` to `CMAKE_SHARED_LINKER_FLAGS` for Clang ("Optimize size of binaries"), which strips the macOS debug map (OSO stabs) from every shared library — DWARF stays in the `.o` files but LLDB can no longer map addresses to source. Guard that line with `if (NOT CMAKE_BUILD_TYPE STREQUAL "Debug")`, then `scripts/configure-occt.sh && scripts/rebuild-occ.sh`. Verify with `nm -pa occt/install/debug/lib/libTKFillet.7.8.1.dylib \| grep -c ' OSO '` (0 = stripped/broken, non-zero = debug map present). This lives in the vendored OCCT checkout, so a reset/checkout/pull of `occt/` can revert it — re-check the line if breakpoints regress. |
