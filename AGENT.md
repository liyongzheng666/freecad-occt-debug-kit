# Agent 开发者轨道（Agent Track）

> **For agent / harness / eval engineers**: this repo contains a complete, honest *root-cause investigation agent* — deterministic tool layer, one decision seam shared by rule & LLM policies, 5-dimension scoring with abstention accounting, record/replay determinism, sandboxed parallel eval, and a review→GT annotation loop. If you build agents or eval harnesses, start here.
> **面向 agent / harness / eval 工程师**：一个完整的根因调研 agent——确定性工具层、rule/LLM 共用的单一决策接缝、五维打分 + 弃权计量、record/replay 确定性、沙箱并行 eval、review→GT 标注闭环。做 agent 或评测基建的，从这里开始。

## 系统级架构（System view）

```mermaid
flowchart LR
    subgraph TOOLS[确定性工具层 tools/]
        REP[reproduce<br/>FreeCADCmd 真跑]
        VAL[check_valid<br/>几何有效性判据]
        TRI[triage_input<br/>近切/曲率预检]
        SSI[ssi_probe<br/>面面求交子复现]
        CAP[capture<br/>LLDB + env_emit 现场]
    end
    subgraph LOOP[决策回路 loop/]
        INV[investigate<br/>observe→判别→分类→反事实→结论]
        DEC[decide state<br/>rule | llm 同签名]
    end
    subgraph EVAL[eval/]
        RUN[runner<br/>166 case 并行+沙箱+隔离]
        SCO[scorer 五维+弃权四态]
        BASE[baselines 门<br/>CI 冻结回归]
    end
    subgraph LOOP2[闭环]
        SESS[session.py 事件发射缝]
        TRAJ[trajectory.py 轨迹重放]
        REV[review.py 人审→GT]
    end
    PB[(playbook<br/>决策表/失效本体)] --> LOOP
    LOOP --> TOOLS
    LOOP --> SESS --> TRAJ --> REV --> EVAL
    LOOP --> EVAL
    EVAL --> BASE
```

## 阅读路径（按这个顺序）

| 顺序 | 读什么 | 为什么读 |
| --- | --- | --- |
| 1 | [agent/README.md](agent/README.md) | 5 分钟架构图 + 快速开始 + 四条核心设计 |
| 2 | [agent/docs/root-cause-verification.md](agent/docs/root-cause-verification.md) | **三腿验证**（靶向子复现 / 中间态证据 / 互斥反事实）+ 代理奖励陷阱（`IsDone()`） |
| 3 | [agent/contracts.py](agent/contracts.py) | 跨层 typed 契约（RunEnd / Conclusion / GroundTruth / Review）——工具/回路/eval 的唯一接口 |
| 4 | [agent/loop/investigate.py](agent/loop/investigate.py) + [decide_rule.py](agent/loop/decide_rule.py) / [decide_llm.py](agent/loop/decide_llm.py) | 决策回路与**唯一策略接缝**：模型只在 `decide(state)` 出现 |
| 5 | [agent/eval/baselines.md](agent/eval/baselines.md) | 五维打分 + 弃权四态 + rule/LLM A/B 的实证数字与诚实边界 |
| 6 | [agent/session.py](agent/session.py) / [trajectory.py](agent/trajectory.py) / [review.py](agent/review.py) | 事件发射缝 / 轨迹离线重放重打分 / 人工 review→GT 标注（数据飞轮） |
| 7 | [docs/occ-fillet-debug-agent-architecture.md](docs/occ-fillet-debug-agent-architecture.md) | 系统级架构：采集/埋点/agent/viewer 如何协作 |

## 与业界概念的对应（怎么讲给别人听）

| 本仓库的实现 | 业界概念 |
| --- | --- |
| `check_valid` 几何有效性判据（禁用 `IsDone()`） | **verifiable reward** / 防 **reward hacking**（Goodhart） |
| 三腿验证（定位+机制+反事实） | **process supervision**（不只 outcome 对错，还要中间态证据） |
| `review.py` 人审 → `GroundTruth` 标注 → 一致率 | **data flywheel** / RLHF 标注管线 |
| reproduce / decide 的 real/replay 双后端 | **确定性 eval**（record/replay，不用 temperature=0） |
| runner 并行 166 case + per-case 沙箱 + 失败隔离 | **rollout infra**（10.8× 实测） |
| 弃权四态（false_commit / wrong_abstain …） | **calibrated confidence** / abstention 计量 |

## 快速开始

```bash
python -m agent.loop.investigate box 5                 # 一条命令出根因诊断
bash agent/eval/eval.sh                                # 五维 + 弃权四态分层打分
bash scripts/run-agent-tests.sh                        # 24 测试模块（离线可跑，CI 门）
```

## 诚实边界（README 之外的实话）

- **决策空间小**：当前 playbook 3–4 候选，rule 臂顺序穷尽已近最优；LLM 臂质量逐位持平、只在假绿分支靠语义早停省了 6% tool-call。要让 LLM 显价值需要更大决策空间的 case（路线图 §5 已列）。
- **合成分布 ≠ 真实分布**：13 个手工 GT + 166 参数化 case 中，真实 STEP 资产 6 个（4 个进 eval）；真实世界覆盖是已知短板（[progress](agent/docs/progress.md) §7 B1）。
- **机制真分只覆盖 4/13 case**；abstention precision 0.50（探针分辨率极限，非策略问题）。

> 环境仅维护 **macOS Apple Silicon**；离线路径任意平台（CI）。依赖关系见 [docs/dependencies.md](docs/dependencies.md)。提问题带复现包（[.github/ISSUE_TEMPLATE.md](.github/ISSUE_TEMPLATE.md)）。
