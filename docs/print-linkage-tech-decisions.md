# Print ↔ Kit 联动技术选型

> 状态：已接受的架构决策<br>
> 核对日期：2026-06-21<br>
> 适用范围：`freecad-occt-debug-kit`（生产/编排）与 `Print`（消费/Viewer）两仓库之间的联动接缝<br>
> 上游设计：[occ-fillet-debug-agent-architecture.md](occ-fillet-debug-agent-architecture.md) §7、[lldb-dynamic-geometry-capture.md](lldb-dynamic-geometry-capture.md)

本文件锁定两仓库**物理接缝**上的技术选型与硬契约，不重复协议字段语义（见 Print `protocol/`）。
残留风险登记在文末 [§8 风险与隐患登记表](#8-风险与隐患登记表)。

## 1. 联动接缝

```text
Kit 端（生产 / 编排）                                  Print 端（消费 / Viewer）
occdbg / Capture ──► events.ndjson ─────────────────► Bridge(tail+replay) ─► SSE ─► Scene Store ─► Renderer
        │                                                     │
        └─► BREP 资产 ──► occ-debug-mesh ──► print-mesh 资产 ──► Bridge(静态托管 assets/) ─► Renderer
            （kit 侧在写入 BREP 后即转换）                      （只 serve 文件，绝不 shell out）
                         ▲
            .occ-debug/sessions/<id>/  ← 两仓库唯一共享：路径经 OCC_DEBUG_SESSION 握手
```

两仓库唯一的物理接触点是 **Session 目录**（NDJSON 事件流 + 资产）与 **Bridge**。
**关键边界**：三角化由 **kit 生产端**完成，Bridge 只对 `assets/` 做静态托管，**永不调用 kit 二进制**——以此保住 arch §7.2 的 "Print 只消费协议、不依赖 kit/FreeCAD" 边界。

## 2. 已锁定的选型

| 维度 | 决策 | 理由 | 落点 |
| --- | --- | --- | --- |
| 事件传输 | **SSE** | 单向增量推送（Bridge→Viewer）；viewer 对采集的控制走 VS Code/LLDB，不回传 Bridge，故无需 WebSocket 双工；arch §7.1 已写明 SSE。**但重连不等于免费**，见 §3 的 replay 契约。 | `Print/bridge/` ↔ `viewer` |
| Bridge 技术栈 | **Python 标准库**（`ThreadingHTTPServer` + 轮询 tail） | 零第三方依赖，不与 FreeCAD pixi Python 冲突。**注意隐性代价**：默认 `http.server` 单线程会被长连 SSE 阻塞，必须用 `ThreadingHTTPServer`；stdlib 无 inotify/FSEvents，tail 实为轮询。 | `Print/bridge/` |
| BREP→Mesh 三角化 | **C++ `occ-debug-mesh` 独立工具，由 kit 生产端触发**（方案①） | 用与被调试进程相同的本地 OCCT ABI 三角化，避免内核版本错配；**触发点放在 kit 而非 Bridge**，使 Print 保持纯消费。 | `tools/occ-debug-mesh/`（kit，待建） |
| `print-mesh` 线格式 | **分面网格：per-face 子网格 + 独立 edge polyline**，double 坐标 + 可选 local-origin | 调试器核心是选/高亮 face/edge，**三角汤会丢拓扑**，必须按 face 分组并单列 edge；double + local-origin 规避远原点 Float32 抖动。 | `protocol` + `occ-debug-mesh` + viewer renderer |

## 3. 硬契约（上线 SSE / NDJSON 前必须成立）

### 3.1 Session 路径握手

- 两仓库唯一要对齐的运行时参数。**契约环境变量 `OCC_DEBUG_SESSION`**（session 根目录），与 lldb 文档 §6 一致。
- Bridge 启动参数 `--session <dir>`，缺省读 `OCC_DEBUG_SESSION`；kit 生产端写同一变量指向的目录。
- 目录结构：`<session>/events.ndjson` + `<session>/assets/*.{brep,mesh.json}`。

### 3.2 SSE 冷启动全量 replay + 续传

- `tail -f` 语义会让 viewer **首次连接 / 浏览器刷新时收不到此前所有 `add`**，场景为空；丢一个 `add` = 该几何永久消失（reducer 的 seq 缺口检测只报 warning，不补数据）。
- **契约**：Bridge 收到 `/events` 连接后，**先按行回放整个 `events.ndjson` 快照**，再切换到 tail。
- **续传**：尊重 `Last-Event-ID` 请求头，从该游标之后继续，避免重连后重复全量回放。

### 3.3 SSE 全局游标 与 协议 `seq` 解耦

- `Last-Event-ID` 是**单一全局游标**；协议 `seq` 是 **per `run_id`** 单调（reducer 用 `lastSeqByRun` 跟踪）。直接拿 `seq` 当 SSE `id` 会在多 run 时错乱。
- **契约**：SSE 的 `id:` 用 **events.ndjson 的全局行号（或字节偏移）**；协议内 `seq` 仍 per-run，仅供 reducer 去重/缺口检测。

### 3.4 NDJSON 原子整行写

- 生产端正写一行时，Bridge 可能读到**半行 JSON** 导致解析炸。
- **契约**：生产端**整行原子写**（一次 `write()` 带 `\n`，禁止分多次写）；Bridge 按 `\n` 缓冲、只发完整行；单行 JSON 解析失败 → 记诊断并跳过，不中断流。

### 3.5 跨源（dev 期）

- viewer 在 Vite dev（`127.0.0.1:5777`），Bridge 在另一端口 → 跨源。
- **决策**：在 `viewer/vite.config.ts` 配 `/events`、`/assets` 的 proxy 到 Bridge（生产期同源，dev 期免 CORS 头）；Bridge 同时输出限定来源的 `Access-Control-Allow-Origin` 作为兜底。

## 4. `print-mesh` 资产格式

OCCT 三角化（`Poly_Triangulation`）产出节点+三角形索引；**法线是可选的**，缺失时由 `occ-debug-mesh` 现算，且 `REVERSED` 朝向的 face 必须翻向。线格式按 face 分组、坐标用 double：

```jsonc
{
  "format_version": "1.0",
  "unit": "mm",
  "local_origin": [x0, y0, z0],          // 可选；positions 相对此偏移，规避远原点 Float32 抖动
  "faces": [
    {
      "face_id": "Face3",                 // 回映射拓扑用
      "orientation": "FORWARD",           // FORWARD/REVERSED，决定法线方向
      "positions": [/* double, 相对 local_origin */],
      "indices":   [/* 三角形顶点索引，Uint32 语义 */],
      "normals":   [/* 生产端通常已补全（含 orientation 翻向）；省略时 viewer 兜底现算 */]
    }
  ],
  "edges": [
    { "edge_id": "Edge7", "points": [/* double polyline，相对 local_origin */] }
  ]
}
```

- viewer 端按 `face_id`/`edge_id` 建独立 Object3D，支撑选中/高亮/分面着色。
- `format_version` 独立于事件协议的 `schema_version`，允许资产格式单独演进。

## 5. 选型带来的待建项

- `Print/bridge/`（Python 标准库）：`ThreadingHTTPServer`；`/events` 全量 replay→tail SSE；`/assets/*` 静态托管（限定 session 目录内，防路径穿越）。**不做三角化、不 shell out。**
- `viewer`：新增 SSE 客户端，`EventSource` 订阅 `/events` 并 `applyEvents`，替换写死的 `sampleEvents`；会话条从 "本地数据" 切到真实连接状态。`vite.config.ts` 配 proxy。
- `tools/occ-debug-mesh/`（C++，kit）：`BREP → print-mesh`（§4 格式），由 kit 生产端在写入 BREP 后触发。M2 进入主路径。
- `protocol`：将 §4 的 `print-mesh` 格式补成正式 schema 文件。

## 6. 不在本次选型范围

- `libOccDebugCapture` 的 C ABI 细节（见 lldb-dynamic-geometry-capture.md §4）。
- VS Code Variables/Watch 右键发送扩展（见 vscode-send-to-print.md）。
- FCStd baseline 提取与世界坐标对齐（arch §9）。

## 7. 第一个端到端切片

不依赖 C++ Capture 库与 occ-debug-mesh 即可打通的最小闭环，用于先验证管道。
**本切片只用 inline geometry kinds（`point/point_set/vector/polyline/curve/edge/wire/bbox`），不碰 `asset/shape/face`**——因为 [basicRenderers.ts](../tools/Print/viewer/src/rendering/renderers/basicRenderers.ts) 尚未注册 `shape/face/surface_patch` renderer。

1. **Bridge**（`Print/bridge/`，Python 标准库）：`/events` 全量 replay→tail SSE（§3.2–3.4）。
2. **SSE 客户端**（`viewer/src/core/`）：`EventSource` 订阅，`applyEvents` 接管 sampleEvents。
3. **假生产者**（kit `scripts/`）：把等价于 sampleEvents 的 NDJSON 逐行**原子**追加进 session，验证实时增量。

打通后再按 M1→M2 推进：旧 JSON adapter → LLDB occdbg 写真 NDJSON → `occ-debug-mesh` BREP/mesh → FCStd baseline。

## 8. 风险与隐患登记表

本表登记**未固化为硬契约的残留风险与待定项**（§2–§4 是已锁定决策，本表是需持续盯的清单）。
状态：🟢 已决策（方向锁定，实现待落地）｜🟠 待实现时验证｜🟡 已缓解但有残差。

| # | 隐患 | 触发条件 | 影响 | 缓解 / 待决策 | 状态 | 归属 |
| --- | --- | --- | --- | --- | --- | --- |
| H1 | 上游文档冲突：Print [README.md](../tools/Print/README.md) 第 45 行原写 "Bridge 负责…将 BREP 异步转换为显示 Mesh"，与本决策（方案①，kit 生产端转）相反 | 实现时按哪份文档走 | 职责归属分裂、Bridge 误引入 OCCT 依赖 | **已修订** Print README 第 45 行为 "三角化由 Kit 生产端完成，Bridge 仅静态托管 assets/，不调用 Kit 二进制" | 🟢 | Print 文档 |
| H2 | run 生命周期：README 说 "新 Run 默认清理旧对象"，但 `clear_scene` 由谁发未定（生产端显式发？viewer 在 `run_end`/新 `run_id` 推断？） | 一个 session 内跑多次 | 旧 run 对象残留或被误清 | **已定**：生产端在新 run 起始显式发 `clear_scene`，viewer 不擅自推断；实现待 occdbg/Capture 落地 | 🟢 | 协议/生产端 |
| H3 | 协议漂移：schema 真源在 `Print/protocol/`，kit 生产端无共享校验 | kit 改了字段而 Print 未同步 | 产出不合规事件、viewer 静默丢弃 | **已定**：kit 侧对产出事件做 schema 校验（CI 引 Print 的 `protocol/*.schema.json` 做 lint）；实现待 Capture/生产管线落地 | 🟢 | 两仓库 |
| H4 | 远原点精度残差：即便 double + `local_origin`，three.js `BufferGeometry` 内部仍 Float32 | 超大装配、跨度极大 | 远离 local_origin 的几何仍抖动 | 必要时改 per-entity local frame；先记录，M2 视觉回归时验证 | 🟡 | viewer |
| H5 | 法线一致性：生产端现算法线与 viewer 兜底现算可能不一致；`REVERSED` 漏翻 → 背面光照错 | mesh 缺法线 / 朝向处理疏漏 | 着色/光照错误，误导调试判断 | 生产端为权威、统一现算并按 orientation 翻向；viewer 兜底仅兜底 | 🟠 | occ-debug-mesh + renderer |
| H6 | 大 session 冷启动 replay：`events.ndjson` 极大时全量回放慢，无快照/compaction | 长会话后刷新/重连 | 首屏延迟、内存峰值 | 后续引周期性快照或分段；先接受全量 | 🟡 | Bridge |
| H7 | 轮询 tail 的延迟/CPU 权衡：stdlib 无 FS 事件 | 高频事件 vs 低延迟需求 | 间隔短费 CPU、间隔长有延迟 | 间隔可配（默认 100–200ms）；必要时按空闲退避 | 🟡 | Bridge |
| H8 | 生产端崩溃留半行：§3.4 规定整行原子写，但进程崩溃仍可能留尾部半行 | 被调试进程异常退出 | Bridge 读到不完整尾行 | Bridge 容忍尾部半行，仅在补全 `\n` 后再发 | 🟠 | Bridge |
| H9 | 静态资产路径穿越：Bridge serve `assets/` 需严格限定在 session 目录内 | 恶意/拼接路径含 `../` | 越权读任意文件 | 规范化路径并校验前缀，拒绝逃逸；列为安全 checklist | 🟠 | Bridge |
| H10 | occ-debug-mesh 新增需链接本地 OCCT 的构建目标，且与 OCCT patch/版本绑定 | 引入新 C++ 工具 | bootstrap 多一步构建、版本耦合 | bootstrap 增加 occ-debug-mesh 构建步骤，pin 同一 OCCT | 🟡 | kit/bootstrap |
| H11 | SSE/HTTP-1.1 单域 6 连接上限 | 多浏览器 tab 同开 | 额外 tab 的 SSE 饿死 | localhost 单 viewer 通常无碍；多 tab 时提示或复用连接 | 🟡 | Bridge/viewer |
