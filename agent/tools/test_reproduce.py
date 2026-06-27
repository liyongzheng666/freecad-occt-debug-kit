"""reproduce 集成自测（真跑 FreeCADCmd）：python -m agent.tools.test_reproduce

- benign 小圆角 → status ok / is_done / 产出 brep；其 brep 过 check_valid → valid（双工具组合）
- overflow 大圆角 → status failed / StdFail_NotDone / phase fillet_notdone
- record→replay：real 录制后，replay 不拉 FreeCAD 重现同一 RunEnd（G7）
FreeCADCmd 不在 → SKIP 退 0。
"""
from __future__ import annotations

import tempfile
from pathlib import Path

from agent.contracts import RunEnd
from agent.tools.check_valid import check_valid
from agent.tools.reproduce import _resolve_freecadcmd, reproduce


def main() -> int:
    try:
        _resolve_freecadcmd()
    except FileNotFoundError as e:
        print(f"SKIP: {e}")
        return 0

    fails = []

    def check(name, cond):
        print(("PASS " if cond else "FAIL ") + name)
        if not cond:
            fails.append(name)

    with tempfile.TemporaryDirectory(prefix="repro_test_") as d:
        rec = Path(d) / "fixtures"

        # —— benign：跑完、产出形状 ——
        r = reproduce("box", radius=2.0, out_dir=str(Path(d) / "benign"), record_dir=str(rec))
        check("benign → status ok", r.status == "ok")
        check("benign → is_done", r.is_done is True)
        check("benign → bad_shape written", r.bad_shape and Path(r.bad_shape).exists())

        # —— 组合 reproduce→check_valid：产出 brep 真几何有效 ——
        if r.bad_shape and Path(r.bad_shape).exists():
            v = check_valid(r.bad_shape)
            check("benign brep → check_valid valid", v.valid is True)

        # —— overflow：算法失败（NotDone）——
        r2 = reproduce("box", radius=1000.0, out_dir=str(Path(d) / "of"))
        check("overflow → status failed", r2.status == "failed")
        check("overflow → not is_done", r2.is_done is False)
        check("overflow → StdFail_NotDone", "NotDone" in (r2.exception or ""))
        check("overflow → phase fillet_notdone", r2.phase == "fillet_notdone")

        # —— record→replay：不拉 FreeCAD 重现 benign 的 RunEnd ——
        rp = reproduce("box", radius=2.0, backend="replay", record_dir=str(rec))
        check("replay → status ok (no FreeCAD)", rp.status == "ok")
        check("replay → bad_shape persisted in record_dir",
              rp.bad_shape and Path(rp.bad_shape).exists() and "fixtures" in rp.bad_shape)
        check("replay → RunEnd type", isinstance(rp, RunEnd))

    print(f"\n{'ALL PASS' if not fails else str(len(fails)) + ' FAILED: ' + ', '.join(fails)}")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
