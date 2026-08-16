# 文档目录（Documentation index）—— 按读者分轨

> **New here?** Pick a track: [GEOMETRY](../GEOMETRY.md) (kernel/geometry developers) or [AGENT](../AGENT.md) (agent/harness/eval engineers). Dependencies & build chain: [dependencies.md](dependencies.md).
> **新读者先选轨道**：[GEOMETRY](../GEOMETRY.md)（几何/内核开发者）或 [AGENT](../AGENT.md)（agent/harness/eval 工程师）。依赖与构建链：[dependencies.md](dependencies.md)。

## 轨道 A —— 几何建模 / 内核（Geometry track）

| 文档 | 内容 |
| --- | --- |
| [../GEOMETRY.md](../GEOMETRY.md) | **轨道入口**：失效本体 → Parasolid 对照 → 缺陷导出 → LLDB 捕获的阅读顺序 |
| [../agent/playbook/blend-failure-ontology.md](../agent/playbook/blend-failure-ontology.md) | 失效本体 S0–S6 + ChFi3d 适配 + 失效四态分类学 |
| [fillet-para-study-and-agent-gap-plan.md](fillet-para-study-and-agent-gap-plan.md) | Parasolid Ch74/§77 故障分类 ↔ OCCT 行为 ↔ agent 阶段，含实跑验证的 STEP 例子 |
| [occ-debug-mesh-export-design.md](occ-debug-mesh-export-design.md) | 导出数据总设计 + 索引（数据字典、schema 落点、P0a/P0b/P0c 切片） |
| [uv-parametric-space-mapping.md](uv-parametric-space-mapping.md) | 3D↔UV 专题：缝边/周期/极点退化/裁剪，对照 OCCT/Parasolid/STEP |
| [lldb-dynamic-geometry-capture.md](lldb-dynamic-geometry-capture.md) | LLDB 断点内动态采集几何（occdbg/Capture）设计 |
| [occ-debug-mesh-p0a-geom-sidecar.md](occ-debug-mesh-p0a-geom-sidecar.md) · [p0b-uv-viewer.md](occ-debug-mesh-p0b-uv-viewer.md) · [p0c-controlnet.md](occ-debug-mesh-p0c-controlnet.md) | geom sidecar / UV viewer / NURBS 控制网 三切片 |
| [../tools/occ-debug-mesh/README.md](../tools/occ-debug-mesh/README.md) | occ-debug-mesh 设计说明 / 交接文档（夹具、输出格式、决策表） |

## 轨道 B —— Agent / Harness / Eval（Agent track）

| 文档 | 内容 |
| --- | --- |
| [../AGENT.md](../AGENT.md) | **轨道入口**：系统级架构图 → 契约 → 决策回路 → eval 的阅读顺序 + 业界概念对应 |
| [../agent/README.md](../agent/README.md) | agent 总览：5 分钟架构 + 快速开始 + 四条核心设计 + 分数现状 |
| [../agent/docs/root-cause-verification.md](../agent/docs/root-cause-verification.md) | 三腿验证方法学（定位/机制/反事实）+ 代理奖励陷阱 |
| [../agent/docs/progress.md](../agent/docs/progress.md) | 路线图 / 进度快照 / Gap Register / 操作备忘（推进档案） |
| [../agent/eval/baselines.md](../agent/eval/baselines.md) | 五维打分 + 弃权四态 + rule/LLM A/B 基线（实证数字 + 诚实边界） |
| [occ-fillet-debug-agent-architecture.md](occ-fillet-debug-agent-architecture.md) | 系统级架构：采集/埋点/agent/viewer 协作（设计基线） |

## 环境 / 构建（Environment）

| 文档 | 内容 |
| --- | --- |
| [dependencies.md](dependencies.md) | **唯一权威依赖图**：fork 钉板 / 构建链 / 运行时链 / 升级影响 / 断链症状 |
| [vscode-build-and-pixi.md](vscode-build-and-pixi.md) | VS Code 里编译/链接怎么跑起来（Pixi 工具链详解） |
| [occt-debugging.md](occt-debugging.md) | 通过 FreeCAD 调试本地可改的 OCCT（macOS/Pixi/Clang/CodeLLDB） |
| [vscode-debug-breakpoints.md](vscode-debug-breakpoints.md) | 断点管理与几何可视化调试 |
| [print-linkage-tech-decisions.md](print-linkage-tech-decisions.md) | Print↔Kit 接缝契约、print-mesh 格式、风险表 |
| [vscode-send-to-print.md](vscode-send-to-print.md) | VS Code 右键「发送到 Print」交互编排 |

## 进度 / 研究（Progress & research）

| 文档 | 内容 |
| --- | --- |
| [change-log.md](change-log.md) | 变更记录（每批改动「做了什么→目的」） |
| [m2-research-notes.md](m2-research-notes.md) | M2 调研笔记：风险全景、选型候选、几何域调研（不下决议） |
| [occ-mesh-daemon-plan.md](occ-mesh-daemon-plan.md) | mesh daemon 计划（BREP → 流式 mesh 事件） |

---

新窗口接手路线：按你的角色选轨道（GEOMETRY / AGENT），依赖问题先查 [dependencies.md](dependencies.md)，再进对应文档。
