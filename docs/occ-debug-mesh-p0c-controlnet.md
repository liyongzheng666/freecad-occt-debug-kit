# P0c —— NURBS 控制网导出与可视化

> 状态：**已完成**（回归 50/50 全过）<br>
> 目的：把 B-spline 曲线/曲面的**控制网**（极点 + degree + 网格结构）导出到 geom sidecar，
> 并在交互 viewer 里以 3D 控制点 + 网格线显示、Inspector 列出参数。<br>
> 上游：[occ-debug-mesh-export-design.md](occ-debug-mesh-export-design.md)（§4 控制网提级、§8 切片）、
> [occ-debug-mesh/README.md](../tools/occ-debug-mesh/README.md)（§5 输出格式）、
> [change-log.md](change-log.md)（§9 P0c 行）。

## 1. 目标与范围

- **导出**（P0c-a，纯 C++）：geom.json 的 B-spline 边/面带 `control`（极点世界坐标、degree、网格维度、rational/periodic）。
- **可视化**（P0c-b，viewer）：控制网发成 `point_set`（极点）+ `polyline`（曲线控制多边形 / 曲面网格线），独立子组、默认隐藏；Inspector 显示控制网摘要。
- **不在范围**：完整 knot 矢量（暂不导，Inspector 只给 degree/grid）；权重仅在 rational 时导。

## 2. 数据格式（geom.json 的 `control`）

仅 B-spline 曲线/曲面才有该字段（解析体——平面/圆柱/球/环——无控制网）。schema 见
[geom.schema.json](../tools/Print/protocol/geom.schema.json) 的 `$defs/control`。

```jsonc
"control": {
  "degree_u": 3, "degree_v": 3,      // 曲线只用 degree_u；degree_v=0
  "nb_u": 6, "nb_v": 6,              // 极点网维度；曲线 nb_v=0（极点数=nb_u）
  "rational": false,
  "periodic_u": false, "periodic_v": false,
  "poles": [x,y,z, ...],            // 扁平世界坐标；曲面 row-major（u 外层 / v 内层），长度 nb_u*nb_v*3
  "weights": [ ... ]               // 仅 rational 时出现
}
```

- **世界坐标**：极点取自 `Geom_BSpline*::Pole(...)`（局部系），统一 `Transformed(loc.Transformation())` 落世界系（loc 取自 `BRep_Tool::Curve/Surface`）。
- **曲面极点索引**：`poles[(i*nb_v + j)*3 ...]`，i 沿 U（外）、j 沿 V（内）。
- **网格线由维度重建**：U 行 = 固定 i、j 走 0..nb_v-1；V 列 = 固定 j、i 走 0..nb_u-1。

## 3. C++ 实现（`tools/occ-debug-mesh/src/main.cxx`）

- **剥壳** `asBSplineCurve` / `asBSplineSurface`：把可能被 `TrimmedCurve`/`OffsetCurve`/
  `RectangularTrimmedSurface`/`OffsetSurface` 包裹的几何递归剥到 `Geom_BSpline*` 基；非 B-spline 返回 null。
- **提取** `curveControlNet(edge)` / `surfaceControlNet(face)`：
  - 曲线：`BRep_Tool::Curve(e, loc, f, l)` → 剥壳 → `Degree/NbPoles/IsRational/IsPeriodic/Pole(i)[/Weight(i)]`。
  - 曲面：`BRep_Tool::Surface(f, loc)` → 剥壳 → `UDegree/VDegree/NbUPoles/NbVPoles/IsU(V)Rational/IsU(V)Periodic/Pole(i,j)`。
  - 极点 `Transformed(loc.Transformation())` → 世界。
- `ControlNet` 结构挂到 `EdgeGeom.control` / `FaceGeom.control`；`collectEdgeGeom`/`collectFaceGeom` 调用提取。
- `writeControl()`：present 才输出 `control` 对象（接在 edge/face 尾部）。
- **toolkit**：`Geom_BSpline*`/`GeomAbs_*`/`BRep_Tool` 都在已链 TKBRep/TKG3d，无需新增。

## 4. viewer 实现（`scripts/mesh-to-session.py`）

> P0c **没有新增 viewer renderer**——直接复用 P0b 已有的 `point_set` 与 `polyline` 渲染器。

- `emit_control_net(base, owner_id, ctrl)`：
  - `point_set`（极点，黄 `#f1c40f`，size 6）。
  - 曲线 → 一条 `polyline`（控制多边形）；曲面 → `nb_u` 条 U 行 + `nb_v` 条 V 列 `polyline`（暗黄 `#caa83a`）。
  - 子组 `occ-debug-mesh/<base>/control-net/<owner_id>`，结尾 `set_visibility(group, visible=false)` → **默认隐藏**（图层树逐个开）。
- 面/边实体 metadata 加 `control` 摘要串（如 `bspline deg(5,5) 6×6, poles 36`）→ Inspector「元数据」自动显示。

**看法**：选中面/边 → Inspector 看 `control`；图层树展开 `…/control-net/<id>` → 点「显示」→ 3D 出现黄色控制点 + 网格线。

## 5. 夹具教训（关键）

控制网**可视化**夹具不能用高次插值生成曲面：

| 做法 | 结果 |
| --- | --- |
| ❌ 旧：`GeomAPI_PointsToBSplineSurface`(6×6, **5 次插值**) | 控制点剧烈过冲（z 甩到 **[-34,41]** vs 曲面 [-6,6]）、xy 非单调 → 控制网乱成一团 + 尖刺 |
| ✅ 新：**直接用 6×6 控制网格构造** `new Geom_BSplineSurface(poles, knots, mults, 3, 3)` | 控制网**就是**那张波浪网格，z ∈ **[-6, 5.6]**、xy 单调 → 整齐贴合曲面 |

要点：导出代码本身没 bug（极点顺序/世界坐标都对，四角=数据点）；问题在夹具。**clamped 均匀节点**：`nk = n-deg+1` 个 distinct 节点，两端 mult `deg+1`、内部 1。

## 6. 验证（`scripts/verify-occ-debug-mesh.sh`，6 项 control 断言）

- `nurbs.geom`：bspline 曲面有控制网、`nb_u==6 && nb_v==6`、`poles == nb_u*nb_v*3`、**4 条边界都有控制多边形**。
- `bspline-edge.geom`：曲线控制多边形 **7 极点、degree 6**。
- `box.geom` / `cylinder.geom`：**无控制网**（解析体）。
- schema 校验：6 个 geom 夹具全部 VALID。

## 7. 改动文件

| 仓库 | 文件 | 改动 |
| --- | --- | --- |
| 父仓 freecad | `tools/occ-debug-mesh/src/main.cxx` | 剥壳/提取/`ControlNet`/`writeControl`；`makeTestNurbs` 改直接构造 |
| 父仓 freecad | `scripts/mesh-to-session.py` | `emit_control_net` + metadata 摘要 |
| 父仓 freecad | `scripts/verify-occ-debug-mesh.sh` | 6 项 control 断言 |
| Print 子仓 | `tools/Print/protocol/geom.schema.json` | `$defs/control` + edge/face 引用 |

> viewer `.tsx` **无改动**（复用 point_set/polyline + Inspector 自动 dump）。

## 8. 复现

```bash
scripts/build-occ-debug-mesh.sh
BIN=tools/occ-debug-mesh/build/occ-debug-mesh
$BIN --make-test-nurbs /tmp/nurbs.brep && $BIN /tmp/nurbs.brep /tmp/nurbs.mesh.json   # -> nurbs.geom.json 带 control
scripts/verify-occ-debug-mesh.sh                                                       # 50/50
python3 scripts/mesh-to-session.py /tmp/nurbs.mesh.json --session .occ-debug/sessions/dev --fresh
# viewer 里展开 occ-debug-mesh/nurbs/control-net/F1 → 显示
```

## 9. 后续（未做）

- 完整 knot 矢量 + 在 Inspector 展开（verbosity 开关 `--geom full`）。
- 曲线控制多边形/曲面控制网的**权重可视**（rational：极点大小按权重）。
- bspline-edge 夹具仍用插值（`GeomAPI_PointsToBSpline`，degree 6）——曲线控制多边形可接受，未改；如需同样"直接构造"可比照 §5。
