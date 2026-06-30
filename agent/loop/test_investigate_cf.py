"""A7 WP3 自测：python -m agent.loop.test_investigate_cf

互斥靶向反事实（降半径 / 扰容差，root-cause §4 腿3）：
  _counterfactual_verdict —— 两修法成功组合 → S2 / S3 / S2->S3 / inconclusive（纯函数，无 FreeCAD）；
  _probe_tolerance_fix —— wedge 近切：扰容差(≤0.1)无效 → None → 坐实 S2（需 FreeCADCmd，缺则 SKIP）。
"""
from __future__ import annotations

import tempfile

from agent.loop.investigate import _counterfactual_verdict, _probe_tolerance_fix


def main() -> int:
    fails = []

    def check(name, cond):
        print(("PASS " if cond else "FAIL ") + name)
        if not cond:
            fails.append(name)

    # —— 纯组合判别（无需 FreeCAD）——
    check("降半径✓ 容差✗ → S2", _counterfactual_verdict(True, None)[0] == "S2")
    check("降半径✗ 容差✓ → S3", _counterfactual_verdict(False, 0.01)[0] == "S3")
    check("降半径✓ 容差✓ → S2->S3", _counterfactual_verdict(True, 0.01)[0] == "S2->S3")
    check("均✗ → inconclusive", _counterfactual_verdict(False, None)[0] == "inconclusive")
    # S2 verdict 文案排除 S3，且不预设几何/算法子类
    s2_why = _counterfactual_verdict(True, None)[1]
    check("S2 文案点名排除 S3", "S3" in s2_why and "排除" in s2_why)

    # —— wedge 集成：扰容差无效（近切几何，容差不敏感）→ None → 坐实 S2 ——
    try:
        from agent.tools.reproduce import _resolve_freecadcmd
        _resolve_freecadcmd()
    except FileNotFoundError as e:
        print(f"\nSKIP wedge perturb_tolerance 集成: {e}")
        print(f"\n{'ALL PASS' if not fails else str(len(fails)) + ' FAILED: ' + ', '.join(fails)}")
        return 1 if fails else 0

    with tempfile.TemporaryDirectory(prefix="cf_test_") as d:
        tol_fix = _probe_tolerance_fix("wedge", 1.0, d, [], False)
        check("wedge 扰容差无效 → None（容差不敏感）", tol_fix is None)
        check("wedge → 互斥反事实判 S2", _counterfactual_verdict(True, tol_fix)[0] == "S2")

    print(f"\n{'ALL PASS' if not fails else str(len(fails)) + ' FAILED: ' + ', '.join(fails)}")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
