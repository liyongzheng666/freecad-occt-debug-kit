#!/usr/bin/env bash
# run-agent-tests.sh — 跑 agent/ 全部 test_*.py 模块（人 & CI 共用的单一真源）。
#
# 纪律：每个测试都是纯 `python -m` 脚本（stdlib-only，无 pytest），缺二进制
# （FreeCADCmd/occ-debug-mesh/LLDB）时打印 `SKIP: …` 并 exit 0——故无 OCCT 的
# CI runner 上：纯离线测试真跑、需二进制的干净跳过、无一 hard-fail。
#
# 自动发现 `find agent -name test_*.py`（避免硬编列表漂移；天然排除 _*_harness.py
# 与 gitignore 的 agent/trajectories/）。真失败（非 SKIP 的非零退出）→ 本脚本 exit 1。
set -euo pipefail

cd "$(dirname "$0")/.."   # 仓库根（agent 是 package → python -m agent.… 可解析）

fail=0
ran=0
skip=0

while IFS= read -r f; do
  mod="${f%.py}"        # 去 .py 后缀
  mod="${mod//\//.}"    # agent/tools/test_x.py → agent.tools.test_x
  echo "── $mod"
  if out="$(python -m "$mod" 2>&1)"; then
    if printf '%s\n' "$out" | grep -q "^SKIP:"; then
      skip=$((skip + 1))
      printf '%s\n' "$out" | grep "^SKIP:" || true
    else
      ran=$((ran + 1))
    fi
  else
    printf '%s\n' "$out"
    echo "FAIL: $mod"
    fail=$((fail + 1))
  fi
done < <(find agent -name 'test_*.py' -not -path '*/__pycache__/*' | sort)

echo "──────────────────────────────"
echo "ran=$ran skip=$skip fail=$fail"

if [ "$fail" -ne 0 ]; then
  echo "有测试真失败（fail=$fail）"
  exit 1
fi

# 空转护栏：防止环境错误（如 agent 不可 import）导致"全 SKIP 的假绿"。
# 纯离线真跑集 ≈10，阈值取 6 留余量。
if [ "$ran" -lt 6 ]; then
  echo "护栏：真跑测试过少（ran=$ran < 6），CI 恐为空转——请检查 python/agent 环境"
  exit 1
fi

echo "全部通过（真跑 $ran，跳过 $skip）"
