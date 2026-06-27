"""check_valid 集成自测（真跑 occ-debug-mesh）：python -m agent.tools.test_check_valid

用 occ-debug-mesh 内置夹具造已知 good/bad/selfx 几何，断言有效性判据正确；再跑一个
真实仓库 BREP（occt/data/occ/bottle.brep，若在）做 smoke。binary 不在 → SKIP 退 0
（无构建的机器不算失败）。这是 check_valid 自己的测试集（reward signal 必须配）。
"""
from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from agent.contracts import ValidityReport
from agent.tools.check_valid import _DEFAULT_BIN, _resolve_bin, check_valid

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _make(bin_path: Path, flag: str, out: Path) -> None:
    subprocess.run([str(bin_path), flag, str(out)], capture_output=True, text=True, check=True)


def main() -> int:
    try:
        bin_path = _resolve_bin()
    except FileNotFoundError as e:
        print(f"SKIP: {e}")
        return 0

    fails = []

    def check(name, cond):
        print(("PASS " if cond else "FAIL ") + name)
        if not cond:
            fails.append(name)

    with tempfile.TemporaryDirectory(prefix="cv_test_") as d:
        box, bad, selfx = Path(d) / "box.brep", Path(d) / "bad.brep", Path(d) / "selfx.brep"
        _make(bin_path, "--make-test-box", box)
        _make(bin_path, "--make-test-bad", bad)
        _make(bin_path, "--make-test-selfx", selfx)

        # 有效盒子 → valid，无 error、无自交
        r = check_valid(str(box))
        check("box → valid", r.valid is True)
        check("box → no invalid subshapes", r.invalid_subshapes == [])
        check("box → no self-intersection", r.self_intersections == [])

        # 开口壳当 solid → invalid（NotClosed / FreeEdge，open_boundary）
        r = check_valid(str(bad))
        check("bad → invalid", r.valid is False)
        check("bad → has error subshapes", len(r.invalid_subshapes) > 0)
        check("bad → open_boundary present",
              any(x.get("category") == "open_boundary" for x in r.invalid_subshapes))

        # 自交面 → invalid 且能挑出 self_intersection
        r = check_valid(str(selfx))
        check("selfx → invalid", r.valid is False)
        check("selfx → self_intersection captured", len(r.self_intersections) >= 1)
        check("selfx → SelfIntersectingWire status",
              any("SelfIntersect" in x.get("status", "") for x in r.self_intersections))

        # 工具崩了不能静默判有效：不存在的 brep → 抛 FileNotFoundError
        raised = False
        try:
            check_valid(str(Path(d) / "nope.brep"))
        except FileNotFoundError:
            raised = True
        check("missing brep → raises (not silent-valid)", raised)

    # 真实仓库几何 smoke（有就跑）
    bottle = _REPO_ROOT / "occt" / "data" / "occ" / "bottle.brep"
    if bottle.exists():
        r = check_valid(str(bottle))
        check("real bottle.brep → ValidityReport", isinstance(r, ValidityReport))
        print(f"     bottle.brep: valid={r.valid}  notes={r.notes}")
    else:
        print("note: occt/data/occ/bottle.brep 不在，跳过真实几何 smoke")

    print(f"\n{'ALL PASS' if not fails else str(len(fails)) + ' FAILED: ' + ', '.join(fails)}")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
