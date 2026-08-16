---
name: Bug report / 问题复现
about: 报告圆角诊断、occ-debug-mesh 或构建相关的问题（带复现包，作者可快速复现）
title: "[bug] "
labels: ""
assignees: ""
---

> **Reproduction-first**: this project is maintained on **macOS Apple Silicon only**. Please fill in the reproduction package below — it lets the maintainer reproduce within minutes instead of asking round-trips.
> **复现优先**：本项目仅维护 **macOS Apple Silicon**。请带全下面的复现包——作者可以在几分钟内进入同一状态，不用来回追问。

## 复现包（Reproduction package）

**A. 环境（必填）**

| 项 | 值（在本仓库根目录跑这些命令） |
| --- | --- |
| macOS 版本 / 芯片 | `sw_vers` + `uname -m` 输出 |
| OCCT 版本 | `git -C occt describe --tags` |
| FreeCAD 版本 | `git -C FreeCAD rev-parse --short HEAD` |
| 工作区自检 | `bash scripts/workspace-doctor.sh` 的输出（贴关键行） |

**B. 触发条件（必填，二选一）**

- 合成 case：诊断命令（如 `python -m agent.loop.investigate box 5`）
- 真实模型：把 **BREP/STEP 文件作为附件上传**（或 FCStd 里的 Part::Feature 导出），并给出：
  - 圆角的**边号**（GUI 里 EdgeN，1-based）+ **半径**
  - 你的诊断命令（如 `python -m agent.loop.investigate "brep:/abs/m.brep" 5 --edges 3`）

**C. 期望 vs 实际（必填）**

- 期望行为：
- 实际行为（贴完整输出/报错）：
- 是否稳定复现（重跑 N 次中几次出现）：

**D. 问题归类（帮助分流，可多选）**

- [ ] 环境/构建（bootstrap/workspace-doctor 报错）
- [ ] occ-debug-mesh（转换/缺陷输出不对）
- [ ] agent 诊断结论错误（附：你认为正确的根阶段/失效类别是什么）
- [ ] eval/测试（baselines 漂移、测试失败）
- [ ] 文档（链接 404 / 描述与实际不符）

> 提示：边号坑——STEP 导出+重读会重编号边，请以读回后的 shape 复核边号（见 agent/README 快速开始）。
