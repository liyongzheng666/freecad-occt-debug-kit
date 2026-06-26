# occ-debug-mesh — 设计说明书 / 交接文档

> 状态：M2 阶段 2 进行中（面网格 + 缺陷遍历 + **边离散**已完成并验证）<br>
> 用途：BREP → `print-mesh` JSON（逐面世界坐标三角网格）+ 缺陷 sidecar；供 daemon 转成事件喂 Print viewer<br>
> 本文件是**给新窗口/新会话接手用的自包含说明**。上层背景见
> [print-linkage-tech-decisions.md](../../docs/print-linkage-tech-decisions.md)、
> [m2-research-notes.md](../../docs/m2-research-notes.md)（§7 清单 / §9 缺陷层 / §10 N1-N8）、
> [change-log.md](../../docs/change-log.md)（§7-8 决策与进度）。

## 1. 在系统里的位置

```
occdbg(断点内) ─写 BREP─► assets/*.brep ─► [occ-debug-mesh] ─► *.mesh.json + *.defects.json
                                            （链本地 debug OCCT V7_8_1，与被调试进程同 ABI）
                                                    │
                                       daemon 读 → 追加 update/defect 事件 → Bridge → viewer
```
occ-debug-mesh 是**纯 CLI 工具**：吃一个 BREP，吐网格 + 缺陷。不碰 LLDB、不发事件（那是 daemon 的活，M2-3 方案 A）。

## 2. 构建与运行

```bash
scripts/build-occ-debug-mesh.sh          # pixi clang 18，OpenCASCADE_DIR=安装树配置
export DYLD_LIBRARY_PATH="$PWD/occt/install/debug/lib"
BIN=tools/occ-debug-mesh/build/occ-debug-mesh

$BIN <in.brep> [out.mesh.json]           # 转换：out 默认 in+".mesh.json"，缺陷写 <base>.defects.json
$BIN --timeout <sec> <in.brep> [out]     # 网格看门狗（V2 层1）：超时 → 未网格化面进 failed_faces、partial=true、不崩
$BIN --diagnose <in.brep>                # 打印 BRepCheck 对每个子形状的报告（调试用）
$BIN --make-test-box  <out.brep>         # 夹具：10x20x30 盒子（有效）
$BIN --make-test-bad  <out.brep>         # 夹具：开口壳当 solid（NotClosed）
$BIN --make-test-located <out.brep>      # 夹具：带 Location 的盒子（旋转90°Z+平移）
$BIN --make-test-selfx <out.brep>        # 夹具：自交(bowtie)面
$BIN --make-test-edge  <out.brep>        # 夹具：裸边（边离散验收用）
$BIN --make-test-nurbs <out.brep>        # 夹具：B-spline 曲面（曲面 + 4 条曲线边界边）
$BIN --make-test-bspline-edge <out.brep> # 夹具：裸 B-spline 曲线边
$BIN --make-test-cylinder <out.brep>     # 夹具：圆柱（缝边、U 周期）— geom/UV 用
$BIN --make-test-sphere <out.brep>       # 夹具：球（缝 + 2 极点退化边）— geom/UV 用
$BIN --make-test-torus <out.brep>        # 夹具：环（U+V 双周期）— geom/UV 用
$BIN --make-test-mirror <out.brep>       # 夹具：镜像 Location 盒子（det<0）— V9 绕序/法线
$BIN --make-test-nonmanifold <out.brep>  # 夹具：三面共一边（非流形边）— §9 non_manifold

scripts/verify-occ-debug-mesh.sh         # ★ 一键离线回归：跑全部夹具 + 断言（§6/§7）
scripts/mesh-view.py <base>.mesh.json    # 浏览器预览：面(半透明)+ edges[](高亮折线)，世界比例
```
**构建关键点**：`OpenCASCADE_DIR` 必须指**安装树** `occt/install/debug/lib/cmake/opencascade`——构建树 `occt/build/debug` 的 config 引用了没生成的模块 Targets，会报错。<br>
**运行无需 `DYLD_LIBRARY_PATH`**：构建已把 `occt/install/debug/lib` 烧进 rpath，二进制自寻 OCCT——所以 verify 脚本不碰环境变量、直接跑。

## 3. 当前架构（`src/main.cxx`）

- **`convert()`**：读 BREP → `BRepMesh_IncrementalMesh`（带参构造即网格化）→ `TopExp::MapShapes(FACE/EDGE/VERTEX)` → 逐面 `meshFace()` → `collectDefects()` → `collectEdges()` → `collect{Vertices,EdgeGeom,FaceGeom}()` → 写 mesh JSON + defects sidecar + **geom sidecar**。
- **`meshFace()`**：`BRep_Tool::Triangulation(face, loc)` 取面局部三角网格 → **应用 `loc.Transformation()` 得世界坐标**（M2-4）；缺法线时 `BRepLib_ToolTriangulatedShape::ComputeNormals`；`REVERSED` 面翻绕序+翻法线；非有限节点 → 整面计入 `failed_faces`。
- **`collectEdges()`**（§7）：`TopExp::MapShapes(EDGE)`（共享边自动去重，edge_id=`E`+i）+ `MapShapesAndAncestors(EDGE→FACE)`。**有三角化祖先面** → `edgeFromFace()` 复用 `Poly_PolygonOnTriangulation`（节点是面 tri 索引，套面 `loc` 落世界系，与面网格边界严丝合缝）；**裸边/面没三角化** → `edgeFromCurve()` 用 `BRepAdaptor_Curve`+`GCPnts_QuasiUniformDeflection` 直接离散曲线（adaptor 自带 edge location → 世界）。退化边 `Degenerated()` 跳过；非有限点丢该边；绝对挠度由 bbox 对角线 × 相对系数推出。
- **`collect{Vertices,EdgeGeom,FaceGeom}()` → `writeGeom()`**（P0a，§5 `geom.json`）：顶点（点+`Tolerance`）；边（`BRepAdaptor_Curve::GetType`→`curve_type`、range、flags、首尾顶点、相邻面、**pcurves**：`IsClosed(e,f)` 判缝→`CurveOnSurface(e,f)` + `CurveOnSurface(e.Reversed(),f)` 取两条，退化边仍留 pcurve）；面（`BRepAdaptor_Surface::GetType`→`surface_type`、`UVBounds`、`IsU/VPeriodic/Closed`、`Tolerance`）。**curve/surface 路径与 §7 渲染网格解耦**。
- **`collectDefects()` / `collectInto()`**：`BRepCheck_Analyzer`；**遍历 standalone `Status()` + context 状态**（关键坑：NotClosed 等存在"子形状在父语境下"的 context 里，且 `IsValid(sub)` 单独看可能是 valid）；wire 缺陷用 `MapShapesAndAncestors` 挂到**父面 face_id**；`statusName` 全 36 枚举命名（不丢信息），`statusCategory` 映射到 `defect.category`（未映射→other 但保留真名）。
- **`diagnose()`**：枚举所有子形状的 valid + 状态（含 context），调试神器。
- **夹具** `makeTest*()`：离线造各种 BREP 验收，无需 LLDB。

## 4. 已固化的设计决策（改动前先读）

| 决策 | 取值/做法 | 出处 |
| --- | --- | --- |
| deflection | 相对挠度系数 **0.002**、角 **0.5 rad** | OCCT 默认 0.001/0.5，放粗一档求调试快 |
| 法线 | `BRepLib_ToolTriangulatedShape::ComputeNormals`（同 AIS）；`REVERSED` 翻 | 不手搓、跨光滑边平滑 |
| 世界坐标 | 读 `Poly_Triangulation` 后**应用累积 `TopLoc_Location`** | M2-4；已验证非 identity 也对 |
| face_id/edge_id | `= TopExp::MapShapes` 索引（`F1`/`E1`…） | M2-5；mesh 与 defect ref 共用同一索引 |
| 缺陷映射 | `BRepCheck_Status` → category；未映射 `other` 但保留真名 | §9；BRepCheck ~36 码 |
| 坏面 | 非有限节点/无三角化 → `failed_faces`，`partial=true` | V2/D4；坏 shape 不崩 |
| 边离散 | 有三角化祖先面→复用 `PolygonOnTriangulation`；否则 `GCPnts_QuasiUniformDeflection` 离散曲线 | §7/Q4；前者与面网格重合且免费 |
| 边挠度 | GCPnts 用**绝对**挠度 = bbox 对角线 × 相对系数(0.002)，下限 1e-3 | §7；GCPnts 不收相对系数，按 shape 尺度自适应 |

**7.8 API 教训**：`Poly_Triangulation` 用 1-based `Node(i)`/`Triangle(i)`/`Normal(i)`（不是旧 `Nodes()` 数组）。**改 OCCT 调用前先 `grep` 头文件确认 7.8.1 签名**（我们就是这么避坑的）。

## 5. 输出格式

- **`<base>.mesh.json`**：见 [Print/protocol/print-mesh.schema.json](../Print/protocol/print-mesh.schema.json)。`faces[]`（face_id/orientation/positions/indices/normals，世界 double；**`normals` 可选**——退化面算不出法线时省略该字段，viewer 自行重算）、`edges[]`（edge_id/points，世界 double 折线；§7）、`partial`/`failed_faces`。**无 per-asset origin**（会话级 origin 由 viewer 减）。<br>**注意 `edges[]` 是全部边的子集**：退化边和两条离散路径都失败的边不出现在这里（但仍在 `geom.json` 的 `edges[]` 里，`curve_type:"none"`）；`edge_id` 同 `MapShapes` 索引，mesh 里查不到某 `E_i` 属正常，去 geom 找。
- **`<base>.defects.json`**：`defect` 对象数组 `{category, source:"brepcheck", severity, status:"BRepCheck_*", ref?:{face_id/edge_id}}`，对齐 [event.schema.json](../Print/protocol/event.schema.json) 的 `$defs.defect`（`entity_id` 由 daemon 填）。
- **`<base>.geom.json`**（P0a，几何/拓扑 sidecar）：见 [Print/protocol/geom.schema.json](../Print/protocol/geom.schema.json)。`vertices[]`（id/point/tolerance）、`edges[]`（curve_type/range/容差/flags/首尾顶点/相邻面/**pcurves[]** UV，缝边两条、退化边一条）、`faces[]`（surface_type/uv_bounds/周期·闭合/容差）；B-spline 边/面带 **`control`**（NURBS 控制网：极点/degree/grid，世界坐标，P0c）。3D 世界系、UV 在面参数系。设计见 [docs/occ-debug-mesh-export-design.md](../../docs/occ-debug-mesh-export-design.md)。

## 6. 已验证（测试矩阵，可一键回归 → `scripts/verify-occ-debug-mesh.sh`，60 项断言）

| 夹具 | 期望 | 状态 |
| --- | --- | --- |
| box | 6 面、12 三角、世界 bbox [0,10]×[0,20]×[0,30]、法线外向；**12 边（每条 2 点）、边 bbox = 面 bbox** | ✅ |
| located（旋转+平移） | 世界 bbox X[80,100] Y[200,210] Z[300,330]、法线外向单位长；**12 边同样落世界 bbox** | ✅ M2-4 命脉（面+边） |
| bad（开口壳） | `NotClosed → open_boundary`（场景级保留）；5 面；**4 条自由边带 `open_boundary` edge_ref（R3，source=topology/FreeEdge）** | ✅ R3 |
| selfx（自交面） | `SelfIntersectingWire → self_intersection`（ref=父面 F1）+ `UnorientableShape`；面不可三角化(0 面)，**4 边走裸曲线兜底（§7 path B）** | ✅ |
| edge（裸边） | 0 面、**1 条 polyline = (0,0,0)→(10,5,2)** | ✅ §7 |
| nurbs（B-spline 曲面） | 1 面、4 边界边；曲线边按挠度多点（实测 max≥10，如 35/17/34），x=0 直 isoline 仍 2 点 | ✅ §7 曲线 |
| bspline-edge（裸 B-spline） | 0 面、**1 条多点折线**（实测 36 点，GCPnts 曲线离散） | ✅ §7 曲线 |
| mirror（镜像 Location） | 世界 bbox X[40,50] Y[0,20] Z[0,30]、**法线外向 + 绕序与法线一致**（winding_ok）；12 边落世界 bbox | ✅ V9（绕序+法线统一 `reversed^mirror`） |
| nonmanifold（三面共边） | 3 面；geom 中**1 条边邻接 3 面**；`non_manifold` 缺陷 ref=该边、source=`topology` | ✅ §9（拓扑边邻接，非 BRepCheck/bopcheck） |

> 曲线边断言只在**夹具级**判定（`max 点数/边 ≥ 10`），不逐边断言 `>2`：局部接近直线的段（如上面 x=0 的 isoline）会退化成 2 点；闭环/缝边的两端在 3D 重合、只有 UV 空间区分。

## 7. ✅ 已完成：边离散

**目标**：填上 `print-mesh` 的 `edges[]`（曾硬编码为 `[]`）。**已实现并验证**（`collectEdges()`，见 §3；回归 `scripts/verify-occ-debug-mesh.sh`）。

**已定方案（Q4，见 change-log §7）**：按输入分派——
- **面上的边**：复用 `Poly_PolygonOnTriangulation`（已网格化、与面网格边界严丝合缝、免费）。
- **裸 Edge/Wire**：`GCPnts_QuasiUniformDeflection` 直接离散曲线（无需网格）。

**实现算法**：
```
edges_map = TopExp::MapShapes(shape, EDGE)         // 自动去重共享边；edge_id = "E"+i
edgeFaces = TopExp::MapShapesAndAncestors(shape, EDGE, FACE)
for each edge E_i:
    if 有祖先面 F 且 F 已三角化:
        tri, loc = BRep_Tool::Triangulation(F, loc)
        poly = BRep_Tool::PolygonOnTriangulation(E_i, tri, loc)   // 节点是 tri 节点的索引
        points = [ tri.Node(poly.Node(k)).Transformed(loc) ]      // 世界坐标
    else:   // 裸边 / 面没三角化
        adaptor = BRepAdaptor_Curve(E_i)                          // 含 edge location → 世界
        GCPnts_QuasiUniformDeflection d(adaptor, deflection)
        points = [ d.Value(k) for k in 1..d.NbPoints() ]
    if points 有效（>=2，全有限）: edges[].push({edge_id:"E"+i, points})
```

**要点 / 坑**：
- **世界坐标**：两条路径都要落到世界系（PolygonOnTriangulation 用 tri 的 loc；BRepAdaptor_Curve 自带 edge location）。
- **7.8 API**：`Poly_PolygonOnTriangulation` 的节点访问（`Node(k)`/`Nodes()`）先 grep 头文件确认；`BRep_Tool::PolygonOnTriangulation(edge, tri, loc)` 签名同上确认。
- **退化边**：`BRep_Tool::Degenerated(edge)` 为真则跳过（无 3D 曲线）。
- **NaN 守卫**：同 `meshFace`，非有限点丢弃该边。
- **deflection**：与面网格一致（相对系数或由 bbox 推一个绝对值；GCPnts 用绝对挠度）。

**验收**（全部通过，`scripts/verify-occ-debug-mesh.sh`）：
- `box` → **12 条边**（每条直线 2 点），边 bbox 与面 bbox 一致 [0,10]×[0,20]×[0,30]。
- `located` → 12 条边落世界 bbox X[80,100] Y[200,210] Z[300,330]（边的世界坐标路径，M2-4）。
- `--make-test-edge` 裸边 → **1 条 polyline** = (0,0,0)→(10,5,2)（曾是 0）。
- 实测发现：`selfx` 自交面**不可三角化（0 面）**，4 条边经 `edgeFromFace` 失败后落到 `edgeFromCurve` 兜底——验证了"有祖先面但面没网格"也走裸曲线路径。

**涉及头文件**：`BRep_Tool.hxx`（`PolygonOnTriangulation`/`Degenerated`/`Curve`）、`Poly_PolygonOnTriangulation.hxx`、`BRepAdaptor_Curve.hxx`、`GCPnts_QuasiUniformDeflection.hxx`（CMake 链接已够：TKMesh/TKGeomBase/TKBRep；如缺符号补 toolkit）。

## 8. 其它遗留 / 延后（backlog）

**✅ 本轮已清（见 §6 矩阵 mirror/nonmanifold + bad 的 R3 断言）**：
- **镜像翻绕序（V9）**：`meshFace` 用统一 `flip = reversed XOR trsf.IsNegative()` 翻绕序+法线（`gp_Dir::Transformed` 在负 scale 下已自动取反，单次 flip 同时抵消并定向外向）。夹具 `--make-test-mirror` + `winding_ok` 断言。
- **non_manifold（§9）**：**不是** `BRepAlgoAPI_Check`/bopcheck（实测 `BOPAlgo_CheckStatus` 无 NonManifold；bopcheck 不报）——改用拓扑边邻接：相异邻接面 >2 即非流形边，发 `{non_manifold, source:topology, ref:edge_id}`。夹具 `--make-test-nonmanifold`。
- **shell 缺陷 ref（R3）**：`NotClosed` 时把开边界落到自由边（邻接面==1），发 `{open_boundary, source:topology, status:FreeEdge, ref:edge_id}`，场景级 NotClosed 保留。复用 `bad` 夹具。
- **bootstrap 接入（M2-10）**：`bootstrap.sh` 步骤 5b 建 occ-debug-mesh、步骤 7 跑 `verify-occ-debug-mesh.sh`。
- **超时看门狗 层1（V2）**：`--timeout <sec>` 经 `IMeshTools_Parameters`+`Message_ProgressRange` 驱动 `WallClockBreak::UserBreak()`；BRepMesh 按面轮询（`BRepMesh_FaceDiscret`），超时后未网格化面落 `failed_faces`、`partial=true`、不崩。默认关闭（不传则与原行为字节级一致）。回归含 tiny/generous 两条断言。

| 项 | 说明 | 关联 |
| --- | --- | --- |
| 超时看门狗 **层2** | 单面**内部**死循环 per-face 取消救不了；需 daemon 外部 `timeout(1) occ-debug-mesh …` 硬杀（daemon 本就管子进程） | V2 |
| `sha256`（**已定 daemon 侧**） | **occ-debug-mesh 不算 sha256**（保持纯几何、不引 crypto）。daemon 读 `*.mesh.json`/`*.defects.json`/`*.geom.json` 落盘字节算 sha256，填进它生成的 manifest 供 viewer 按内容哈希缓存。工具零改。 | V7 |
| ChFi3d 算法状态 | WalkingFailure/TwistedSurface 来自**运行中**的 `BRepFilletAPI_MakeFillet`（枚举 `ChFiDS_ErrorStatus`），静态 BREP 拿不到 → 属 daemon/LLDB 层，非本工具 | M3 |

## 9. 给新窗口的上下文地图

0. **总目录**：[docs/README.md](../../docs/README.md)（全 docs 索引；接手先看这个）。
1. 读 [m2-research-notes.md](../../docs/m2-research-notes.md)：§3 锁定的 M2-1/2/3、§7 文件清单、§9 缺陷层、§10 N1-N8。
2. 读 [print-linkage-tech-decisions.md](../../docs/print-linkage-tech-decisions.md)：接缝契约、print-mesh 格式、§8 风险表。
3. 协议真源：[Print/protocol/*.schema.json](../Print/protocol/)。
4. 本工具代码：`src/main.cxx`（单文件）；构建：`scripts/build-occ-debug-mesh.sh`。
5. 验收习惯：每加一块就造夹具、离线断言（见 §6/§7），别依赖 LLDB。
6. **导出数据扩展**：设计/索引 [occ-debug-mesh-export-design.md](../../docs/occ-debug-mesh-export-design.md)（§8 切片索引）+ [uv-parametric-space-mapping.md](../../docs/uv-parametric-space-mapping.md)（3D↔UV 专题）；各阶段总结 [P0a geom sidecar](../../docs/occ-debug-mesh-p0a-geom-sidecar.md) / [P0b UV viewer](../../docs/occ-debug-mesh-p0b-uv-viewer.md) / [P0c 控制网](../../docs/occ-debug-mesh-p0c-controlnet.md)。
