# 3D ↔ UV 参数空间映射：问题与方案

> 状态：**研究/设计稿（待确认，未写代码）**<br>
> 目的：把 3D→2D(UV) 视图真正打通，重点啃**周期/封闭曲面**的难点；结合 OCCT、
> Parasolid/ACIS、STEP 与 NURBS 文献，整理问题与处理方案。<br>
> 相关：[occ-debug-mesh-export-design.md](occ-debug-mesh-export-design.md)（数据导出）、
> `tools/Print/TestJson/`（`cg_edge_export`：点带 (u,v)）、
> [UvPanel.tsx](../tools/Print/viewer/src/features/uv-viewer/UvPanel.tsx)（当前是桩）。

## 1. 为什么需要 UV 视图

几何算法（fillet、boolean、offset、mesh）大量工作发生在**参数空间**：pcurve 求交、缝边拼接、周期 wrap。很多 3D 里看不出的 bug（缝错位、极点退化、pcurve 越界、UV 自交）在 UV 平面上一眼可见。**3D↔UV 双屏对照**是调试这类问题的核心工具——这也是 `cg_edge_export` 让每个点同时带 `(x,y,z)+(u,v)` 的原因。

## 2. 映射的本质

- **面**承载一张曲面 `S(u,v) → R³`（`Geom_Surface`），面是其参数域上一块（可能被裁剪的）区域。
- **边在面上**有一条 **pcurve** `C₂(t) → (u,v)`（`Geom2d_Curve`），它和 3D 曲线 `C₃(t)` 满足 `S(C₂(t)) ≈ C₃(t)`（在容差与 SameParameter 意义下）。
- UV 视图画的就是：面的 UV 矩形域 `[umin,umax]×[vmin,vmax]` + 各边的 pcurve 折线 + 三角网格的 UV 节点。

OCCT 取数：`BRep_Tool::CurveOnSurface(e,f,...)`（pcurve）、`BRepTools::UVBounds(f,...)`（域）、`Poly_Triangulation::UVNode(i)`（网格 UV）。

## 3. 难点（周期/封闭是重灾区）

### 3.1 缝边 Seam（封闭面的命脉）
封闭面（柱/球/环/某些 BSpline）有一条**缝**：`u=umin` 与 `u=umax` 在 3D 重合。沿缝的边是**缝边**，它在**同一个面**上有**两条 pcurve**——一条贴 `u=umin`、一条贴 `u=umax`，3D 完全重合、UV 张开成整个周期。
- OCCT：`BRep_Tool::IsClosed(e,f)` 判缝；`CurveOnSurface(e,f,Index=1/2)` 取两条。简单的 `CurveOnSurface(e,f)` 只给一条 → **UV 视图会把缝画塌**。
- 这正是之前你点出的"闭环曲线两端 3D 重合、UV 不重合"。

### 3.2 周期 wrap / unwrap
周期面 `IsUPeriodic()` 的参数按 `UPeriod()` 取模。跨缝的 pcurve 参数可能落在 `[−ε, +ε]` 或 `[2π−ε, 2π+ε]` 两种等价表示，混用会在 UV 里**跳变/越界**。
- 方案：以面的 `UVBounds` 为基准把所有 pcurve/UV 节点 **unwrap 到同一周期窗口**；跨缝的边按缝**切成两段**或复制到两侧。

### 3.3 极点退化 Degeneracy
球/锥顶点：一整条 UV 边界（如 `v=vmax` 一行）塌成一个 3D 点。对应**退化边**（`BRep_Tool::Degenerated`=true，无 3D 曲线、只有 pcurve）。
- 现 §7 边离散**跳过退化边**（无 3D 曲线）——但 UV 视图**必须包含**它们，否则 UV 域边界缺一条。**结论**：UV 路径独立走 pcurve，不复用"跳过退化边"的逻辑。

### 3.4 UV 不连续 / 朝向
- 跨缝的边在 UV 里不连续（需按 3.2 处理）。
- 面 `orientation=REVERSED` 时 UV 朝向翻转；环的 CCW/CW 决定外环/孔。UV 视图要按面朝向统一，否则孔画反。

### 3.5 裁剪 Trimming
面是曲面参数域上**被环裁剪**的区域；`UVBounds` 给的是环的包围盒，不一定等于底层曲面的自然域。控制网/自然域要和裁剪域分开标注（见导出设计 §6.5）。

## 4. 其它内核怎么处理（对照，部分待核实）

> 以下为概念性对照，**具体 API/字段名以各家文档为准**（见 §6 待补清单），不在此杜撰细节。

- **Parasolid**：B-rep 拓扑 body→face→loop→**fin(coedge/半边)**→edge→vertex；**每个 fin 携带该边在所属面参数空间的曲线（SP-curve / parameter-space curve）**。缝边由两个 fin 分居缝两侧，各自一条 SP-curve——和 OCCT"一边两 pcurve"同构。周期面带参数范围与周期标志。
- **ACIS**：`coedge` 上挂 `pcurve`；周期/封闭面同样靠 coedge 分居两侧表达缝。
- **STEP（AP242/AP203）**：`edge_curve` 的 `surface_curve`/`seam_curve` 用 `pcurve` 列表表达"同一 3D 曲线在面参数空间的多条 2D 表示"；缝边正是用多条 `pcurve` 的标准案例。
- **共性**：所有现代内核都用"**半边(coedge/fin) + 参数空间曲线**"表达边-面关系，缝边=同一边的两个半边各带一条参数曲线。OCCT 的"`(edge,face,Index)` 多 pcurve"是同一思想的另一种存储。

> 结论：我们的导出/视图按"**每条边在每个承载面上可有 1~2 条 pcurve**"建模即可，与各大内核一致；缝边显式标 `is_seam` 并带两条 pcurve。

## 5. 处理方案（我们的导出 + 视图）

### 5.1 导出（occ-debug-mesh）
1. 面：导 `UVBounds`、`IsUPeriodic/IsUClosed`+`UPeriod`、三角网格 `UVNode`。
2. 边×面：对每个 `(edge, face)` 取 pcurve；`IsClosed(e,f)` 为真则取 `Index=1,2` 两条，标 `is_seam=true`。
3. 退化边：不跳过，按 pcurve 导（标 `degenerate=true`，3D 为单点）。
4. UV 折线采样：可直接用三角网格 `UVNode`（与 3D 折线天然对应、免费），或对 `Geom2d_Curve` 用 2D `GCPnts` 离散。
5. **unwrap**：以面 `UVBounds` 为窗口，把 pcurve/UV 节点归一到同一周期区间。

### 5.2 视图（UvPanel）
- 画面 UV 矩形域 + 网格；pcurve 折线按边色；缝边两条 pcurve 用同色虚/实区分。
- 跨缝边切两段或两侧复制，避免横穿整图的假线。
- 选中 3D 边/面 → UV 高亮对应 pcurve/域；反向亦然（双向 hover）。
- 退化边在 UV 是正常一条边、在 3D 高亮成一个点（提示"degenerate/pole"）。

### 5.3 验收夹具（离线，照 README §6 风格）
- 圆柱面（`IsUPeriodic`，1 条缝边、2 pcurve）。
- 球面（两个极点退化边 + 缝）。
- 环面（U、V 双周期）。
- 带孔的平面/BSpline 面（内外环朝向）。
> 这些夹具同时验收导出（pcurve/UV 节点正确）与视图（缝不塌、孔不反、极点不丢）。

## 6. 待补参考资料（不杜撰，留待核实/补全）

- Piegl & Tiller, *The NURBS Book*：周期/封闭 B-spline、节点矢量、控制网。
- OCCT 官方文档：Modeling Data（pcurve、SameParameter、周期面）、BRepMesh（UV 节点存储条件）。
- Parasolid 文档：topology（fin/SP-curve）、periodic/closed surfaces 处理。
- STEP AP242：`pcurve`、`seam_curve`、`surface_curve` 表达。
- FreeCAD：拓扑命名 / element mapping（跨快照身份，见导出设计 §6.1）。

## 7. 待确认

- [ ] UV 采样源：优先用三角网格 `UVNode`（与 3D 折线对应）还是 2D pcurve 独立离散？
- [ ] 缝边/退化边在 schema 的标志位（`is_seam`/`degenerate`）与两条 pcurve 的承载结构。
- [ ] unwrap 策略：统一到 `UVBounds` 窗口；跨缝边切段 vs 两侧复制。
- [ ] 先做哪个验收夹具：建议**圆柱（缝）→ 球（极点）→ 环（双周期）**。
