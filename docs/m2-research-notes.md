<!-- # M2 调研笔记 -->

> 状态：调研中（决策待定）<br>
> 核对日期：2026-06-21<br>
> 适用范围：M2 = 用真 occdbg/Capture + occ-debug-mesh 替掉假生产者、viewer 接 BREP/mesh、FCStd baseline、世界坐标对齐、VS Code 右键、F5 编排（"第一版端到端闭环"）<br>
> 关联：[print-linkage-tech-decisions.md](print-linkage-tech-decisions.md)、[occ-fillet-debug-agent-architecture.md](occ-fillet-debug-agent-architecture.md) §9、[lldb-dynamic-geometry-capture.md](lldb-dynamic-geometry-capture.md)

本笔记汇总 M2 的风险全景、M2-1/2/3 的白话解释与**技术选型候选**、以及 M2-4/5/6/7 的几何域调研。**本笔记不下最终决议**——选型在消化后单独进行。

## 0. 先例：OCCT DRAW Test Harness（同类工具 + 可复用清单）

> DRAW 是 OCCT 官方自带、内核开发者调几何 bug 的标准工具。它**印证了本项目的方向**，且有大量可直接复用之处。本节是设计依据的背景记录。

### 0.1 它是什么

TCL 命令行 + X11/OpenGL 3D 窗口，全靠打字。典型会话：

```tcl
DRAWEXE ; pload MODELING
box b 10 20 30                  # 造盒子（自动显示）
blend r b 2 ...                 # 半径 2 倒圆角
vinit; vdisplay r; vfit; vaxo   # 显示
checkshape r                    # 体检：报哪里不合法
bopcheck r                      # 布尔/干涉检查
save r r.brep ; restore r.brep r2
```

### 0.2 关键招式：断点处抓中间几何（与 occdbg 同源）

停在 lldb/gdb、手里有 `TopoDS_Shape` 时直接调：

```cpp
BRepTools_Write("/tmp/bad.brep", &myShape)   // 存 BREP
DBRep_Set("bad", &myShape)                   // 塞进 DRAW 变量
Draw_Eval("donly bad; axo; fit")             // 画出来
```

这正是 `occdbg shape ... -- myShape` 的"祖宗"——不改源码、不重编译，在断点处看中间态。我们把它产品化：自动存 BREP、推浏览器、带分组/坐标/拓扑/源码上下文。

### 0.3 为什么不直接用 DRAW

| 维度 | OCCT DRAW | 本项目 Print |
| --- | --- | --- |
| 界面 | TCL 打字 + X11 老视图 | 浏览器 web，鼠标交互 |
| 场景 | 一次一个快照、手动重敲 | 增量会话（add/update/clear 流式） |
| 上下文 | 只有裸几何 | FreeCAD 对象/element + 源码位置 + 分组 |
| 失败诊断 | `checkshape`/`bopcheck` 纯文字 | 缺陷配色高亮叠在几何上（V2 升级） |
| 给谁用 | 单个内核开发者 | 人 + Agent（结构化 NDJSON、右键发送） |
| 复现/协作 | 难 | 会话可存/回放/分享 |

### 0.4 优秀 / 可借鉴 / 可复用清单（本节重点）

| DRAW 能力 | 背后机制 | 我们如何复用 / 借鉴 |
| --- | --- | --- |
| 断点存几何 | `BRepTools_Write` / `DBRep_Set` / `Draw_Eval` | occdbg C ABI（`OccDebug_EmitShape` 等）照此三步设计；BREP 直接复用 `BRepTools::Write` |
| `checkshape` | `BRepCheck_Analyzer`（按子形状报缺陷码） | **V2 缺陷诊断层的现成引擎**，直接调、不重造 |
| `bopcheck` | `BRepAlgoAPI_Check` | 自交/干涉缺陷检测复用 |
| `save`/`restore .brep` | BREP 为权威交换格式 | 印证"BREP 权威、mesh 仅派生"的决策 |
| `explode` + 子形状索引名（`b_1,b_2`） | `TopExp` 子形状编号 | **M2-5 的 face_id/edge_id 同源**（MapShapes 索引） |
| `donly` / `fit` | 只显示这个 / 铺满 | 已对应我们的 **Solo / Focus** |
| `nbshapes` / `whatis` / `dump` | 计数 / 类型 / 属性转储 | Inspector 的信息项来源 |
| TCL 脚本可回放 | 命令序列即脚本 | 会话回放 + **Agent 断点自动采集（batch）** |

### 0.5 不复用什么（反面参照）

TCL/X11 古老 UX、单快照模型、纯文字诊断、零上下文、单用户——这些正是我们用 web + 增量会话 + 配色诊断 + FreeCAD 上下文 + Agent 协议要**超越**的点。

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
| M2-12 | events.ndjson **多写者并发**（occdbg + Capture-in-debuggee + daemon），同 run_id 的 seq 无单一权威 | 生产端并发 | 🔴 |
| M2-13 | occ-debug-mesh 必须网格化**坏/开放/自交 shape**（M2 输入常是失败几何）而不卡死 | 网格鲁棒性 | 🔴 |
| M2-14 | 裸 `Edge`/`Wire`/`Vertex` 输入（fillet 输入本就是边）以面为中心的 mesher 产不出 | 输入覆盖 | 🟠 |
| M2-15 | 缺**子面/子边选择**模型——store 只有实体级 `selectedId` | viewer 选择 | 🟠 |
| M2-16 | mesh-ready `update` 对**已被 remove/clear 的实体**竞态 | 时序 | 🟠 |
| M2-17 | `occdbg surfdata`(ChFiDS) 需 TKFillet 适配器，与 capture 禁链 TKFillet 冲突 | 范围划分 | 🟡 |

## 2. M2-1/2/3：白话解释

这三个**不是几何问题，是"时间与进程边界"问题**——网络延迟、文件还没生成、活该谁干。假生产者没碰到，是因为它只发"内联几何"（点/线/盒，数值直接写在事件里），不需文件、不需网格化。

### 2.1 M2-1 渲染函数是"同步"的，网格要"异步"取
viewer 现在画对象的函数像**纯函数**：给点/线/盒，当场就地建好——像直接读 `gp_Pnt` 字段，零等待。但一个 `Shape` 的三角网格是 Bridge 上一个**单独的文件**（`/assets/xxx.mesh.json`），要画它得先**下载+解析**——花时间、可能失败，像"读结构体字段" vs "得先 `fopen` 把 BREP 从磁盘读进来"。现在这台画图机器假设一切瞬时；一旦某对象要"先下载再建"，要么卡住、要么得换套路：**先放占位符 → 后台下载 → 完成后替换**。这套替换机制现在没有。

### 2.2 M2-2 事件引用的网格文件，异步才生成 → 可能 404
事件像工单："渲染这个 shape，网格在文件 X 里。"但 X（print-mesh）是 occdbg 倒出 BREP **之后**才网格化生成的，于是工单可能**先于 X 到达** viewer → viewer 要 X → "404"。如同"先把写着'见附件'的邮件发了，附件还没做完"。

### 2.3 M2-3 谁来跑网格化、什么时候跑
已定"kit 产网格、Bridge 不碰"，但**触发机制空白**。occdbg 蹲在断点里（被调试进程冻住）倒出 BREP 后，得有东西去跑 occ-debug-mesh。在**冻住的被调试进程里**直接跑，像在信号处理器里做重活——脆弱、不安全。

## 3. M2-1/2/3 技术选型（✅ 已敲定 2026-06-22）

> **最终方案（自洽组合）**：M2-1 = **A 异步 renderer + 占位替换**；M2-2 = **B 两段式 add→update**；M2-3 = **A 独立守护进程 watch assets/**。
> 咬合关系：独立守护进程网格化 → 完成后追加 update → viewer 把占位替换为真网格。下列各表保留候选与代价供回溯。

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

**DRAW / 调试工具与缺陷检查**
- [OCCT DRAW Test Harness 用户指南](https://dev.opencascade.org/doc/overview/html/occt_user_guides__test_harness.html)
- [OCCT Debugging tools & hints（断点存中间对象）](https://dev.opencascade.org/doc/overview/html/occt__debug.html)
- [BRepCheck_Analyzer 参考](https://dev.opencascade.org/doc/refman/html/class_b_rep_check___analyzer.html)
- [BRepAlgoAPI_Check (bopcheck)](https://dev.opencascade.org/doc/refman/html/class_b_rep_algo_a_p_i___check.html)
- [ChFi3d_Builder（圆角失败状态）](https://dev.opencascade.org/doc/refman/html/class_ch_fi3d___builder.html)

## 6. 待决策清单（下次技术选型的输入）

- [x] M2-1：**异步 renderer + 占位替换**（✅ 敲定 2026-06-22）
- [x] M2-2：**两段式 add→update**（✅ 敲定 2026-06-22）
- [x] M2-3：**独立守护进程 watch assets/**（✅ 敲定 2026-06-22）
- [ ] M2-4：世界坐标契约（occ-debug-mesh 输出世界 double，Location 累积已应用、镜像翻绕序）
- [ ] M2-5：face/edge 命名（TopExp::MapShapes 索引，print-mesh 与 topology_ref 共用）
- [ ] M2-6：local_origin（会话级单一原点，记 manifest，viewer 降 Float32 前减）
- [ ] M2-7：deflection（相对挠度 + 角度≈0.5、钳 ≥0.2）
- [ ] M2-12：seq 权威——daemon 的 update 用**独立 run_id 命名空间**（`run-NNNN/mesh`）解耦
- [ ] M2-13：mesher 鲁棒性——每面 try/catch + 超时看门狗 + `partial`/`failed_faces` 标记
- [ ] M2-14：按顶层类型分派（Face/Shell/Solid→面网格；Edge/Wire→edges；Vertex→点）
- [ ] M2-15：store 增 `selectedFaceId`/`selectedEdgeId`，拾取与 Inspector 接子面
- [ ] M2-16：reducer 容忍"update 不存在 id"降级为低级诊断（mesh-ready 竞态）
- [ ] M2-17：surfdata 划入 M3；M2 的 occdbg 命令集不含 surfdata
- [ ] §9 缺陷诊断层：M2 落 BRepCheck 几何缺陷（`defect` kind + 配色高亮 + 缺陷面板）；ChFi3d 算法状态留 M3

## 7. 实施清单（修订版，已并入 §8 漏洞修复）

`新`=新建 `改`=修改。**🆕** 标记为深挖漏洞后新增/修正的条目。

### A. KIT — 生产端 C++

| 文件 | 新/改 | 内容 |
| --- | --- | --- |
| `tools/occ-debug-capture/{CMakeLists,include/OccDebugCApi.h,src/*}` | 新 | C ABI（EmitPoint/Curve/Shape/Clear/LastError）+ NDJSON SessionWriter + BREP 导出；只链低层 OCCT、**禁链 TKFillet** |
| `tools/occ-debug-mesh/CMakeLists.txt` | 新 | 链本地 OCCT 网格 toolkit；指向 `occt/install/debug` |
| `tools/occ-debug-mesh/src/Mesher.cxx` | 新 | `BRepMesh_IncrementalMesh`(相对挠度,角≈0.5,钳≥0.2)；`TopExp::MapShapes` 出 id；读 `Poly_Triangulation` **应用累积 Location→世界 double**；法线+`REVERSED`+镜像翻绕序 🆕 |
| `tools/occ-debug-mesh/src/ShapeDispatch.cxx` | 新 🆕 | **按顶层类型分派**：Face/Shell/Solid→面网格；Edge/Wire→edges；Vertex→点（M2-14） |
| `tools/occ-debug-mesh/src/Robust.cxx` | 新 🆕 | **每面 try/catch + 超时看门狗**，跳过不可网格化面并写 `partial`/`failed_faces`（M2-13） |
| `tools/occ-debug-mesh/src/PrintMeshJson.cxx` | 新 | 序列化 per-face + edges；**世界 double、无 per-asset origin**；算 `sha256` 🆕 |

### B. KIT — 生产端编排（Python/Shell）

| 文件 | 新/改 | 内容 |
| --- | --- | --- |
| `scripts/lldb_occ_debug.py` | 新 | `occdbg` 命令族（**不含 surfdata**，划 M3 🆕）；简单值 SBValue→NDJSON、复杂走 Capture C ABI |
| `scripts/occ-mesh-daemon.py` | 新 | watch `assets/*.brep`→调 `$OCC_DEBUG_MESH_BIN` 🆕→写 `.mesh.json`→**追加 update 事件（独立 run_id 命名空间 `run-NNNN/mesh`）** 🆕；幂等跳过已网格化 🆕 |
| `scripts/export-fcstd-baseline.py` | 新 | FreeCADCmd 算全局 Placement、导 baseline BREP + 写 manifest（`local_origin`/freecad_revision/occt_revision） |
| `scripts/validate-events.py` | 新 | 用 Print `protocol/*.schema.json` 校验产出（M2-8/H3） |
| `scripts/occ-debug-start.sh` | 新 | F5 编排 + **就绪顺序**：建 session→起 daemon→跑 baseline→lldb 拉 FreeCAD 🆕 |
| `scripts/bootstrap.sh` | 改 | 增两个 C++ 工具的构建步骤（M2-10） |

### C. PRINT — 协议

| 文件 | 新/改 | 内容 |
| --- | --- | --- |
| `protocol/print-mesh.schema.json` | 新 | 正式化 §4（faces/edges/`partial`/`failed_faces`，**无 per-asset origin** 🆕）；`asset.path` 相对 assets/ 契约 🆕 |
| `protocol/session.schema.json` | 改 | manifest 增 `local_origin` |
| `protocol/event.schema.json` | 改 🆕 | `update` 对不存在 id 由消费端降级（M2-16，文档约定） |

### D. PRINT — viewer 渲染层

| 文件 | 新/改 | 内容 |
| --- | --- | --- |
| `viewer/src/rendering/RendererRegistry.ts` | 改 | 异步 renderer 接口（返回 `Object3D \| Promise`） |
| `viewer/src/rendering/SceneController.ts` | 改 | 占位→替换；pending 取消；mesh dispose；**按 face_id/edge_id 拾取到子对象** 🆕 |
| `viewer/src/rendering/renderers/meshRenderer.ts` | 新 | 取 `/assets/<print-mesh>`→每面 BufferGeometry(Uint32 🆕)+边 LineSegments；**减会话 `local_origin`** 🆕；`DoubleSide`(开放壳) 🆕；tag face_id |
| `viewer/src/rendering/assets/assetCache.ts` | 新 | 按 path/sha256 缓存去重；404 退避兜底 |

### E. PRINT — viewer 状态/会话/UI

| 文件 | 新/改 | 内容 |
| --- | --- | --- |
| `viewer/src/core/protocol/types.ts` | 改 | print-mesh/asset 类型、`local_origin` |
| `viewer/src/core/session/sessionStore.ts` | 新 | 会话元信息（`local_origin`/unit），供 renderer 偏移 |
| `viewer/src/core/scene-store/store.ts` | 改 🆕 | 增 `selectedFaceId`/`selectedEdgeId` 子选择（M2-15）；`reduceScene` update-miss 降级 🆕 |
| `viewer/src/core/bridge/useBridgeStream.ts` | 改 | 拉 manifest 取 `local_origin` |
| `viewer/src/features/inspector/Inspector.tsx` | 改 | 显示选中 face/edge 的 topology_ref + 资产状态（加载中/已加载/404/partial 🆕） |
| `viewer/src/features/viewport/Viewport3D.tsx` | 改 | 资产几何 NaN/Inf 兜底（D4） |
| `viewer/src/core/bridge/sseClient.ts` | 改 | 重连退避+终态（D3）、StrictMode 抑制（D1） |

### F. PRINT — Bridge

| 文件 | 新/改 | 内容 |
| --- | --- | --- |
| `bridge/bridge.py` | 改 | `/session` 返回 manifest；大资产 `Range`/流式；`.mesh.json` mime |

### 实施顺序（5 阶段，可独立验收）

1. **协议先行**：print-mesh.schema + types + session `local_origin`。
2. **occ-debug-mesh（C++）**：含分派/鲁棒/世界坐标——用静态 BREP（含**故意坏的** 🆕）离线验收，不依赖 LLDB。
3. **viewer 异步渲染 + 子面选择**：喂阶段 2 样例资产，浏览器看 shape/face、点选面。
4. **占位→升级链路**：daemon（独立 run_id 命名空间）追加 update + viewer 升级。
5. **真采集**：occdbg + baseline + F5 + bootstrap，替掉假生产者。

> 地基仍是**阶段 2**，且新增"**坏 shape 测试夹具**"作为它的核心验收项。

## 8. 深挖的漏洞与修复

severity：🔴 阻塞 ｜ 🟠 重要 ｜ 🟡 次要。下表为本轮 review 对 §7 清单与相关文档的修补。

| # | 漏洞 | 原清单的问题 | 修复 | 落点 |
| --- | --- | --- | --- | --- |
| 🔴 V1 | **多写者 seq 权威**（M2-12） | events.ndjson 被 occdbg/Capture/daemon 三家追加，同 run_id 的 seq 无法各自独立单调 | daemon 的 update 用**独立 run_id 命名空间 `run-NNNN/mesh`**，reducer 各自跟踪 lastSeqByRun、update 仍按 id 命中——免跨进程 seq 锁 | occ-mesh-daemon.py / reducer |
| 🔴 V2 | **坏 shape 网格化**（M2-13） | M2 输入常是 fillet 失败的非法/开放/自交 shape，BRepMesh 可能卡死/崩 | 每面 try/catch + **超时看门狗** + 跳过并标 `partial`/`failed_faces` | occ-debug-mesh Robust.cxx；print-mesh schema |
| 🔴 V3 | **§4 origin 自相矛盾** | linkage §4 写 per-asset `local_origin`，M2-6 又定会话级单一 origin | print-mesh **世界 double、无 per-asset origin**；唯一 origin 在 manifest，viewer 降 Float32 前减一次；occ-debug-mesh 不再需要 origin | linkage §4（已改）/ M2-6 |
| 🔴 V4 | **裸 Edge/Wire 输入**（M2-14） | fillet 输入本就是边，以面为中心的 mesher 产不出 | 按顶层类型分派：Edge/Wire→edges、Vertex→点 | occ-debug-mesh ShapeDispatch.cxx |
| 🟠 V5 | **缺子面选择**（M2-15） | M2-5 选面是核心价值，但 store 只有实体级 `selectedId` | store 增 `selectedFaceId`/`selectedEdgeId`，拾取/Inspector 接子面 | store / SceneController / Inspector |
| 🟠 V6 | **update vs remove 竞态**（M2-16） | daemon 网格化耗时，期间实体可能被 remove/clear → update 命中空 | reducer 把"update 不存在 id"降为低级诊断（已有诊断，仅调级别） | reducer / event 文档约定 |
| 🟠 V7 | **asset.path 契约缺失** | 路径相对谁、是否带前导 / 未定 | 相对 `<session>/assets/`、无前导 `/`、映射 `/assets/<path>`；sha256 由 mesher 算 | linkage §4（已补）/ print-mesh schema |
| 🟠 V8 | **daemon 找不到 mesher** | 守护进程怎么定位 occ-debug-mesh 二进制 | env `OCC_DEBUG_MESH_BIN`（默认指向构建输出） | occ-mesh-daemon.py / bootstrap |
| 🟡 V9 | **开放壳/镜像渲染** | 开放壳背面不可见、镜像 Location 绕序错 | mesher 镜像翻绕序；meshRenderer 面材质 `DoubleSide` | occ-debug-mesh / meshRenderer |
| 🟡 V10 | **surfdata 范围越界**（M2-17） | occdbg 命令集列了 surfdata，但它需 TKFillet 适配器、与 capture 禁链冲突 | surfdata 明确**划入 M3**，M2 不含 | lldb 文档 / occdbg 命令集 |

## 9. 缺陷诊断层（V2 升级：从"别崩"到"诊断"）

> 把"坏几何"从健壮性负担升级为**一等诊断特性**——从坏的形态 + 算法自报状态反推病因。复用基础见 §0.4（DRAW `checkshape`/`bopcheck`）。

### 9.1 双源融合

两路诊断叠在同一场景：

1. **几何缺陷**：对抓到的 shape 跑 `BRepCheck_Analyzer`（= DRAW `checkshape`），按子形状取缺陷码（自交/非闭合/退化/pcurve 错…）；自交/干涉再用 `BRepAlgoAPI_Check`（= `bopcheck`）。
2. **算法失败状态**：对 fillet 读 `ChFi3d_Builder` 的 `WalkingFailure`/`TwistedSurface` + 失败的 contour/vertex。

→ 融合后高亮在几何上，工程师看一眼"形 + 因"即可反推。

### 9.2 协议：`defect` 标记

新增几何 kind `defect`（加入 enum）。一个 defect 实体：

```jsonc
{
  "op": "add", "kind": "defect",
  "id": "fillet/defect/self-intersection-1",
  "group": "fillet/defects",
  "geometry": { "position": [x, y, z] },   // 或 polyline(坏边) / 省略(仅 ref 子形状)
  "defect": {
    "category": "self_intersection",        // self_intersection|open_boundary|twisted_surface|degenerate|non_manifold|invalid_pcurve|walking_failure
    "source": "brepcheck",                  // brepcheck|bopcheck|chfi3d
    "status": "BRepCheck_SelfIntersectingWire",  // 原始状态码
    "severity": "error",                    // error|warning
    "message": "wire 自交于该点",
    "ref": { "entity_id": "...", "face_id": "F3", "edge_id": "E7" }  // 可选：指向坏子形状
  }
}
```

- defect 走现有 add/update/remove 管线（复用 Solo/Focus/Inspector）。
- viewer 按 `category` 配色：自交=红、开口=橙、扭曲=紫、退化=黄、非流形=品红、走线失败=× 标记。

### 9.3 生产端

- occ-debug-mesh/capture：抓 shape 后跑 `BRepCheck_Analyzer`，遍历缺陷子形状 → 发 defect 事件（带 face_id/edge_id ref）。`BRepCheck` 在低层 `TKTopAlgo`，**不碰 TKFillet**。
- occdbg fillet 钩子（M3）：读 ChFi3d 失败状态 + 失败 contour/vertex → 发 defect 事件。
- BRepCheck 对垃圾 shape 自身可能慢/抛 → 同 V2 的 try/catch + 超时包裹。

### 9.4 viewer

缺陷配色表 + 图例；新"缺陷"面板列出本会话 defects，点击 focus + 高亮 ref 子形状；Inspector 显示 category/source/status/message。

### 9.5 落地（在 §7 之上增量）

| 文件 | 新/改 | 内容 |
| --- | --- | --- |
| `protocol/event.schema.json` | 改 | kind 加 `defect`、$defs 加 `defect` 块 |
| `tools/occ-debug-mesh/src/Diagnose.cxx` | 新 | `BRepCheck_Analyzer` 遍历 → defect 事件（链 `TKTopAlgo`） |
| `viewer/src/rendering/renderers/defectRenderer.ts` | 新 | 按 category 配色标记 |
| `viewer/src/features/defects/DefectPanel.tsx` | 新 | 缺陷列表 + 点击 focus/高亮 |
| `viewer/src/core/scene-store/store.ts` | 改 | defect 选择/高亮 ref 子形状 |

### 9.6 分期

- **M2**：BRepCheck 几何缺陷（自交/开口/退化/非流形）+ 配色高亮 + 缺陷面板——不依赖 TKFillet，先落。
- **M3**：ChFi3d 算法状态（WalkingFailure/TwistedSurface + 失败 contour）——需 TKFillet 适配层（接 M2-17/surfdata）。

## 10. 锁定 M2-1/2/3 后的二次排查（N1–N8）

> 对已敲定的 A/B/A 组合再排查一轮。结论：**无新增阻塞阶段 1-2 的问题**；N1–N8 全部落在阶段 3-5，已记录为契约/任务。

| # | 问题 | 影响阶段 | 修复 / 契约 |
| --- | --- | --- | --- |
| ✅ N1 | `SceneController.sync` 每次 store 变化都**无条件重建对象** → mesh 会被反复重下 | 3 | **已定**：sync 按 `signature=JSON(kind/geometry/asset/style)` 增量重建，未变跳过；**可见性改 `.visible` 开关**（Viewport3D 传全部实体+可见集，不预过滤）→ 隐藏不重下；assetCache 按 sha256 兜底。无残留隐患 |
| ✅ N2 | daemon 不知道 `.brep` 属于哪个实体 → 发不出正确 update | 4 | **已定**：occdbg 写 sidecar `<x>.meta.json`（`{entity_id,run_id,group,brep,mesh}`）后**原子 rename** `<x>.brep.tmp→<x>.brep`；daemon 只听 `*.brep`、读 sidecar 定目标。不用文件名当 id（免碰撞/读半成品竞态） |
| ✅ N3 | 占位需 bbox：viewer **画不了 occt-brep**，add 必须带世界坐标 bbox | 协议/2/5 | **已定**：shape 全程 `kind:"shape"`，add 带 `Bnd_Box` 世界 bbox；renderer 有 print-mesh 画网格、否则画 bbox（顺带做 N6 网格化全败的永久兜底） |
| 🟠 N4 | 多写者**字节交错**：occdbg+daemon 并发 append，POSIX 仅对 <PIPE_BUF(~4KB) 的 O_APPEND 写保证原子，超长行可能交错损坏 | 4-5 | ①事件行保持短（资产走引用，已是）②append 走 `flock`。V1 只解了序号撞车，这是字节层 |
| 🟠 N5 | 异步**陈旧结果**：mesh 下载未回，asset 又被 update / 实体被删 → 旧结果晚到塞上 | 3 | 每实体一个 load generation token，按 `(entityId, sha256)` 作废过期下载 |
| 🟠 N6 | 两段式**失败路径**未定：网格化失败 daemon 发什么 | 4 | partial→update 带部分网格+defect；全败→note(capture_failure)+保留占位+标"mesh 失败" |
| 🟡 N7 | daemon **生命周期**：起/杀/崩溃发现/重启/日志 | 4-5 | occ-debug-start.sh 补 PID/健康，崩溃可见 |
| 🟡 N8 | 回放**并发下载风暴**：viewer 连上回放整段，每 shape 都 fetch | 3 | assetCache 加并发上限 |

**就绪结论**：阶段 1（协议）+ 阶段 2（occ-debug-mesh + BRepCheck）**可立即开干**——N1–N8 不挡，且 N2/N3 这两个便宜契约现在就写进协议草案，阶段 2 才不会漏掉 bbox 与命名约定。
