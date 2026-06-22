# 变更记录（改动目的）

> 记录每批改动**为什么做**，而非逐行 diff。细节见各设计文档与 git 历史。
> 约定：今后每批改动都在此追加一条"做了什么 → 目的"。

## 1. 仓库整合与基础设施

| 改动 | 目的 |
| --- | --- |
| Print 纳入 `tools/Print/`（pin SHA + bootstrap 拉取 + gitignore） | 两仓库统一管理、从裸 clone 可复现地拉到匹配版本 |
| 建立 gitnexus 代码图谱索引 | 让"这函数谁调/改它影响谁"可查 |
| `.occ-debug/` 加入忽略 | 会话生成数据（events/BREP）不进版本库 |

## 2. 联动链路（端到端管道，slice A/B/C）

| 改动 | 目的 |
| --- | --- |
| `scripts/fake-occ-session.py` 假生产者 | 在 C++ Capture 还没有时，就能验证整条管道 |
| `tools/Print/bridge/bridge.py`（Python 标准库 SSE Bridge） | tail `events.ndjson` → SSE，连接即全量 replay，把事件实时喂给浏览器 |
| viewer SSE 客户端（`sseClient`/`useBridgeStream`）+ vite proxy | 实时接入 Bridge，替换写死的 `sampleEvents`，打通 producer→Bridge→viewer |

## 3. 边界加固（让管道扛得住真实使用）

| 改动 | 目的 |
| --- | --- |
| producer reset 改为"新 `run_id` + `clear_scene`"（不再 truncate） | 免刷新重载；规避 reducer 的单调 seq / 唯一 id 冲突 |
| Bridge：truncation 兜底 + 解码容错 + 心跳缩短 | 文件被截断/坏行/死连接时不崩、不卡 |
| 无 renderer 的 kind 报诊断（不再静默丢） | 让"画不出来的几何"看得见 |
| Solo 的"显示全部"按钮 | Solo 后能一键恢复全部分组 |

## 4. viewer 可读性

| 改动 | 目的 |
| --- | --- |
| Inspector 增"几何（世界坐标）"段 | 点显坐标、线显头/尾——调试要看真实 3D 数值 |

## 5. M2 设计固化（开发前把契约/风险/选型钉死）

| 改动 | 目的 |
| --- | --- |
| `print-linkage-tech-decisions.md` | 锁两仓库接缝：SSE / Python Bridge / occ-debug-mesh 归属 / print-mesh 格式 + 硬契约 + 风险表 |
| `m2-research-notes.md` | M2 风险全景、M2-1/2/3 白话+选型、几何域调研、DRAW 先例、缺陷诊断层 §9、二次排查 N1-N8 |
| 多轮 review（V1-V10 漏洞、N1-N8 二次排查） | 开发前排雷，避免边写边返工 |
| 锁定 M2-1/2/3 = 异步 renderer / 两段式 / 守护进程 | 解锁阶段 3-5 的实现形状 |

## 6. M2 阶段 1：协议先行

| 改动 | 目的 |
| --- | --- |
| `protocol/print-mesh.schema.json` | 固化派生网格格式：per-face 子网格 + edges + partial/failed_faces，世界 double、无 per-asset origin |
| `event.schema.json` 加 `defect` kind + payload | §9 缺陷诊断层的协议载体（category/source/severity/ref） |
| `session.schema.json` 加 `local_origin` | M2-6：会话级单一原点，viewer 降 Float32 前减 |
| `types.ts` 增 defect / PrintMesh / SessionInfo 类型 | 两端类型对齐，typecheck 守住契约 |
