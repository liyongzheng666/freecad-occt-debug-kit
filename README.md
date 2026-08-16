# freecad-occt-debug-kit —— OCCT/FreeCAD 圆角失败根因诊断 Agent 与调试工具链

> **What this is**: a root-cause investigation agent + quantified eval harness for OCCT/FreeCAD fillet & chamfer failures, built on a reproducible debug environment (pinned forks, Pixi toolchain, LLDB capture, geometry viewer). Two audiences, two doors.
> **这是什么**：面向 OCCT/FreeCAD 圆角（fillet/chamfer）失败的**根因调研 agent + 量化 eval**——可复现调试环境、确定性工具层、决策回路、五维打分与弃权计量。

## 你是哪种读者？（Two doors）

| 身份 | 入口 | 3 秒预览 |
| --- | --- | --- |
| 🧱 几何建模 / 内核开发者 | [GEOMETRY.md](GEOMETRY.md) | 失效本体 S0–S6、失效四态、Parasolid 对照、缺陷导出、LLDB 捕获 |
| 🤖 Agent / Harness / Eval 工程师 | [AGENT.md](AGENT.md) | 决策回路、decide 接缝 A/B、五维打分、弃权四态、轨迹/review 闭环 |
| 🛠 想在本仓库构建 / 开发 | 往下读「环境编排」 | [docs/dependencies.md](docs/dependencies.md) 是依赖唯一权威源 |

## 30 秒上手（Quick start）

```bash
python -m agent.loop.investigate box 5                           # 合成 case 根因诊断
python -m agent.loop.investigate "brep:/abs/m.brep" 5 --edges 3  # 你的模型：根阶段 + 失效类别 + 修法 + 证据
bash agent/eval/eval.sh                                          # 五维 + 弃权四态分层打分
```

> **维护范围（Scope）**：runtime 仅支持与维护 **macOS Apple Silicon**。Linux 仅用于 CI 离线单测门（无 OCCT，干净 SKIP），不承诺可运行；其它平台不维护。提问题请带复现包（[.github/ISSUE_TEMPLATE.md](.github/ISSUE_TEMPLATE.md)）。

## 快速复现清单（Issue triage）

遇到问题按三层定位，10 分钟内锁定层：

```bash
bash scripts/workspace-doctor.sh          # ① 环境/布局/插桩/dylib 是否健康
bash scripts/run-agent-tests.sh           # ② 24 测试模块（哪层真失败、哪层 SKIP）
bash agent/eval/eval.sh --case box-r5     # ③ 单 case 复现（再换成出问题的 case）
```

分数基线冻结在 [agent/eval/baselines.md](agent/eval/baselines.md)，漂移即回归；依赖关系查 [docs/dependencies.md](docs/dependencies.md)。

## 仓库布局

```text
freecad-occt-debug-kit/
├── agent/                 诊断 agent：回路（loop/）+ 工具层（tools/）+ eval/（五维打分）
├── tools/occ-debug-mesh/  C++ BREP → mesh/geom/defect 转换器（本仓库内）
├── scripts/               构建 / 运行 / 调试 / 捕获 / 自检入口
├── docs/                  设计文档（按读者分轨，见 docs/README.md）
├── GEOMETRY.md / AGENT.md 两条读者轨道入口
├── FreeCAD/ · occt/ · tools/Print/   三个钉死 fork（bootstrap 克隆，不入本仓库）
└── .occ-debug/            调试会话输出（生成物，不入库）
```

> 三个 fork 各有自己的 git 历史/分支/远端，不随本仓库提交；全新 clone 只含配置层 + `occ-debug-mesh` + agent，按下面「环境编排」变成可构建、可调试的环境。本 kit 如何喂给 Print viewer，见[架构与 Print 依赖](#架构与-print-依赖)。

## 项目现状总览

本工作区是一套 **FreeCAD / OCCT 圆角失败根因诊断** 的完整栈——从可复现构建、几何采集，到自动化的根因诊断 agent 与量化 eval。四层子系统各自的成熟度：

| 子系统 | 落点 | 状态 |
| --- | --- | --- |
| 环境 / 构建层 | pinned forks + pixi + 幂等 `scripts/bootstrap.sh` | 成熟：一条命令从裸 clone 到可调试 |
| 几何工具 | `tools/occ-debug-mesh/`（BREP → mesh/geom/defect + BOP 面面自交校验） | 成熟：60+ 离线断言 + 夹具回归 |
| Agent（根因回路）+ Eval（量化） | `agent/`（observe→定位→机制→反事实→结论 + 五维打分 + rule/LLM A/B） | v0 投产，13-case；详见 [agent/README.md](agent/README.md) |
| CI + 护栏 | GitHub Actions 离线单测门 + eval 基线回归门 + `workspace-doctor.sh` | 新落地（见下「最近加固」） |

### 最近一轮加固（2026-07-04，剖析驱动，6 PR #7–#12）

针对"手动断言 / 装饰性代理 / 静默失效"三类隐患的系统性补强：

- **CI + 基线回归门**：接 GitHub Actions 跑 `agent/` 全套离线单测（无 OCCT 干净 SKIP）；`eval/test_baseline.py` 把 baselines 数字**冻结成 CI 断言**（Conclusion 快照重打分），scorer/聚合一漂移即变红。
- **反事实真分**：eval 的反事实维从"仅判是否携带修法"升为"与 GT 比对的真判别分"（5 维里补掉第一个装饰性代理）。
- **面面自交检测**：`check_valid` 补 `BOPAlgo_ArgumentAnalyzer`，堵"IsDone + BRepCheck 过但两面互穿"的假绿盲区（reward signal 完整性）——对现有 case 零回归，由基线门确认。
- **真实模型输入**：`build_shape` 支持 `fcstd:` 直读用户 FreeCAD 文档（从合成 case 跨到真实模型诊断）。
- **插桩耐久护栏**：`workspace-doctor.sh` 校验 `OCCT_DEBUG_SSI_OUT` 源码改造在源+已装 dylib 在位，把 WP5 静默失效变显式告警。

> 完整路线图、gap register（G1–G30）与逐项进展见 [agent/README.md](agent/README.md)；本次加固每项都经 CI 两版 Python 绿灯 + 基线门零漂移把关后合并。

## 环境编排：从全新克隆引导环境（在本仓库构建/开发的人）

> 本节面向**需要在本仓库构建/开发**的人；只读系统/Agent 的读者走上面两条轨道。

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

- OCCT 的三处本地改动现维护在 fork `liyongzheng666/OCCT` 的 `v7_8_1-fillet-debug` 分支上（不再是工作树补丁）：① 在 Debug 构建中保留 debug map，使 LLDB 能绑定断点（否则 `-Wl,-s` 会将其 strip 掉）；② 一处 Clang 18 要求的 FreeType `tags` 强制转换；③（2026-07-01）`ChFi3d_Builder_0.cxx::ChFi3d_StripeEdgeInter` 经 `OCCT_DEBUG_SSI_OUT` 环境变量门控落盘两 blend 面（纯加法，无该 env 时行为不变），供 agent 免-LLDB 抓 overlap 型 S3 失败现场（A7 WP5）。①② 已 push 到 fork；③ 本地已 commit，push 到 fork 后 fresh clone 即含（否则 `env_emit` capture 退回 untestable，不伪绿）。`patches/occt-debug-build.patch` 仅作为 ①② delta 的可读参考保留。排查表见 [docs/occt-debugging.md](docs/occt-debugging.md)。
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

- **来源**：`https://github.com/liyongzheng666/Print.git`，钉在 `PRINT_SHA = 98657e48aff2b0410a45f85540ee40e77dcc5ca4`（**以 `scripts/bootstrap.sh` 为准**，见 [docs/dependencies.md](docs/dependencies.md) 版本钉板表）。
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

按身份选轨道；全量索引在 [docs/README.md](docs/README.md)。

- [GEOMETRY.md](GEOMETRY.md) —— 几何建模/内核开发者轨道（失效本体 → Parasolid 对照 → 缺陷导出 → LLDB 捕获）。
- [AGENT.md](AGENT.md) —— Agent/Harness/Eval 工程师轨道（架构图 → 契约 → 决策回路 → eval）。
- [docs/dependencies.md](docs/dependencies.md) —— **依赖唯一权威源**：fork 钉板 / 构建链 / 运行时链 / 升级影响。
- [agent/README.md](agent/README.md) —— agent 总览与快速开始；[agent/docs/progress.md](agent/docs/progress.md) —— 路线图 / 进度档案。
- [tools/occ-debug-mesh/README.md](tools/occ-debug-mesh/README.md) —— 缺陷导出 CLI 的设计说明 / 交接文档（夹具、输出格式、决策表）。
- [docs/occ-fillet-debug-agent-architecture.md](docs/occ-fillet-debug-agent-architecture.md) —— 系统级架构（采集/埋点/agent/viewer 协作）。
- [docs/lldb-dynamic-geometry-capture.md](docs/lldb-dynamic-geometry-capture.md) —— 断点内活几何捕获。
- [docs/vscode-build-and-pixi.md](docs/vscode-build-and-pixi.md) / [docs/occt-debugging.md](docs/occt-debugging.md) / [docs/vscode-debug-breakpoints.md](docs/vscode-debug-breakpoints.md) —— 环境 / 调试工作流。
