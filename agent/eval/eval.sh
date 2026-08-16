#!/usr/bin/env bash
# eval.sh — 跑全 case 集，按失效类别分层打印根因指标（A4 / G5 / G11）。
#   指标：定位 / 失效分类 / 机制(代理) / 反事实(携带) / 校准 + tool-call 成本 + wall-clock。
#   GT：cases/*.json 的 ground_truth 四元组 + failure_class（root-cause-verification.md §6）。
#   缺 FreeCADCmd → 相关 case 标 SKIP（不假绿）；设 REPRO_FREECADCMD 指向 debug 构建。
# 实现见 agent/eval/runner.py；透传参数（如 --case box-r5 / --json out.json）。
set -euo pipefail
cd "$(dirname "$0")/../.."        # → repo 根，保证 `python -m agent.*` 可导入
exec python -m agent.eval.runner "$@"
