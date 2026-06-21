# 断点管理与几何可视化调试

这个工作区已经配置好了 macOS 调试三件套：clangd 负责代码补全和跳转，CodeLLDB（`vadimcn.vscode-lldb`）负责调试，`scripts/lldb_occt_formatters.py` 里的 OCCT 格式化器在每次启动调试时自动加载。**调试器本身已经就绪，不需要你额外配置。**

跨 `FreeCAD/` 和 `occt/` 两棵大代码树调试时有两个麻烦：断点越来越多难以管理，以及变量面板里展开几何对象要点很多层。下面介绍两个扩展和几个内置功能来解决这两个问题。

两个扩展已经写进 `.vscode/extensions.json`，重新打开工作区时 VS Code 会自动提示安装。也可以随时执行命令 **Extensions: Show Recommended Extensions** 手动安装。

---

## 断点管理器（`loukas-kotas.breakpoints-manager`）

**解决的问题：断点太多、散落在两棵代码树里，打开关闭很麻烦。**

**核心用法：把断点分组，整组开/关。**

比如调查圆角（fillet）bug 时，把相关断点放进一个叫"fillet"的集合；同时研究另一个问题时再建一个"边缘相交"集合。两个集合互不干扰，随时切换，不用每次重新打断点。

具体操作：

1. 侧边栏会多出一个 **Breakpoints Manager** 面板，在里面点 **+** =2q w
2. 右键断点 → **Add to Collection** 把现有断点归入集合
3. 集合前面的勾可以整组开/关
4. 右键集合 → **Export** 可以把断点布局存成 JSON 文件，提交到 git 里，方便以后复现或共享给同事

**调圆角时推荐的起始断点组**（来自 `occt-debugging.md`）：

- `FreeCAD/src/Mod/Part/App/FeatureFillet.cpp` → `Part::Fillet::execute`
- `occt/src/BRepFilletAPI/BRepFilletAPI_MakeFillet.cxx` → `Add` 或 `Build`
- `occt/src/ChFi3d/ChFi3d_Builder_C1.cxx` → `PerformIntersectionAtEnd`

---

## 几何可视化（`hediet.debug-visualizer`）

**解决的问题：停在断点上只能看文字，看不到几何形状长什么样。**

这个扩展会打开一个独立面板，把你填入的表达式渲染成图形——可以是 3D 点云、拓扑关系图，或者折线图。每次单步都会自动刷新。

`scripts/lldb_occt_formatters.py` 里已经写好了三个函数，专门给这个扩展用：

| 函数 | 接受的变量类型 | 渲染效果 | 用来看什么 |
| --- | --- | --- | --- |
| `occ_topo` | `TopoDS_Shape` | 关系图（DAG） | 形状的拓扑层次：Solid→Shell→Face→Wire→Edge→Vertex，以及各子形状的朝向；共享的 TShape 会显示为一个节点、多条入边 |
| `occ_shape_pts` | `TopoDS_Shape` | 3D 点云 | 形状里所有顶点（Vertex）在三维空间的位置，每个点标注坐标 |
| `occ_pts` | `TColgp_Array1OfPnt` | 3D 点云 + 折线 | BSpline 极点或脊线采样点，连线后就是控制多边形；适用于任何 `NCollection_Array1<gp_Pnt>` |
| `occ_spine` | `ChFiDS_Spine` 或 `handle<ChFiDS_Spine>` | 3D 折线 | 脊线的所有边顶点按序连线，显示圆角脊线在三维空间的走向 |
| `occ_pt_curve` | 一个点 `gp_Pnt`/`gp_Pnt2d` + 一条曲线 | 3D 折线 + 单个高亮点 | 把点和曲线画在同一张图里，一眼看出这个点是否落在曲线上、位置对不对 |
| `occ_geom` | 任意多个点和/或曲线（互不相关） | 3D 折线 + 高亮点，每个一种颜色 | 把任意几个点、曲线叠在同一张图里对比位置；自动判别每个变量是点还是曲线 |

这三个函数只读内存，不会在被调试的进程里执行任何代码，所以完全安全，不会改变程序状态。

### 第一步：打开可视化面板

按 `Ctrl+Shift+P`（Mac 上是 `Cmd+Shift+P`）打开命令面板，输入并执行：

```text
Debug Visualizer: New View
```

面板打开后，顶部会出现一个输入框，把下面的表达式粘进去就行。

### 第二步：两步操作（第一次用时）

> **为什么需要两步**：Debug Visualizer 只读 DAP EvaluateResponse 的 result 字段，而 Python print / AppendMessage 的输出走的是 DAP output event（流向调试控制台）。解决方案是先把 JSON 写到 `/tmp/` 文件，再用一条 watch 表达式读这个文件——表达式返回值才进 EvaluateResponse.result。这里用的是 CodeLLDB 的原生求值器（`/nat` 前缀，见 `settings.json` 里的 `expressionTemplate`）：`/nat (...; (struct __dv_payload*)_b;)`，返回一个指向**不完整结构体**的指针。关键点:Debug Visualizer 只要看到 evaluate 响应带 `variablesReference != 0`,就改去画「变量子节点图」而无视 JSON;而任何能展开的值都会触发它(`char[N]` 数组→字符节点、`const char*`→解引用子节点 `*$1`、甚至加 synthetic 也会冒出 `[raw]`)。不完整结构体**无法解引用→没有子节点→`variablesReference == 0`**,而 `dv_payload_summary`(注册在 `__dv_payload` 上)把文件 JSON 作为该指针的摘要返回,正好进 result 被解析。**不要用 `/py`**(它产出 `char[N]` 数组)。详见 [occt-debugging.md](occt-debugging.md) 排查表。

**第一步：在 VS Code 底部"调试控制台"里运行命令**（不是 Debug Visualizer 面板）：

| 想看什么 | 调试控制台里输入 |
| --- | --- |
| 形状所有顶点（3D 点云） | `occ_viz_shape_pts Vtx` |
| 拓扑层次图（DAG） | `occ_viz_topo myShape` |
| BSpline 极点控制多边形 | `occ_viz_pts thePoles` |
| ChFiDS_Spine 脊线折线 | `occ_viz_spine mySpine` |
| 点 + 曲线画在一张图 | `occ_viz_pt_curve pt cv` |
| 任意多个点/曲线叠在一张图 | `occ_viz_geom pt1 pt2 cv1 cv2` |

命令成功后会提示 `Written /tmp/occ_dv_Vtx.json`。

> **多个点和曲线一起看：用 `occ_viz_geom`**。把所有变量名列在后面即可，顺序和混搭随意——`occ_viz_geom pt1 pt2 cv1 cv2`。它会**自动判别**每个变量是点（能读出 `coord` x/y/z）还是曲线（能调 `FirstParameter()`/`Value(t)`），每个 trace 配一种颜色。文件按**第一个**参数命名，所以 Debug Visualizer 框里填第一个变量名（这里是 `pt1`）。`occ_viz_pt_curve` 现在只是它的两参数别名。
>
> **`occ_viz_geom`/`occ_viz_pt_curve` 与其他命令的不同**：其他命令只读内存，而曲线无法从内存直接采样，所以它会在被调试进程里调用 `cv.Value(t)` 采样曲线（自动识别 `.`/`->` 调用方式和 2D/3D）。`Value()` 是 const 调用、无副作用，跟 `occ_save` 用的是同一种目标求值方式。

**第二步：在 Debug Visualizer 输入框里填变量名**（只填变量名，不加其他东西）：

```text
Vtx
```

`settings.json` 里的 `expressionTemplate` 会自动把 `Vtx` 包裹成读取 `/tmp/occ_dv_Vtx.json` 的 `/nat (struct __dv_payload*)` 表达式，结果就显示出来了。

之后每次单步，Debug Visualizer 会自动刷新（重新读文件）。如果变量值变化了想更新可视化，再跑一次调试控制台命令即可。

填完表达式后按回车，图形就会出现。之后每次按 F10（单步）或 F11（步入），图形自动刷新。

### 第三步：固定到某个变量上

可以同时打开多个 Debug Visualizer 面板，分别监视不同变量。比如一个盯着整体形状的拓扑，另一个盯着某个面的极点数组。

### 调 ChFi3d_Builder（圆角构造器）时的典型用法

| 在哪里打断点 | 看哪个变量 | 用哪个函数 | 能看到什么 |
| --- | --- | --- | --- |
| `ChFi3d_Builder.cxx`，脊线构造完之后 | `mySShape` 或 `mySpine` | `occ_viz_topo mySShape` | 脊线引用了哪些面和边 |
| `ChFi3d_Builder_C1.cxx`，`PerformIntersectionAtEnd` | `Sol` 或 `F1`/`F2` | `occ_viz_shape_pts Sol` | 面面求交结果的顶点位置 |
| 曲面构造函数内部，有 `TColgp_Array1OfPnt` 的地方 | 极点数组变量 | `occ_viz_pts thePoles` | BSpline 控制多边形随单步演变的过程 |
| `ChFi3d_Builder.cxx` 或 `ChFiDS_Spine.cxx`，脊线初始化完之后 | `mySpine`（`ChFiDS_Spine` 或 `Handle(ChFiDS_Spine)`） | `occ_viz_spine mySpine` | 脊线所有边的顶点按序连成折线，直观显示脊线在三维空间的走向 |

### 想看完整曲面（不只是顶点）？用 occ_save 导出

点云只能看顶点，看不到面和边的真实形状。如果你需要看完整的几何，在调试时于 LLDB 控制台（VS Code 底部的"调试控制台"）输入：

```text
occ_save myShape /tmp/dbg.brep
```

这会把 `myShape` 这个变量的几何存成 BREP 文件，然后用 FreeCAD、CAD Assistant 或 OCCT DRAW Harness 打开 `/tmp/dbg.brep` 就能看到完整的 3D 几何。

`occ_save` 命令在调试一开始就自动注册好了，无需额外配置，直接用即可。

### 不想依赖 Debug Visualizer？用 occ_view.py 在浏览器里看

`occ_viz_*` 命令写出的 `/tmp/occ_dv_<var>.json` 本身就是 **Plotly 原生的 `data`/`layout` 格式**，Debug Visualizer 只是其中一个（而且毛病不少的）消费者。同一份 JSON 在普通浏览器里就能渲染，完全不依赖 VS Code、DAP、`__dv_payload` 那套技巧：

```text
scripts/occ_view.py                 # 渲染所有 /tmp/occ_dv_*.json
scripts/occ_view.py Spine           # 只看 /tmp/occ_dv_Spine.json
scripts/occ_view.py Spine Vtx       # 把两份文件叠加到同一张 3D 图里
scripts/occ_view.py /path/to.json   # 直接指定文件路径
```

它把所有传入的 **plotly 类型**文件叠加到同一张图（trace 自动按来源命名、配不同颜色），所以这正是**对比曲线 `cv` 与 STEP 实体**最稳的做法：分别 emit（例如 `occ_viz_pt_curve pt cv` 加一个形状 emitter），再 `scripts/occ_view.py cv <shape>` 在一张图里对比。拓扑图（`graph`）和文本（`text`）类型也能渲染。脚本读 JSON 后写出 `/tmp/occ_view.html` 并用默认浏览器打开（`--no-open` 只写文件不打开）。Plotly.js / vis-network 走 CDN，离线环境需自行替换为本地副本。

---

## VS Code 内置断点功能（不需要安装任何扩展）

很多人只用普通断点，其实内置就有这些功能，用好了能省大量时间。右键任意断点 → **编辑断点**，或在 BREAKPOINTS 面板顶部点 **Add Function Breakpoint**。

| 功能 | 什么时候用 |
| --- | --- |
| **条件断点** | 只在某个表达式为真时才停——比如只在处理第 5 条边时停，不用手动跳过前面 4 次 |
| **命中计数断点** | 在一个热路径上，只在第 N 次经过时才停，不用狂按继续键 |
| **日志点（Logpoint）** | 打印一个表达式的值但不暂停程序——替代在代码里加 `Base::Console().Log(...)` |
| **触发断点** | 先命中断点 A，断点 B 才会生效——用来隔离某条特定的调用路径 |
| **函数断点** | 按函数名打断点，适合模板函数或重载函数找不到具体行号的情况 |

---

## 延伸阅读

- [docs/occt-debugging.md](occt-debugging.md) — 完整的 clangd + CodeLLDB 工作流、构建优先的启动配置，以及可复现的圆角冒烟场景
