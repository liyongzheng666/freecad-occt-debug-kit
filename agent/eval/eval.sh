#!/usr/bin/env bash
# eval.sh — 跑全 case 集，按难度分层打印根因指标（A4 / G5 / G11）。
#   指标：定位 / 机制 / 反事实 / 校准 + tool-call 成本 + wall-clock，分层报。
#   GT：cases/<id>/gt.json 四元组（docs/root-cause-verification.md §6）。
# 占位：实现见 agent/README.md §3 A4。
set -euo pipefail
echo "[agent/eval] stub —— A4 未实现；见 agent/README.md §3 A4" >&2
exit 1
