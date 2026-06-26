# P0a —— 几何/拓扑 sidecar 导出（纯 C++）

> 状态：**已完成**<br>
> 目的：在渲染 mesh 之外，把"调试几何算法"真正需要的**拓扑 + 几何**数据导出成
> `<base>.geom.json`：顶点+容差、曲线/曲面类型、UV 边界+周期、边 flags/range/邻接、
> **pcurve（UV 折线）**。**不碰 viewer**（P0b 再打通 3D→2D）。<br>
> 上游：[occ-debug-mesh-export-design.md](occ-debug-mesh-export-design.md)（§5 schema、§8 切片）、
> [uv-parametric-space-mapping.md](uv-parametric-space-mapping.md)（缝边/周期/极点）、
> [occ-debug-mesh/README.md](../tools/occ-debug-mesh/README.md)（§3/§5）。

## 1. 目标与范围

- 新增 sidecar `<base>.geom.json`，与 `mesh.json`（轻渲染）分离。schema：[geom.schema.json](../tools/Print/protocol/geom.schema.json)。
- 内容：`vertices[]`、`edges[]`（含 **pcurves**）、`faces[]`。3D 世界系，UV 在面参数系。
- 不在范围：NURBS 控制网（P0c）、连续性 G1/G2 实算（P1）、跨快照身份（P1）。

## 2. 数据格式（geom.json）

```jsonc
{
  "format_version": "1.0", "unit": "mm",
  "vertices": [{ "id": "V1", "point": [x,y,z], "tolerance": 1e-7 }],
  "edges": [{
    "id": "E2", "curve_type": "line",          // line/circle/.../bspline/offset/none(无3D曲线)
    "tolerance": 1e-7, "range": [first,last],
    "degenerate": false, "same_parameter": true, "closed": false,
    "start_vertex": "V1", "end_vertex": "V2",
    "adjacent_faces": ["F1"],                   // 1=自由/2=流形/>2=非流形
    "pcurves": [                                // UV 折线（权威 UV 来源）
      { "face_id": "F1", "is_seam": true, "index": 1, "uv": [u,v, ...] },
      { "face_id": "F1", "is_seam": true, "index": 2, "uv": [u,v, ...] }   // 缝边的另一侧
    ]
  }],
  "faces": [{
    "id": "F1", "surface_type": "cylinder",     // plane/cylinder/cone/sphere/torus/bspline/...
    "uv_bounds": [umin,umax,vmin,vmax],
    "periodic_u": true, "periodic_v": false, "closed_u": true, "closed_v": false,
    "tolerance": 1e-7
  }]
}
```

## 3. C++ 实现（`tools/occ-debug-mesh/src/main.cxx`）

- `collectVertices`：`BRep_Tool::Pnt`（located→世界）+ `Tolerance`。
- `collectFaceGeom`：`BRepAdaptor_Surface::GetType()`→`surface_type`；`BRepTools::UVBounds`；
  `Geom_Surface::IsU/VPeriodic/Closed`；`Tolerance`。
- `collectEdgeGeom`：`BRepAdaptor_Curve::GetType()`→`curve_type`（退化/纯 pcurve 边给 `none`）；
  `Degenerated/SameParameter/IsClosed`；`FirstVertex/LastVertex`→顶点 id；
  `MapShapesAndAncestors(EDGE→FACE)`→邻接面（去重）；**pcurves**（见 §4）。
- `discretizePCurve`：`Geom2d_Line`→2 点，其余 24 点均匀采样。
- `writeGeom`：输出三段数组。

## 4. 关键设计 / 坑

- **缝边两条 pcurve**：`BRep_Tool::IsClosed(e,f)` 判缝 → `CurveOnSurface(e,f)`（idx1）+
  `CurveOnSurface(e.Reversed(),f)`（idx2）取两侧。简单单条会把缝画塌。
- **退化（极点）边仍留 pcurve**：§7 渲染路径会跳过退化边（无 3D 曲线），但 UV 视图**必须含**它们
  （球极点：一整条 UV 边塌成一个 3D 点）。geom 路径独立、不跳过。
- **世界系**：顶点/极点 `Transformed(loc.Transformation())`；pcurve 是面参数系（非世界）。
- **id 对齐**：`V/E/F` 用 `TopExp::MapShapes` 索引，与 mesh 的 face/edge_id 同源。

## 5. 验收夹具与断言（`scripts/verify-occ-debug-mesh.sh`）

新增 `--make-test-cylinder/sphere/torus`，16 项 geom 断言（离线、无 LLDB）：

| 夹具 | 断言要点（实测全过） |
| --- | --- |
| box | 8 顶点、全 plane/line、无缝无退化、V/E/F 容差>0 |
| cylinder | cylinder+plane、circle+line、**缝边带 2 条 pcurve**、仅 U 周期 |
| sphere | sphere、**2 条极点退化边（各留 pcurve）**、缝、U 周期 |
| torus | torus、**U+V 双周期**、缝 pcurve |

geom schema 校验 6 个夹具全部 VALID。圆柱 UV 展开 = 矩形 + 2 条缝线 + 2 条圆边线（教科书）。

## 6. 改动文件

| 仓库 | 文件 | 改动 |
| --- | --- | --- |
| 父仓 freecad | `tools/occ-debug-mesh/src/main.cxx` | 三个 collector + writeGeom + 圆柱/球/环夹具 |
| 父仓 freecad | `scripts/verify-occ-debug-mesh.sh` | 16 项 geom 断言 |
| Print 子仓 | `tools/Print/protocol/geom.schema.json` | 新增 sidecar schema |

## 7. 复现

```bash
scripts/build-occ-debug-mesh.sh
BIN=tools/occ-debug-mesh/build/occ-debug-mesh
$BIN --make-test-cylinder /tmp/c.brep && $BIN /tmp/c.brep /tmp/c.mesh.json   # -> c.geom.json
scripts/verify-occ-debug-mesh.sh                                              # 全过
```
