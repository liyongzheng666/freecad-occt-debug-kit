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
| LLDB `expr` / `occ_emit_shape`: `no matching function for call to 'Write'` (candidate needs 3 or 6 args, 2 given) | OCCT 7.8 removed the 2-arg `BRepTools::Write(shape, file)`; the file overload now takes a trailing `Message_ProgressRange`, and **lldb expression-eval does not apply C++ default arguments** — so pass it explicitly: `BRepTools::Write(shape, "path", Message_ProgressRange())`. Fixed in `scripts/occ_capture.py` (`occ_emit_shape` / `occ_emit_surface`). General rule: in lldb expressions supply *every* argument of an overload; defaults are not filled in for you. |
| Debug Visualizer shows a char "cloud"/graph of nodes (`[raw]`, `*$1`, individual characters) instead of the chart | Per Debug Visualizer's source, **whenever the evaluate response has `variablesReference != 0` it graphs the variable's children and ignores the JSON**; only a value with *no* children reaches its JSON parser. Everything string-shaped is expandable and so gets graphed: a `char[N]` array (the `/py` Python evaluator produces one — CodeLLDB types a Python `str` as `char[N]`) → N character nodes; a `const char*` → one deref child `*$1`; even a 0-children synthetic provider still adds a `[raw]` node. The fix (in `.vscode/settings.json` `expressionTemplate` + `scripts/lldb_occt_formatters.py`): return a pointer to an **incomplete** struct — `/nat (...; (struct __dv_payload*)_b;)`. An incomplete type cannot be dereferenced, so it genuinely has no children → `variablesReference == 0`, while `dv_payload_summary` (registered for `__dv_payload`) surfaces the file's JSON as the pointer's summary, which CodeLLDB puts in `result`. Earlier dead ends to remember: the template needs the `/nat` prefix (else CodeLLDB's *simple* parser → `Syntax error`); native clang needs `(FILE*)fopen`/`(long)fread`/`(int)fclose` casts (no libc prototypes). After editing, open a **fresh** Debug Visualizer view (or reload the window) — an open view caches the old template. |
| Debug Visualizer shows `No Visualization Available` although the data parses fine | The evaluate result reached the JSON parser (`variablesReference == 0`, good) and passed `isVisualizationData`, but **no visualizer claimed it because the JSON failed a visualizer's strict serializer schema** (silent). Pitfalls hit so far, both in `scripts/lldb_occt_formatters.py`: (1) the plotly `mode` must match the serializer's literal list *exactly* — it lists `"text+markers"`/`"lines+markers"`/`"text+lines"`, **not** the reversed `"markers+text"`/`"markers+lines"` (Plotly itself accepts both, the validator does not); (2) the text/`{"kind":{"text":true}}` visualizer requires a **`"text"`** string prop — `"value"` is silently rejected. To debug a new payload, run the template body in the debug console with `?/nat (...)` to see the raw JSON, then check it against the serializers in the Debug Visualizer webview bundle (`CommonDataTypes.d.ts` lists the shapes; the `mode`/`type` literal lists live in `main.js`). |
| Bare `FreeCADCmd` uses the wrong OCCT | Re-run the local FreeCAD preset and build, then use `workspace-doctor.sh --runtime`; workspace launch profiles also enforce `DYLD_LIBRARY_PATH` |
| OCCT breakpoints never bind (stay pending after `libTKFillet` loads) even though the build is Debug and the local library is loaded | OCCT's `occt/adm/cmake/occt_defs_flags.cmake` unconditionally adds `-Wl,-s` to `CMAKE_SHARED_LINKER_FLAGS` for Clang ("Optimize size of binaries"), which strips the macOS debug map (OSO stabs) from every shared library — DWARF stays in the `.o` files but LLDB can no longer map addresses to source. Guard that line with `if (NOT CMAKE_BUILD_TYPE STREQUAL "Debug")`, then `scripts/configure-occt.sh && scripts/rebuild-occ.sh`. Verify with `nm -pa occt/install/debug/lib/libTKFillet.7.8.1.dylib \| grep -c ' OSO '` (0 = stripped/broken, non-zero = debug map present). This lives in the vendored OCCT checkout, so a reset/checkout/pull of `occt/` can revert it — re-check the line if breakpoints regress. |
| `scripts/bootstrap.sh` rebuilds an old OCCT/FreeCAD after you upgrade one of them | The source revisions are **pinned**: `OCCT_REF` and `FREECAD_SHA` at the top of `scripts/bootstrap.sh`, mirrored in the README *Bootstrap from a fresh clone* section. After moving OCCT or FreeCAD to a new version, update both places. If OCCT changed, regenerate the patch with `git -C occt diff > patches/occt-debug-build.patch` (it may no longer apply on the new tag); if the FreeCAD CMake preset changed, re-copy it with `cp FreeCAD/CMakeUserPresets.json templates/CMakeUserPresets.json`. Otherwise a fresh clone — or an idempotent bootstrap repair run — silently reproduces the stale versions. |
| `agent`'s SSI env-emit capture (`capture_ssi_env` / box-r5 S3 `env_emit` path) returns `untestable` with `RuntimeError: blend face 未写出 … TKFillet 是否含 OCCT_DEBUG_SSI_OUT 改造？` | The `env_emit` capture (A7 WP5) depends on a source instrumentation in `occt/src/ChFi3d/ChFi3d_Builder_0.cxx::ChFi3d_StripeEdgeInter`: the `DStr` param is de-anonymized and, gated by the `OCCT_DEBUG_SSI_OUT` env var, the two overlapping blend surfaces are written as `blend1.brep`/`blend2.brep` just before the `throw StdFail_NotDone`. It is a pure addition (no behavior change when the env var is unset) but **as of 2026-07-01 it is an uncommitted working-tree edit in `occt/`, not part of the pinned `v7_8_1-fillet-debug` history** — so a fresh `bootstrap.sh` clone (or any `occt/` reset/checkout) drops it and the path silently degrades to `untestable` (it does *not* false-green). To make it durable, commit the edit onto `v7_8_1-fillet-debug` alongside the other debug edits (the current convention — the `.patch` file is legacy/reference only). Verify present: **`scripts/workspace-doctor.sh` now checks this automatically** (O3) — its `== WP5 source instrumentation ==` section `warn`s if either the fork source (`ChFi3d_Builder_0.cxx`) or the installed `libTKFillet` lacks the `OCCT_DEBUG_SSI_OUT` string (`strings` on the dylib finds the compiled-in `getenv` literal). For a full functional check also run `python -m agent.tools.test_capture` and confirm `box env_emit → s3_signature=True` is PASS (not SKIP). Rebuild after (re)applying: `scripts/rebuild-occ.sh`. |
