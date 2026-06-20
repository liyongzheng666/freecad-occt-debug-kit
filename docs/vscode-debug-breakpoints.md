# Breakpoint management and debug visualization

This workspace already runs the recommended macOS debug stack: clangd for editing,
CodeLLDB (`vadimcn.vscode-lldb`) for debugging, plus the OCCT/Qt LLDB formatters imported by
every launch profile in `.vscode/launch.json`. The debugger itself is not the bottleneck.

Two pain points remain when debugging across the `FreeCAD/` and `occt/` trees: organizing many
breakpoints, and inspecting nested geometry objects. VS Code's debug UI (including the BREAKPOINTS
panel) is essentially not extensible — there is no plugin that replaces the panel ([microsoft/vscode#237856](https://github.com/microsoft/vscode/issues/237856)).
The practical fix is two focused extensions plus the underused built-in breakpoint features below.

Both extensions are in `.vscode/extensions.json`, so VS Code offers to install them when the
workspace is reopened. Run **Extensions: Show Recommended Extensions** to install on demand.

## Breakpoints Manager (`loukas-kotas.breakpoints-manager`)

Solves "too many breakpoints, scattered across two large trees."

- Group breakpoints into **Collections** and toggle a whole collection on/off at once — e.g. keep
  one collection for the fillet path (`FeatureFillet.cpp` → `BRepFilletAPI_MakeFillet` → `ChFi3d`)
  and a separate one for an unrelated investigation, without losing either set.
- **Export / Import** a collection as JSON to archive or share a debugging scenario. Commit a JSON
  export next to a bug note so a teammate reproduces the exact breakpoint layout.
- Use the Breakpoints Manager view in the side bar (or its command-palette commands) to create,
  select, and switch collections.

Suggested starting collection — the fillet breakpoints from `occt-debugging.md`:

- `FreeCAD/src/Mod/Part/App/FeatureFillet.cpp` at `Part::Fillet::execute`
- `occt/src/BRepFilletAPI/BRepFilletAPI_MakeFillet.cxx` at `Add` or `Build`
- `occt/src/ChFi3d/ChFi3d_Builder_C1.cxx` at `PerformIntersectionAtEnd`

## Debug Visualizer (`hediet.debug-visualizer`)

Solves "expanding `TopoDS_Shape` / `Handle` / point sets in the Variables panel is tedious."

- Command palette → **Debug Visualizer: New View**, then type a watch expression. While stopped in
  a frame, the view renders the evaluated value as a tree, table, or graph and refreshes on each
  step.
- It evaluates expressions through the active CodeLLDB session, so the OCCT/Qt formatters already
  loaded by the launch profile apply here too — prefer expressions that the formatters summarize
  (a shape handle, a `gp_Pnt`, a container of points) over deeply raw structs.
- Pin one visualizer view to the value you are tracking and let it update as you step, instead of
  re-expanding the Variables tree every stop.

## Underused built-in breakpoints (no install)

Much of the "unintuitive panel" feeling disappears once these are in use. Right-click a breakpoint →
**Edit Breakpoint**, or use **Add Function Breakpoint** in the BREAKPOINTS panel header.

| Feature | When to use |
| --- | --- |
| Conditional breakpoint | Stop only when an expression is true — e.g. a specific edge index inside an OCCT loop |
| Hit-count breakpoint | Stop on the Nth pass through a hot path instead of stepping there manually |
| Logpoint | Print an expression without pausing — avoids sprinkling `Base::Console` calls |
| Triggered breakpoint | Arm breakpoint B only after breakpoint A is hit, to isolate one call path |
| Function breakpoint | Break by symbol name when a templated/overloaded OCCT function has no obvious line |

## See also

- `docs/occt-debugging.md` — full clangd + CodeLLDB workflow, build-first launch profiles, and the
  reproducible fillet smoke scenario.
