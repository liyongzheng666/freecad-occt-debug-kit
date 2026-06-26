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

## 7. M2 阶段 2：occ-debug-mesh 决策（已确认，对照 OCCT 自身做法）

| 点 | 决策 | 依据 |
| --- | --- | --- |
| deflection | OCCT **相对挠度，系数 0.002**，角 **0.5 rad**（钳 ≥0.2），parallel | OCCT 默认 DeviationCoefficient 0.001 / Angle 0.5，为调试快放粗一档 |
| 法线 | 缺时调 **`BRepLib_ToolTriangulatedShape::ComputeNormals`**（同 AIS_Shape），按 `REVERSED`/镜像翻向 | OCCT 自带、跨光滑边平滑，不手搓 |
| 缺陷遍历 | `TopExp::MapShapes` 子形状 → `BRepCheck_Analyzer.Result(sub)` → 遍历 `BRepCheck_ListOfStatus`，状态码→`defect.category` | `BRepCheck_Result` 嵌套 map 结构；MapShapes 索引即 face/edge_id |
| 边离散 | 面上边复用 `Poly_PolygonOnTriangulation`；裸 Edge/Wire 用 `GCPnts_QuasiUniformDeflection` | 前者 mesh-依赖且与面网格重合，后者独立、无需网格（接 V4） |

> Pre-flight：OCCT V7_8_1 已建（occt/install/debug，cmake 包在 occt/build/debug），上述全部头文件+方法签名在 7.8.1 确认存在；Poly_Triangulation 用 1-based `Node(i)`/`Triangle(i)`/`Normal(i)` 新 API；编译器用 pixi clang 18。

## 8. occ-debug-mesh 实现进度

| 改动 | 目的 |
| --- | --- |
| occ-debug-mesh 骨架 + CMake + 构建脚本 | 证明工具链：链本地 OCCT、读 BREP→网格化→per-face 世界坐标 JSON。盒子自测 6 面、bbox 精确 |
| review 修复（去冗余 Perform、NaN/Inf 守卫、退化节点→failed_faces） | 健壮性；盒子 6 面法线实测外向（REVERSED 翻转正确） |
| **缺陷遍历**（`BRepCheck_Analyzer` → `defect` sidecar） | 把工具从"查看器"变"诊断器"：检出哪类缺陷+ref。**关键**：缺陷常存"子形状在父语境下"的 context 状态里，不能只看 `Status()`、不能用 `IsValid(sub)` 门控 |
| `defect.category` 加 `other`；`--diagnose`/`--make-test-bad` 工具 | BRepCheck ~50 状态码只映射常见的、其余落 other 不丢；开口盒子(NotClosed→open_boundary)离线验收 |
| 复杂边界场景测试（`--make-test-located/selfx/edge`）+ 两处修复 | review 发现简单盒子没测到的假设：①**带 Location 的世界坐标**——旋转90°+平移后 bbox 精确吻合，M2-4 命脉验证通过；②`statusName` 改全枚举命名（未映射码不再塌成"Other"丢信息）；③wire 缺陷**用祖先查找挂到父面 face_id**（M2-5）。裸边优雅退化 |
| **边离散落地**（`collectEdges`：面上边 `PolygonOnTriangulation` / 裸边 `GCPnts`）+ NURBS 夹具 + `verify-occ-debug-mesh.sh` | 填上 `edges[]`；`--make-test-nurbs/bspline-edge` 验证曲线离散（多点折线）；28 项离线断言一键回归 |
| viewer 接入（`mesh-to-session.py` → Bridge → 真 M1 viewer）+ 面 renderer / 虚线 bbox / 粗线 / 单对象显隐 | 把 occ-debug-mesh 输出喂进交互 viewer；补面渲染、per-entity 可见性等 viewer 缺口 |

## 9. 导出数据扩展（设计 + P0a/P0b/P0c 已落地）

| 改动 | 目的 |
| --- | --- |
| 设计文档 [occ-debug-mesh-export-design.md](occ-debug-mesh-export-design.md) + [uv-parametric-space-mapping.md](uv-parametric-space-mapping.md) | 把导出从"够渲染"升到"够调试"；mesh + geom sidecar 分离；两轮设计审查（点去重 vs per-face UV、缝边两 pcurve、连续性低报、跨快照身份…）；3D↔UV 专题对照 OCCT/Parasolid/STEP；切片 P0a→P0b→P0c。**设计文档 §8 为索引** |
| **P0a 落地** → [occ-debug-mesh-p0a-geom-sidecar.md](occ-debug-mesh-p0a-geom-sidecar.md) | `geom.json` sidecar（顶点+容差、类型、`uv_bounds`+周期、边 flags/邻接、**pcurve UV** 含缝/退化）+ 圆柱/球/环夹具 + 断言。未碰 viewer |
| **P0b 落地** → [occ-debug-mesh-p0b-uv-viewer.md](occ-debug-mesh-p0b-uv-viewer.md) | geom 接进交互 viewer（3D→2D）：`UvPanel` 真画 per-face pcurve、`Inspector` 显字段。配套：UV 实时刷新、换形状免刷新（reset 语义）、隐藏全部、**闭合边按面分图修复**、锁定可设置 |
| **P0c 落地** → [occ-debug-mesh-p0c-controlnet.md](occ-debug-mesh-p0c-controlnet.md) | NURBS 控制网导出（曲线极点多边形 / 曲面极点网，世界坐标）+ viewer point_set/polyline（默认隐藏）+ Inspector degree/grid/poles。夹具改直接构造避免插值过冲 |
