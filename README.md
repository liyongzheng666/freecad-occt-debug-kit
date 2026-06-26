# FreeCAD + OCCT 本地开发工作区

这个外层目录是开发的**编排层**：在本地克隆、构建并调试 FreeCAD + OCCT，再把调试器捕获到的几何转成供 **Print** viewer 使用的几何调试资产。它管理**三个**各自独立的源码仓库，这三个都不随本 kit 提交：

```text
freecad/                  工作区配置、脚本与文档（本仓库）
├── FreeCAD/              FreeCAD 源码 + Pixi/Ninja debug 构建          （克隆并钉死；不在本仓库）
├── occt/                 OCCT 源码 + Makefiles debug 构建 + install     （克隆并钉死；不在本仓库）
├── tools/
│   ├── occ-debug-mesh/   C++ BREP → print-mesh/geom/defect 转换器       （在本仓库内）
│   └── Print/            Print viewer + bridge + protocol schema        （克隆并钉死；不在本仓库）
├── scripts/              配置 / 构建 / 运行 / 调试 / 捕获 / 预览 的入口
├── templates/            属于被忽略源码树内、需还原的文件（如本地 CMake preset）
├── patches/              克隆源码树后需重新应用的本地源码改动
├── docs/                 工作区专属文档
├── .vscode/              两个源码树共用的唯一 VS Code 配置
└── .occ-debug/           调试会话输出：events.ndjson + assets           （生成物；不在本仓库）
```

本外层 Git 仓库刻意忽略 `FreeCAD/`、`occt/`、`tools/Print/`（三者各有自己的分支 / diff / 远端历史），以及 `.occ-debug/`、`.omx/`、`myFold/`（生成数据与本地状态）。

也就是说，**本仓库的全新 clone 只包含配置层加上 `occ-debug-mesh` 工具**，不含 FreeCAD、OCCT 或 Print 源码。按[从全新克隆引导环境](#从全新克隆引导环境)把它变成可构建、可调试的环境。本 kit 如何喂给 Print viewer，见[架构与 Print 依赖](#架构与-print-依赖)。

## 从全新克隆引导环境

本 kit 的 clone 只含配置层。一条命令把它变成可构建、可调试的环境：

```bash
git clone https://github.com/liyongzheng666/freecad-occt-debug-kit.git freecad
cd freecad
scripts/bootstrap.sh            # 克隆钉死的源码、打补丁、构建 OCCT + FreeCAD、自检
```

前置条件（macOS Apple Silicon）：`git`、[`pixi`](https://pixi.sh)（提供锁定的 Clang/CMake/Qt 工具链）、Xcode Command Line Tools。`scripts/bootstrap.sh` 是**幂等**的——重跑会跳过已完成的步骤，所以它也兼作修复入口。传一个并行任务数可覆盖默认的 `-j 8`，例如 `scripts/bootstrap.sh 12`。

目录布局很重要：`occt/` 与 `FreeCAD/` 必须是同级兄弟目录，因为 CMake preset 通过 `${sourceParentDir}/occt/install/debug` 引用 OCCT 的 install。

### 脚本等价的手工步骤

```bash
# 1. 从 liyongzheng666/OCCT fork 取源码：v7_8_1-fillet-debug 分支已含 debug/build 改动（无需打补丁）。
git clone --depth 1 --branch v7_8_1-fillet-debug https://github.com/liyongzheng666/OCCT.git occt

# 2. 从 liyongzheng666/FreeCAD fork 取源码，钉死到本 kit 捕获时的确切 commit。
git clone --filter=blob:none https://github.com/liyongzheng666/FreeCAD.git FreeCAD
git -C FreeCAD checkout 2b7e9a6896bc9b5dc4555c2f6faa9adc0a7caf47

# 3. 还原那些本属于 FreeCAD/ 内、但不在 FreeCAD git 里的文件：
#    仅本地的 CMake preset（被 FreeCAD 自己的 .gitignore 丢弃）与 toponaming 参考说明。
cp templates/CMakeUserPresets.json FreeCAD/CMakeUserPresets.json
cp templates/TOPONAMING.md         FreeCAD/src/Mod/Part/App/TOPONAMING.md

# 4. 落地锁定的 Pixi 工具链（Clang 18、CMake、Ninja、Qt …）。
( cd FreeCAD && pixi install --frozen )

# 5. 构建 OCCT（debug + install），再针对该本地 OCCT 构建 FreeCAD。
scripts/configure-occt.sh
scripts/rebuild-occ.sh
( cd FreeCAD
  pixi run --frozen -- cmake --preset local-occt-macos-debug
  pixi run --frozen -- cmake --build build/debug -j 8 )

# 6. 自检工具链、索引与运行时库解析。
scripts/workspace-doctor.sh --runtime
```

注意：

- OCCT 的两处本地改动现维护在 fork `liyongzheng666/OCCT` 的 `v7_8_1-fillet-debug` 分支上（已 commit，不再是工作树补丁）：在 Debug 构建中保留 debug map，使 LLDB 能绑定断点（否则 `-Wl,-s` 会将其 strip 掉）；以及一处 Clang 18 要求的 FreeType `tags` 强制转换。`patches/occt-debug-build.patch` 仅作为该 delta 的可读参考保留。排查表见 [docs/occt-debugging.md](docs/occt-debugging.md)。
- FreeCAD 从 fork `liyongzheng666/FreeCAD` 的 `local-occt-integration` 分支钉死在 commit `2b7e9a6896b`（`FreeCAD/main` 的祖先），当前与上游零 diff、精确可复现；本 kit 仍把仅本地的 CMake preset 与 `TOPONAMING.md` 参考说明从 `templates/` 还原进去（见上一步第 3 步）。
- 构建完成后，用 `code .` 打开工作区，并从[从这里开始](#从这里开始)继续。

## 从这里开始

打开这个外层目录，而不是单独打开某个源码仓库：

```bash
code .
scripts/workspace-doctor.sh
```

安装 `.vscode/extensions.json` 推荐的扩展。随后 clangd 会使用按路径划分的 `.clangd` 配置：

- `FreeCAD/**` → `FreeCAD/build/debug/compile_commands.json`
- `occt/**` → `occt/build/debug/compile_commands.json`

## 常用命令

```bash
scripts/bootstrap.sh                         # 一键：克隆源码 + 全量构建（见上）
scripts/configure-occt.sh                    # 配置 OCCT 并生成其 compile database
scripts/rebuild-occ.sh                       # 增量构建 + install OCCT
scripts/fc-cmd.sh scripts/debug_target.py    # 跑几何冒烟场景
scripts/fc-lldb.sh scripts/debug_target.py   # 在命令行 LLDB 里调试该场景
scripts/fc-gui.sh                            # 用本地 OCCT 跑 FreeCAD GUI
scripts/workspace-doctor.sh --runtime        # 额外做动态库解析检查
```

VS Code 暴露了等价的 configure / build 任务。常规的 CodeLLDB launch 配置会在启动前先跑 `Debug: sync local toolchain`；只有在检查一个已构建好的进程时，才用名为 `skip build` 的那个配置。

## 架构与 Print 依赖

本仓库（kit）是**生产 / 编排端**：克隆并构建本地可调试的 FreeCAD + OCCT，在断点处捕获几何，并把捕获到的 BREP 转成可视化资产。**Print** 是**消费 / Viewer 端**，是一个独立仓库，由 `scripts/bootstrap.sh` 克隆并钉死到固定 commit：

- **来源**：`https://github.com/liyongzheng666/Print.git`，钉在 `PRINT_SHA = b69d0d19f9c756f756cf7805795b7f3c8c5e7180`（见 `scripts/bootstrap.sh`）。
- **落点**：`tools/Print/`，被本仓库 `.gitignore` 忽略——它有自己的 git 历史 / 分支 / 远端，不随本仓库提交。
- **提供三样东西**：
  - `tools/Print/protocol/` — **硬契约 JSON Schema**：`print-mesh.schema.json`（逐面网格）、`geom.schema.json`（几何 / 拓扑 sidecar）、`event.schema.json`（事件 / 缺陷）。
  - `tools/Print/bridge/bridge.py` — **Bridge**：Python 标准库 `ThreadingHTTPServer`；`/events` 走 SSE（冷启动整文件回放 + `Last-Event-ID` 续传），`/assets/` 静态托管资产。
  - `tools/Print/viewer/` — **Viewer**：TypeScript / React / Three.js 渲染器。

### 两仓库的接缝（唯一物理接触点）

```text
kit（生产 / 编排）                                       Print（消费 / Viewer）
LLDB 捕获 ──► events.ndjson ─────────────────────────► Bridge(tail + 回放) ─SSE─► Scene Store ─► Renderer
     │                                                        │
     └─► *.brep ──► occ-debug-mesh ──► *.mesh/.geom/.defects ─► Bridge(/assets 静态托管) ─► Renderer
         （与被调试进程同一本地 OCCT V7_8_1 ABI 三角化）        （只 serve 文件，绝不调用 kit 二进制）
                              ▲
                 .occ-debug/sessions/<id>/  ← 两仓库唯一共享；路径经环境变量 OCC_DEBUG_SESSION 握手
```

- **唯一共享**：Session 目录 `.occ-debug/sessions/<id>/`（`events.ndjson` + `assets/`），由环境变量 `OCC_DEBUG_SESSION` 对齐。
- **边界（硬约束）**：三角化由 kit 端的 `occ-debug-mesh` 完成；Bridge 只对 `assets/` 做静态托管，**永不调用 kit 二进制**——以此保证「Print 只消费协议、不依赖 kit / FreeCAD」。
- 协议真源在 `tools/Print/protocol/*.schema.json`；接缝决策见 [docs/print-linkage-tech-decisions.md](docs/print-linkage-tech-decisions.md)。

> **集成进度（准确说明，避免误解）**：`occ-debug-mesh`（工具）与 Print 的 `bridge` / `viewer` / `protocol` 均已就位；**当前 viewer 渲染的是离散边（`edges[]`）与 UV 面板**，BREP 资产 → 三角网格的流式渲染路径（即让一个常驻「daemon」自动把 `*.mesh.json` 追加成 mesh 事件）仍在进行中（M2-3，见 docs）。`scripts/mesh-to-session.py` 是把 `occ-debug-mesh` 输出喂进一个 Print session 的现成桥接脚本。

## occ-debug-mesh ↔ Print 使用方法

`occ-debug-mesh`（`tools/occ-debug-mesh/`，本仓库内）是一个 C++ CLI，把一个 BREP 转成 `*.mesh.json` + `*.geom.json` + `*.defects.json`。它链接 `occt/install/debug` 的本地 OCCT，与被调试进程同 ABI。详细设计见 [tools/occ-debug-mesh/README.md](tools/occ-debug-mesh/README.md)。

### 1) 构建并自检工具

```bash
scripts/build-occ-debug-mesh.sh          # 用 pixi clang 18 编译；OpenCASCADE_DIR 指向 install 树
scripts/verify-occ-debug-mesh.sh         # 一键离线回归：全部夹具 + 60 项断言（无需 LLDB）
```

### 2) 单次转换（BREP → JSON）

```bash
BIN=tools/occ-debug-mesh/build/occ-debug-mesh
$BIN in.brep out.mesh.json               # 同时写 out.geom.json 与 out.defects.json
$BIN --timeout 30 in.brep out.mesh.json  # 可选：网格看门狗，超时未网格化的面进 failed_faces、不崩
$BIN --diagnose in.brep                  # 打印 BRepCheck 对每个子形状的报告（调试用）
# 离线夹具自测（无需 LLDB）：--make-test-box / -located / -mirror / -nonmanifold / -nurbs …
```

### 3) 浏览器预览（独立，不需要 Print）

```bash
scripts/mesh-view.py out.mesh.json       # 面（半透明）+ edges[]（高亮折线），世界比例
scripts/geom-view.py out.geom.json       # 几何 / 拓扑 sidecar 预览
```

### 4) 在 Print Viewer 里看（Bridge + Viewer）

```bash
# a. 把 occ-debug-mesh 输出转成一个 Print session（写 events.ndjson + assets）
#    注意 mesh-to-session.py 无可执行位，需用 python3 调用
python3 scripts/mesh-to-session.py out.mesh.json --session .occ-debug/sessions/dev

# b. 起 Bridge（Python 标准库；默认读 $OCC_DEBUG_SESSION，否则 .occ-debug/sessions/dev）
tools/Print/bridge/bridge.py --session .occ-debug/sessions/dev --port 7341

# c. 起 Viewer（Vite dev；/events 与 /assets 已 proxy 到 Bridge）
( cd tools/Print && npm run dev )        # 打开 Vite 提示的地址
```

> 端到端调试场景（在断点处捕获几何）见 `scripts/fc-lldb.sh` / `scripts/debug_target.py` 与 [docs/lldb-dynamic-geometry-capture.md](docs/lldb-dynamic-geometry-capture.md)。

## 构建边界

- FreeCAD 的依赖与编译器来自 `FreeCAD/.pixi/envs/default`。
- FreeCAD 使用仅本地的 `FreeCAD/CMakeUserPresets.json`，preset 名为 `local-occt-macos-debug`。
- OCCT 在 `occt/build/debug` 构建，install 到 `occt/install/debug`。
- 该本地 preset 把 `occt/install/debug/lib` 排在构建 RPATH 中 Pixi 之前；运行 / 调试入口还会额外设 `DYLD_LIBRARY_PATH` 作为兜底。

生成目录被刻意排除在 VS Code 的常规搜索与文件监视之外。不要把 `.pixi`、build、install 目录当作常规清理对象删除。

## 文档

- [tools/occ-debug-mesh/README.md](tools/occ-debug-mesh/README.md) —— `occ-debug-mesh` 的设计说明 / 交接文档（夹具、输出格式、决策表）。
- [docs/print-linkage-tech-decisions.md](docs/print-linkage-tech-decisions.md) —— Print ↔ kit 联动的技术选型与硬契约（Session 握手、SSE、print-mesh 格式）。
- [docs/occ-fillet-debug-agent-architecture.md](docs/occ-fillet-debug-agent-architecture.md) —— 增量式 FreeCAD/OCCT 圆角（fillet）调试 agent 与几何 viewer 的架构与实现计划。
- [docs/lldb-dynamic-geometry-capture.md](docs/lldb-dynamic-geometry-capture.md) —— 以调试器为先的几何捕获命令：无需为每次观察重新构建，即可发出点、曲线、拓扑与 BREP 资产。
- [docs/vscode-send-to-print.md](docs/vscode-send-to-print.md) —— 首版 VS Code Variables/Watch 右键工作流，经 CodeLLDB 与共享的 Capture 流水线把选中的几何送往 Print。
- [docs/vscode-build-and-pixi.md](docs/vscode-build-and-pixi.md) —— VS Code 构建 / 链接流水线与 Pixi 如何配合（面向新手的 Pixi 与 CMake 入门）。
- [docs/occt-debugging.md](docs/occt-debugging.md) —— 调试工作流与排查指南。
- [docs/vscode-debug-breakpoints.md](docs/vscode-debug-breakpoints.md) —— 断点设置与技巧。
