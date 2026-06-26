# occ-debug-mesh 导出数据设计

> 状态：**设计稿（待确认，未写代码）**<br>
> 目的：把 occ-debug-mesh 的导出从"够渲染"升级到"够调试几何算法"——系统化补全
> 点/边/面的**拓扑 + 几何**数据。<br>
> 相关：[occ-debug-mesh/README.md](../tools/occ-debug-mesh/README.md)（§7 边离散现状）、
> [uv-parametric-space-mapping.md](uv-parametric-space-mapping.md)（3D→UV 专题）、
> [print-mesh.schema.json](../tools/Print/protocol/print-mesh.schema.json)、
> `tools/Print/TestJson/`（`cg_edge_export` 既有方向：点带 3D+UV、边带 curve_hint/connected_edges）。

## 1. 现状与差距

| 已导出 | 缺口（本稿主体） |
| --- | --- |
| 面：`positions/indices/normals`（世界系三角网格） | 面的 **UV 节点、曲面类型+参数、UV 边界/周期性、内外环、容差** |
| 边：`points`（3D 折线） | 边的 **pcurve(UV 折线)、曲线类型/阶/周期、首尾顶点、相邻面、跨面连续性、容差、退化标志** |
| 缺陷：BRepCheck 分类（sidecar） | **顶点整体缺失**；**拓扑连接图**；**逐实体容差**；**NURBS 控制网**；跨快照身份 |

判断：当前数据**够画、不够调**。调 ChFi3d/Boolean/Mesh 时真正的线索是容差、连续性、参数化、缝边、拓扑共享、控制网——目前一个都没导。

## 2. 设计原则

1. **稳定 ID 双轨**：`MapShapes` 索引（`V1/E1/F1`，资产内寻址）+ **TShape 指针哈希**（`runtime_tshape`，跨快照追踪同一实体）+ `location_hash`（摆放）。event schema `topology_ref` 已留这三个字段。跨快照身份是难点，见 §6.1。
2. **点去重 + 3D/UV 并存**：照 `cg_edge_export`——顶点/采样点在 `points` 里只出现一次，每点带 `(x,y,z)` 与**所属面上**的 `(u,v)`。3D↔2D 双屏的地基。
3. **容差一等公民**：V/E/F 各级 `tolerance` 必导——OCCT 算法失败八成是容差问题。
4. **几何分档**：`kind` + 解析参数（便宜，默认导）；**控制网 / 完整 NURBS knots**（重，verbosity 开关，但**要求可在 3D 显示**，见 §4）。
5. **世界系 + 可复现摆放**：坐标落世界系（现状）；同时导 `orientation` + `location` 以复算。

## 3. 数据字典

> 状态列：✅ 已有 · ◻ 待加。优先级见 §4。

### 3.1 顶点 Vertex（当前完全缺失）

| 数据 | 拓扑/几何 | OCCT API | 状态 |
| --- | --- | --- | --- |
| `vertex_id` / `tshape` | 拓扑 | `TopExp::MapShapes(VERTEX)` / `TopoDS_Shape::TShape()` | ◻ |
| 3D 点 `(x,y,z)` | 几何 | `BRep_Tool::Pnt(v)` | ◻ |
| **`tolerance`** | 几何 | `BRep_Tool::Tolerance(v)` | ◻ |
| 在每条相邻边上的参数 | 几何 | `BRep_Tool::Parameter(v, e)` | ◻ |
| 在每个相邻面上的 `(u,v)` | 几何 | `BRep_Tool::Parameters(v, f)` | ◻ |
| 相邻边/面（度数） | 拓扑 | `TopExp::MapShapesAndAncestors(VERTEX, EDGE/FACE)` | ◻ |

### 3.2 边 Edge（扩 `cg_edge_export`）

| 数据 | 拓扑/几何 | OCCT API | 状态 |
| --- | --- | --- | --- |
| `edge_id` / `orientation` / `tshape` | 拓扑 | `MapShapes(EDGE)` / `.Orientation()` | 部分 |
| 首/尾顶点 | 拓扑 | `TopExp::FirstVertex/LastVertex(e, true)` | ◻ |
| 相邻面（1=自由/2=流形/>2=非流形） | 拓扑 | `MapShapesAndAncestors(EDGE, FACE)` | ◻ |
| `connected_edges` 拓扑图（via_vertex, self_at/other_at） | 拓扑 | 共享顶点反查 | ◻ |
| 标志 `Degenerated/SameParameter/SameRange/Closed` | 拓扑 | `BRep_Tool::Degenerated/SameParameter/SameRange`，`IsClosed(e,f)` | ◻ |
| **跨面连续性 G0/G1/G2/C1/C2** | 几何 | `BRep_Tool::Continuity(e, f1, f2)` → `GeomAbs_Shape` | ◻ |
| 3D 折线 `points`（+ `sample_count`） | 几何 | `PolygonOnTriangulation` / `GCPnts` | ✅ |
| **pcurve UV 折线**（每承载面一条；**缝边同面两条**） | 几何 | `BRep_Tool::CurveOnSurface(e, f[, Index])` 或 tri 的 `UVNode` | ◻ **P0** |
| `curve.kind`（line/circle/ellipse/bspline/bezier/offset…） | 几何 | `BRepAdaptor_Curve::GetType()` → `GeomAbs_CurveType` | ◻ |
| 参数域 `[first,last]` / `closed` | 几何 | `BRep_Tool::Range` | ◻ |
| 解析参数（圆:心/半径/轴；线:点/向） | 几何 | `BRepAdaptor_Curve::Circle()/Line()…` | ◻ |
| `tolerance` | 几何 | `BRep_Tool::Tolerance(e)` | ◻ |

### 3.3 面 Face

| 数据 | 拓扑/几何 | OCCT API | 状态 |
| --- | --- | --- | --- |
| `face_id` / `orientation` / `tshape` | 拓扑 | `MapShapes(FACE)` | 部分 |
| 外环 + 内环（孔），各环有序边 | 拓扑 | `BRepTools::OuterWire(f)` + 遍历 WIRE | ◻ |
| 三角网格 `positions/indices/normals` | 几何 | `BRep_Tool::Triangulation` | ✅ |
| **三角网格 UV 节点**（逐顶点 `(u,v)`） | 几何 | `tri->HasUVNodes()` / `tri->UVNode(i)` | ◻ **P0** |
| 曲面 `kind`（plane/cylinder/cone/sphere/torus/bspline/revolution/extrusion/offset） | 几何 | `BRepAdaptor_Surface::GetType()` → `GeomAbs_SurfaceType` | ◻ |
| **UV 边界 `[umin,umax,vmin,vmax]`** | 几何 | `BRepTools::UVBounds(f, …)` | ◻ **P0** |
| 周期/闭合 `closed_u/closed_v` `period_u/v`、连续性 | 几何 | `Geom_Surface::IsUPeriodic/IsUClosed/UPeriod` | ◻ |
| `tolerance` | 几何 | `BRep_Tool::Tolerance(f)` | ◻ |
| 解析参数（柱:轴/半径；球:心/半径…） | 几何 | `BRepAdaptor_Surface::Cylinder()/Sphere()…` | ◻ |

### 3.4 NURBS 控制网（曲线 + 曲面，**要求可在 3D 显示**）

| 数据 | OCCT API | 显示 |
| --- | --- | --- |
| 曲线极点 `poles[]` + 权 `weights[]` | `Geom_BSplineCurve::Pole(i)/Weight(i)` | 控制点（point_set）+ 控制多边形（polyline） |
| 曲线 `degree/knots/mults/rational/periodic` | `Geom_BSplineCurve::Degree/Knots/Multiplicities` | 文本/Inspector |
| 曲面极点网格 `poles[nu][nv]` + 权 | `Geom_BSplineSurface::Pole(i,j)/Weight(i,j)` | 控制点网 + 控制网格线（u、v 两向 polyline） |
| 曲面 `(deg_u,deg_v)/knots_u/v/mults/rational/periodic` | `Geom_BSplineSurface::*` | 文本/Inspector |

> 控制网映射到**现有 renderer**（point_set + polyline）即可在 3D 查看，几乎零新渲染成本。注意控制网属于**未裁剪的底层曲面**，会超出可见（裁剪后）面范围，需在 UI 标注，见 §6.5。

### 3.5 Wire / Shell / Solid / 全局

| 层级 | 数据 | OCCT API |
| --- | --- | --- |
| Wire | 闭合？有序边及朝向、外/内环 | `BRep_Tool::IsClosed` / `BRepTools::OuterWire` |
| Shell | 闭合？（NotClosed 缺陷）、自由边集 | `BRepCheck`（已有）+ 自由边=只属 1 面 |
| Solid | （体积/惯性——**按你的反馈不做**） | — |
| 全局 Shape | 世界 bbox、V/E/F/Shell/Solid 计数、validity（已有）、`unit`、`local_origin` | `BRepBndLib`（已用）/ `BRepCheck`（已用） |

## 4. 优先级（按你的反馈调整）

- **P0（下一步，调试刚需）**：顶点（点 + 容差）；边 **pcurve UV** + 曲线 `kind`；面 **三角网格 UV 节点** + 曲面 `kind` + `UVBounds`；各级 `tolerance`。→ 点亮 3D→2D 视图并开始能调真问题。
- **P1**：首尾顶点 / 相邻面 / `connected_edges` 拓扑图；**跨面连续性 G1/G2**；解析参数；内外环。
- **控制网（提级）**：NURBS 曲线/曲面 `poles/weights/knots`，**且可在 3D 显示**（你的明确期待）——从原 P2 提到"想要"。
- **移除/暂不（按你反馈）**：~~面积、边长~~（需求一般）；~~体积、惯性张量~~（不需要）；~~逐点曲率~~（不需要）。

## 5. Schema 落点

采用 **mesh（轻渲染）+ geom sidecar（拓扑/几何/容差/控制网）分离**：

- `<base>.mesh.json`（保持轻，**只 3D**）：面三角网格可加 `uv_nodes`（P0b）；边 `points`（3D）。**退化边也收**（3D 退化为单点 + `degenerate:true`），保证 V/E id 与 geom 对齐。仅当边"恰好只属 1 面且非缝"时，才允许放一份便利 `uv`。
- `<base>.geom.json`（新）：
  - `vertices[]`：`{id, point[xyz], tolerance}`（参数/UV 作引用，P1）。
  - `edges[]`：`{id, curve_type, tolerance, range, flags{degenerate,same_parameter,closed}, start_vertex, end_vertex, adjacent_faces[], pcurves[{face_id, is_seam, index, uv[[u,v]…]}]}`。**pcurve 是 UV 的权威来源**（不放 mesh.json）。
  - `faces[]`：`{id, surface_type, uv_bounds[umin,umax,vmin,vmax], periodic_u/v, closed_u/v, tolerance}`；NURBS 控制网（P0c）。
- 命名：几何类型用 **`curve_type`/`surface_type`**（不用 `kind`，避免与实体 kind 撞名）。
- UV 折线喂 UV 面板时对齐 `cg_edge_export` 风格（点 3D+UV）。

## 6. 设计审查：已知问题与未决项（请确认方向）

1. **跨快照身份（最硬）**：`MapShapes` 索引随形状被改而变（fillet 后 E5 可能变 E7）；`TShape` 指针仅进程内有效、释放后可能复用，跨进程/会话不持久。要把"同一条边在算法时间线上的演变"对齐，唯一可靠锚是 **FreeCAD 拓扑命名（`mapped_element`）**，但这要 FreeCAD 侧配合。**未决**：时间线对齐用 mapped_element / TShape 指针（脆）/ 几何匹配（贵）？建议先导 TShape 指针 + mapped_element（有就用），不做几何匹配。
2. **退化边 vs UV 视图冲突**：现 §7 对 `Degenerated` 边**跳过**（无 3D 曲线，如球极点）。但在 **UV 空间它们是真实的边界边**（一整条 UV 边塌成一个 3D 点）。UV 视图必须包含它们。**结论**：UV 路径不能套用"跳过退化边"，要单独走 pcurve。
3. **缝边两条 pcurve**：缝边在同一面上有**两条** pcurve（u=0 与 u=umax）。简单的 `CurveOnSurface(e,f)` 只给一条，必须用 `IsClosed(e,f)` 检测 + `CurveOnSurface(e,f,Index)` 取两条。漏了 UV 视图就画错缝。详见 [uv 专题](uv-parametric-space-mapping.md)。
4. **UV 节点可得性**：`Poly_Triangulation::HasUVNodes()` 可能为 false（取决于网格参数）。**需确认** BRepMesh 是否默认存 UV 节点；若否，要么改网格参数强制存，要么用 `BRep_Tool::CurveOnSurface`/投影补算。
5. **控制网 vs 裁剪**：控制网是**未裁剪底层曲面**的，会超出可见（裁剪）面，视觉上"对不上"。需在 UI 明确标注"控制网=底层曲面"。
6. **周期面三角化的缝**：BRepMesh 对周期面缝两侧节点可能重复/不重复，缝附近 UV 节点会 u=0 vs u=2π 二义。UV 网格视图要处理 unwrap。
7. **数据体量/精度**：完整 NURBS 网 + 逐面 pcurve 体量大 → sidecar + verbosity 必要；UV 坐标精度；世界坐标 three.js Float32 抖动（既有 H4 风险）对 UV 不适用但对 3D 仍在。
8. **类型 unwrap**：`TrimmedCurve`/`OffsetCurve`/`RectangularTrimmedSurface`/`OffsetSurface` 要剥到底层 BasisCurve/BasisSurface 报真实 `kind` + 偏移量，否则一律报成 "trimmed/offset" 丢信息。
9. **点去重 vs per-face UV（与 `cg_edge_export` 原则冲突）**：`cg_edge_export` 要求"交点全局只出现一次"，但**共享顶点在不同面上 UV 不同**（一个 3D 点对多个 (u,v)）。全局去重 + 单一 `(u,v)` 在多面体上不成立。**结论**：UV 必须按 **(point, face)** 携带，或点按面分组；3D 去重与 UV 分开两层。
10. **"UVNode 免费法"在缝边/退化边失效**：用三角网格 `UVNode` 取边 UV 对**普通边**成立，但**缝边有两条 pcurve、退化边塌成点**，`UVNode` 只给一侧。**结论**：缝边/退化边必须走显式 `CurveOnSurface(e,f,Index)`，不能只靠 UVNode。
11. **连续性可能被低报**：`BRep_Tool::Continuity(e,f1,f2)` 读的是**存储的 regularity 标志**，未编码时返回 `C0`，未必反映真实相切。要可靠判 G1/G2 可能得**沿边比两面法线实算**，而非只信标志。
12. **既有样例 UV 是假的**：`TestJson/edge-2d3d-sample.json` 里 `u==x, v==y`（平面投影占位，非真实曲面参数）。**别照抄样例语义**——真实导出要算真 pcurve UV。

## 7. 待确认决策点

- [ ] 跨快照身份方案（§6.1）：先 **TShape 指针 + mapped_element**？
- [ ] schema：确认 **mesh + geom sidecar 分离**（§5）。
- [ ] P0 范围：顶点+容差 / 边 pcurve UV+kind / 面 UV 节点+kind+UVBounds / 各级 tolerance —— 是否就按这个开干？
- [ ] 控制网：曲线控制多边形 + 曲面控制网，**3D 可视 + Inspector 文本**，确认要做。
- [ ] verbosity 开关：控制网/完整 knots 默认关、按需开——是否需要 CLI flag（如 `--geom full`）。

## 8. 审查补充（第二轮）与实施切片（已确认）

第二轮细审新增、已并入设计：
- `kind` 撞名 → 几何类型改 **`curve_type`/`surface_type`**。
- `SameParameter=false` → 非缝边 UV 用三角网格 `UVNode`（与 3D 逐点对齐）是 **P0b 优化**；**P0a 先用 2D pcurve 离散**（standalone，规避 `HasUVNodes` 风险）。
- pcurve 方向随 coedge 朝向翻 → 画 UV 环按 coedge 朝向定 CCW/CW（P0b）。
- UV 各向异性（U 弧度 / V 长度）→ UV 面板不假设正方形纵横比（P0b）。
- 顶点数据 M×N → **顶点点+容差只存一次**，参数/UV 作引用。
- 控制网实体爆炸 → 单独分组 `…/control-net/<face_id>` 且默认隐藏（P0c）。
- `Continuity` 默认 C0 → 先 `HasContinuity` 判，未编码不报（或 `MaxContinuity`）。
- 缝边两条 pcurve：用 `IsClosed(e,f)` 判，取 `CurveOnSurface(e,f)` 与 `CurveOnSurface(e.Reversed(),f)`。

**实施切片**：
> 各阶段详细总结见独立文档（本节为索引）：

- ✅ **P0a（纯 C++ + 离线断言）** → [occ-debug-mesh-p0a-geom-sidecar.md](occ-debug-mesh-p0a-geom-sidecar.md)：`geom` sidecar（顶点+容差、类型、`uv_bounds`、周期/闭合、边 flags/邻接、**pcurve UV** 含缝/退化）+ schema + 圆柱/球/环夹具 + 断言。
- ✅ **P0b（打通 3D→2D）** → [occ-debug-mesh-p0b-uv-viewer.md](occ-debug-mesh-p0b-uv-viewer.md)：`mesh-to-session` 注入 UV/类型/容差；`UvPanel` 真画 pcurve（**按面分图**、选中高亮）；`Inspector` 显示字段。配套：UV 实时刷新、换形状免刷新、隐藏全部、锁定可设置。
- ✅ **P0c（控制网）** → [occ-debug-mesh-p0c-controlnet.md](occ-debug-mesh-p0c-controlnet.md)：NURBS 控制网导出（曲线极点多边形 / 曲面极点网，世界坐标）+ viewer point_set/polyline（默认隐藏）+ Inspector degree/grid/poles。
