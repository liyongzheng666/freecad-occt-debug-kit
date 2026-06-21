# M2 调研笔记

> 状态：调研中（决策待定）<br>
> 核对日期：2026-06-21<br>
> 适用范围：M2 = 用真 occdbg/Capture + occ-debug-mesh 替掉假生产者、viewer 接 BREP/mesh、FCStd baseline、世界坐标对齐、VS Code 右键、F5 编排（"第一版端到端闭环"）<br>
> 关联：[print-linkage-tech-decisions.md](print-linkage-tech-decisions.md)、[occ-fillet-debug-agent-architecture.md](occ-fillet-debug-agent-architecture.md) §9、[lldb-dynamic-geometry-capture.md](lldb-dynamic-geometry-capture.md)

本笔记汇总 M2 的风险全景、M2-1/2/3 的白话解释与**技术选型候选**、以及 M2-4/5/6/7 的几何域调研。**本笔记不下最终决议**——选型在消化后单独进行。

## 1. M2 风险全景

severity：🔴 架构/正确性阻塞 ｜ 🟠 需在实现中定 ｜ 🟡 打磨 ｜ ⚪ 已知小项

| # | 问题 | 类别 | severity |
| --- | --- | --- | --- |
| M2-1 | renderer 同步、mesh 资产异步，模型塞不进 | 前端架构 | 🔴 |
| M2-2 | `add` 引用的 print-mesh 异步产出 → 取资产 404 竞态 | 协议时序 | 🔴 |
| M2-3 | occ-debug-mesh 由谁/何时触发未设计 | 编排 | 🟠 |
| M2-4 | 世界坐标对齐 / 双重 Location | 几何正确性 | 🔴 |
| M2-5 | print-mesh 的 face_id/edge_id 命名须与 topology_ref 对齐 | 几何身份 | 🟠 |
| M2-6 | local_origin 策略未定（Float32 远原点抖动） | 精度 | 🟠 |
| M2-7 | 三角化 deflection 参数未定 | 网格质量 | 🟡 |
| M2-8 | 真 occdbg 须复刻假生产者契约（原子写/reset/baseline/schema） | 生产端一致性 | 🟠 |
| M2-9 | set_visibility/highlight/focus/note 等 op 未被真实生产者驱动过 | 协议覆盖 | 🟠 |
| M2-10 | occ-debug-mesh 构建接入（链本地 OCCT、bootstrap、版本绑定） | 基建 | 🟡 |
| M2-11 | 大 mesh 资产：Bridge 整文件读内存、无 Range、viewer 无 sha256 缓存 | 性能 | 🟡 |
| D1 | StrictMode 双连诊断噪声 | viewer 健壮性 | ⚪ |
| D3 | 重连无退避/终态 | viewer 健壮性 | ⚪ |
| D4 | NaN/Inf 坐标不校验 | viewer 健壮性 | ⚪ |

## 2. M2-1/2/3：白话解释

这三个**不是几何问题，是"时间与进程边界"问题**——网络延迟、文件还没生成、活该谁干。假生产者没碰到，是因为它只发"内联几何"（点/线/盒，数值直接写在事件里），不需文件、不需网格化。

### 2.1 M2-1 渲染函数是"同步"的，网格要"异步"取
viewer 现在画对象的函数像**纯函数**：给点/线/盒，当场就地建好——像直接读 `gp_Pnt` 字段，零等待。但一个 `Shape` 的三角网格是 Bridge 上一个**单独的文件**（`/assets/xxx.mesh.json`），要画它得先**下载+解析**——花时间、可能失败，像"读结构体字段" vs "得先 `fopen` 把 BREP 从磁盘读进来"。现在这台画图机器假设一切瞬时；一旦某对象要"先下载再建"，要么卡住、要么得换套路：**先放占位符 → 后台下载 → 完成后替换**。这套替换机制现在没有。

### 2.2 M2-2 事件引用的网格文件，异步才生成 → 可能 404
事件像工单："渲染这个 shape，网格在文件 X 里。"但 X（print-mesh）是 occdbg 倒出 BREP **之后**才网格化生成的，于是工单可能**先于 X 到达** viewer → viewer 要 X → "404"。如同"先把写着'见附件'的邮件发了，附件还没做完"。

### 2.3 M2-3 谁来跑网格化、什么时候跑
已定"kit 产网格、Bridge 不碰"，但**触发机制空白**。occdbg 蹲在断点里（被调试进程冻住）倒出 BREP 后，得有东西去跑 occ-debug-mesh。在**冻住的被调试进程里**直接跑，像在信号处理器里做重活——脆弱、不安全。

## 3. M2-1/2/3 技术选型候选（提前预览，未决）

> 三者**互相耦合**，§3.4 给出一个自洽的推荐组合。

### 3.1 M2-1 异步渲染如何落地

| 选项 | 做法 | 代价 | 取舍 |
| --- | --- | --- | --- |
| **A 异步 renderer + 占位替换**（推荐） | `EntityRenderer` 允许返回 Object3D（同步）或 loader（异步）；`SceneController` 先放占位（如事件自带 bbox），fetch 完成再换上真网格 | 改 renderer 接口 + sync() 容忍"未就绪" | 改动**局部化**，内联几何仍走同步，单一渲染管线 |
| B 资产预解析层 | 在事件进 store **之前**由加载层 fetch+解析，store 里实体直接带网格数据；SceneController 全同步 | store 持重网格 buffer；SSE 与 store 间加异步中间件 | sync 干净，但 store 变重、内存压力 |
| C React 组件单独渲染 mesh | asset 实体走 registry 之外的 React 组件用 useEffect 加载 | 渲染分裂成两套系统 | 不一致、难维护 |

**推荐 A**：把异步只局限在"资产几何"，内联几何零改动，渲染管线仍只有一条。

### 3.2 M2-2 如何避免 404 竞态

| 选项 | 做法 | 代价 | 取舍 |
| --- | --- | --- | --- |
| A 生产端 mesh-before-emit | kit 先网格化、**再**发引用 ready 资产的 add | 采集延迟（要等网格化） | 最简单正确，但拖慢采集 |
| **B 两段式：add(BREP/占位) → update(print-mesh)**（推荐） | occdbg 先发 add（带 BREP 或占位），网格化好后由守护进程**追加 update** 换上 print-mesh | viewer 要处理"资产升级" | 不拖采集、无 404；与 M2-3 守护进程天然组合 |
| C viewer 对 404 退避重试 | add 直接带 print-mesh 路径，viewer 取不到就退避重试 | 轮询、时序脆弱、可能"永远 loading" | 最少协议改动，但最脆 |

**推荐 B**：occdbg 立即发 add（先给占位/BREP），网格化守护进程产出 print-mesh 后**追加一条 `update` 事件**把资产换上——viewer 占位→升级，全程无 404。

### 3.3 M2-3 网格化在哪跑

| 选项 | 做法 | 代价 | 取舍 |
| --- | --- | --- | --- |
| **A 独立 kit 守护进程 watch assets/**（推荐） | 单独进程盯 `assets/*.brep`，落地即网格化写 `.mesh.json`，并追加 update 事件 | 多一个常驻进程 | 与调试器完全解耦，契合"kit 产、Print 消费" |
| B occdbg 同步 shell out | occdbg 每次采集在调试器会话里 spawn occ-debug-mesh | 在冻住的被调试进程附近跑重活，风险高 | 接线简单但脆弱 |
| C Bridge 端网格化 | （已否决）破坏 Print 纯消费边界 | — | 仅列此存档 |

**推荐 A**：独立守护进程，既不碰被调试进程，又能顺手承担 M2-2 的 update 追加。

### 3.4 三者的推荐组合（自洽设计）

```text
occdbg(断点内) ──写 BREP 资产──┐
        └──发 add 事件(占位/引用 BREP, M2-2 B)──► events.ndjson
                                                   ▲
kit 网格化守护进程(M2-3 A) ── watch assets/*.brep ─┤
        ├── occ-debug-mesh: BREP → print-mesh(per-face, 世界坐标)
        └── 追加 update 事件(把资产换成 print-mesh, M2-2 B)
                                                   │
viewer(M2-1 A): add 时显示占位 ──收到 update──► fetch print-mesh ──► 替换为真网格
```

一句话：**occdbg 只管"发现并发事件"，守护进程管"网格化 + 通知升级"，viewer 管"占位 + 异步换上"**——三个进程各司其职、无 404、不拖调试器。

## 4. M2-4/5/6/7：几何域调研

### 4.1 M2-4 Location / 世界坐标
- 形状靠 **`TopLoc_Location`**（链接坐标系链）定位。两种移动本质不同：
  - `TopoDS_Shape::Located/Moved(loc)`：**同一 TShape**，只挂/叠加 Location，不复制几何；
  - `BRepBuilderAPI_Transform`：把变换**烘焙进新 TShape**（几何真动）。
- **要命点**：`TopExp_Explorer` / `TopoDS_Iterator` **默认累积父级 Location**——从带 Location 的 compound explore 出的子面已带**组合后全局变换**；但直接抓顶层 `myShape` 要自己看 `myShape.Location()` 判断局部/带 placement。
- **结论**：`Poly_Triangulation` 节点存**面的局部坐标**；变世界要**读取时应用累积 Location**（法线只乘旋转部分，按 `REVERSED` 翻向）。**漏乘=错位，乘两次=双重 placement**。建议：每资产定标志"坐标是否已 bake 到世界"，occ-debug-mesh 统一**输出世界坐标**。
- FreeCAD：`Placement` ↔ `TopLoc_Location`；嵌套 App::Part/Body/Link 逐层相乘求全局。

### 4.2 M2-5 face/edge 身份
- `TopExp::MapShapes(shape, TopAbs_FACE, map)` → **`TopTools_IndexedMapOfShape`**，**1 起整数索引**，按 TShape+朝向去重（共享边只出现一次），`FindIndex/FindKey` 双向。
- **稳定性**：仅在**该 shape 快照内**确定；跨编辑/重建会变（FreeCAD 拓扑命名另解）。**单次 run 内够用**。
- **用法**：`face_id="F"+索引`、`edge_id="E"+索引`，**同一张 map** 同时驱动 print-mesh 分组与事件 `topology_ref` → 天然对齐；跨引用 FreeCAD 元素另带 `mapped_element`。
- ⚠️ MapShapes 复用同 map 会累积，每 shape 用新 map / 先 Clear。
- **利好**：OCCT 三角化本就**每面一份** `Poly_Triangulation`，与 §4 "per-face 子网格"完美对上；边用 `Poly_PolygonOnTriangulation` 或 `BRepAdaptor_Curve + GCPnts_UniformDeflection` 离散为 polyline。

### 4.3 M2-6 local_origin / 精度
- three.js GPU 是 **Float32**；~4×10⁸ 时最小步进已达 64，远原点装配/场地坐标会抖。
- 业界解法 **floating origin / relative-to-center（RTC）**：相机留原点附近、几何相对本地原点表达；CesiumJS 用 RTC + 高低位双 float32 模拟 double。
- **够用的简化**：**一个会话级全局 `local_origin`**（如 baseline 包围盒中心），所有 double 减去它再降 Float32，整场景贴原点；仅单资产自身跨度巨大才需 per-object 框架。建议：**一个 session 原点**（非每资产各一），记进 manifest，viewer 仅读数显示时加回。

### 4.4 M2-7 deflection
- `BRepMesh_IncrementalMesh(shape, linDefl, isRelative, angDefl, parallel)`。
- **线性挠度**=弦高误差，**主导视觉质量**；**角度挠度**=相邻段夹角，**通常 0.2–0.8 rad**，**<0.2 可能卡死/无限细分**。
- **`isRelative=true`**：线性挠度按**边长缩放**，混合尺度形状得成比例三角化——好默认。
- **建议**：相对挠度（或 linDefl ≈ 0.001–0.01 × 包围盒对角）+ 角度 ≈0.5 rad，钳住角度 ≥0.2；已有三角化 IncrementalMesh 会复用。调试求"快且认得出"，非"生产级光顺"。

## 5. 参考资料

**Location / 变换**
- [Move TopoDS_Shape to global position](https://dev.opencascade.org/content/move-topodsshape-global-position)
- [BRepBuilderAPI_Transform vs Location](https://dev.opencascade.org/content/topodsshape-and-brepbuilderapitransform)
- [Transformations in OCCT (Unlimited3D)](https://unlimited3d.wordpress.com/2021/03/28/transformations-in-occt/)
- [OCCT Coordinate Systems Wiki](http://opencascade.wikidot.com/coordinate-systems)

**拓扑遍历 / 身份**
- [TopExp Class Reference (官方)](https://dev.opencascade.org/doc/refman/html/class_top_exp.html)
- [Iterate edges in TopoDS_Face (TechOverflow)](https://techoverflow.net/2019/06/13/how-to-iterate-all-edges-in-topods_face-using-opencascade/)
- [On the orientation of shapes](http://myopencascade.blogspot.com/2010/03/on-orientation-of-shapes.html)

**精度 / 大坐标**
- [Precision-Safe Rendering of Large-Coordinate CAD in Three.js (Medium)](https://medium.com/@mlightcad/precision-safe-rendering-of-large-coordinate-cad-drawings-in-three-js-c49c299b3afc)
- [three.js forum: Large coordinates](https://discourse.threejs.org/t/large-coordinates/50621)
- [three.js forum: Camera and floating point origin](https://discourse.threejs.org/t/camera-and-floating-point-origin/51486)

**网格化**
- [OCCT Mesh User Guide](https://dev.opencascade.org/doc/overview/html/occt_user_guides__mesh.html)
- [BRepMesh_IncrementalMesh Reference](https://dev.opencascade.org/doc/refman/html/class_b_rep_mesh___incremental_mesh.html)
- [BRepMesh intro (Unlimited3D)](https://unlimited3d.wordpress.com/2024/03/17/brepmesh-intro/)

## 6. 待决策清单（下次技术选型的输入）

- [ ] M2-1：渲染异步化方案（推荐 A 异步 renderer + 占位替换）
- [ ] M2-2：404 竞态方案（推荐 B 两段式 add→update）
- [ ] M2-3：网格化编排（推荐 A 独立守护进程）
- [ ] M2-4：世界坐标契约（每资产"已 bake"标志 + occ-debug-mesh 输出世界坐标）
- [ ] M2-5：face/edge 命名（TopExp::MapShapes 索引，print-mesh 与 topology_ref 共用）
- [ ] M2-6：local_origin（会话级单一原点，记 manifest）
- [ ] M2-7：deflection（相对挠度 + 角度≈0.5、钳 ≥0.2）
