# 文档目录 —— Print / OCCT 几何调试套件

> 本目录是 FreeCAD / OpenCASCADE 几何算法调试系统的设计与交接文档。<br>
> 系统两半：**Kit**（`occ-debug-mesh` 等，把 BREP 转成网格/几何/缺陷数据）+ **Print**（浏览器交互 viewer，`tools/Print/`，pin SHA 的嵌套子仓）。<br>
> 工具自身说明见 [tools/occ-debug-mesh/README.md](../tools/occ-debug-mesh/README.md)；协议真源见 [tools/Print/protocol/](../tools/Print/protocol/)（`print-mesh` / `geom` / `event` / `session` schema）。

## 导出数据扩展（occ-debug-mesh，当前主线）

把导出从"够渲染"升级到"够调试几何算法"：点/边/面的拓扑+几何、3D↔UV 参数空间、NURBS 控制网。

| 文档 | 内容 |
| --- | --- |
| ★ [occ-debug-mesh-export-design.md](occ-debug-mesh-export-design.md) | **总设计 + 索引**：数据字典、schema 落点、§6 设计审查 12 条、**§8 切片索引（P0a/P0b/P0c）** |
| [uv-parametric-space-mapping.md](uv-parametric-space-mapping.md) | 3D↔UV 专题：缝边/周期/极点退化/裁剪，对照 OCCT/Parasolid/STEP |
| [occ-debug-mesh-p0a-geom-sidecar.md](occ-debug-mesh-p0a-geom-sidecar.md) | **P0a**：`geom.json` sidecar（顶点+容差、曲线/曲面类型、UV 边界+周期、pcurve 含缝/退化）。纯 C++、离线断言 |
| [occ-debug-mesh-p0b-uv-viewer.md](occ-debug-mesh-p0b-uv-viewer.md) | **P0b**：geom 接进交互 viewer（UvPanel 真画 per-face pcurve、Inspector 字段）+ 5 项配套修复 |
| [occ-debug-mesh-p0c-controlnet.md](occ-debug-mesh-p0c-controlnet.md) | **P0c**：NURBS 控制网导出 + 3D point_set/polyline 可视化 + 夹具教训 |

## Print ↔ Kit 联动与架构

| 文档 | 内容 |
| --- | --- |
| [print-linkage-tech-decisions.md](print-linkage-tech-decisions.md) | Print↔Kit 接缝契约、print-mesh 格式、风险表（端到端管道选型） |
| [occ-fillet-debug-agent-architecture.md](occ-fillet-debug-agent-architecture.md) | 圆角（ChFi3d）自动调试 + 几何可视化系统总架构 |
| [lldb-dynamic-geometry-capture.md](lldb-dynamic-geometry-capture.md) | LLDB 断点内动态采集几何（occdbg/Capture）设计 |
| [vscode-send-to-print.md](vscode-send-to-print.md) | VS Code Variables/Watch 右键"发送到 Print"交互编排 |

## 环境 / 调试基础

| 文档 | 内容 |
| --- | --- |
| [vscode-build-and-pixi.md](vscode-build-and-pixi.md) | VS Code 里编译/链接怎么跑起来（Pixi 工具链详解） |
| [occt-debugging.md](occt-debugging.md) | 通过 FreeCAD 调试本地可改的 OCCT（macOS/Pixi/Clang/CodeLLDB） |
| [vscode-debug-breakpoints.md](vscode-debug-breakpoints.md) | 断点管理与几何可视化调试 |

## 进度 / 研究

| 文档 | 内容 |
| --- | --- |
| [change-log.md](change-log.md) | **变更记录**（每批改动"做了什么→目的"）；§9 = 导出数据扩展进度索引 |
| [m2-research-notes.md](m2-research-notes.md) | M2 调研笔记：风险全景、M2-1/2/3 选型候选、M2-4/5/6/7 几何域调研（不下决议） |

---

新窗口接手路线：先读本目录 → `occ-debug-mesh-export-design.md`（总设计/索引）→ 对应阶段文档（P0a/P0b/P0c）即可拿到完整数据格式、实现、坑与复现命令。
