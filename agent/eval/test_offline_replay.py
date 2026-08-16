"""tool-layer 离线重放自测（P1b C1）：python -m agent.eval.test_offline_replay

证明两件事：
  ① **字节级一致**：record 一遍（real + REPRO_RECORD_DIR）再 replay 一遍（REPRO_BACKEND=replay），
     两次 conclusion_to_dict 逐位相同。
  ② **真离线**：replay 时把 FreeCADCmd / occ-debug-mesh 指向**不存在**路径，仍产出同一 Conclusion
     → 铁证没拉起任何 OCCT 栈（不是"碰巧二进制在"）。

**当前覆盖 clean case**（诊断路径只用 reproduce + check_valid，两者已双后端）。缺陷 case 的全离线
还需 triage/vertex/ssi/falsegreen 也上双后端 + brep 路径可移植（跨机相对化）——见 docs C1 scope。
本测试证明 record/replay **模式**字节级成立，是那个增量的地基。

缺 FreeCADCmd → SKIP（record 一遍需真跑）。
"""
from __future__ import annotations

import os
import tempfile

from agent.eval.gen_cases import generate
from agent.loop.investigate import investigate
from agent.trajectory import conclusion_to_dict


def _set(k, v):
    if v is None:
        os.environ.pop(k, None)
    else:
        os.environ[k] = v


def main() -> int:
    try:
        from agent.tools.reproduce import _resolve_freecadcmd
        _resolve_freecadcmd()
    except FileNotFoundError as e:
        print(f"SKIP: {e}（record 一遍需 FreeCADCmd）")
        return 0

    fails = []

    def check(name, cond):
        print(("PASS " if cond else "FAIL ") + name)
        if not cond:
            fails.append(name)

    allc = dict(generate())
    picks = [c for c in sorted(allc)
             if c.startswith("gen-clean-box") or c.startswith("gen-clean-pocket")][:2]
    check("有 clean case 可测", len(picks) >= 1)

    saved = {k: os.environ.get(k) for k in
             ("REPRO_BACKEND", "REPRO_RECORD_DIR", "REPRO_FREECADCMD", "OCC_DEBUG_MESH_BIN")}
    try:
        with tempfile.TemporaryDirectory(prefix="offline_replay_") as rec:
            for cid in picks:
                run = allc[cid]["agent_run"]
                kw = dict(radius=run["radius"], op=run.get("op", "fillet"))

                # ① RECORD：real + 录制
                _set("REPRO_BACKEND", None)
                _set("REPRO_RECORD_DIR", rec)
                live = conclusion_to_dict(investigate(run["case"], **kw))

                # ② REPLAY：离线（二进制指向不存在）+ 读录制
                _set("REPRO_BACKEND", "replay")
                _set("REPRO_FREECADCMD", "/nonexistent/FreeCADCmd")
                _set("OCC_DEBUG_MESH_BIN", "/nonexistent/occ-debug-mesh")
                rep = conclusion_to_dict(investigate(run["case"], **kw))

                _set("REPRO_BACKEND", None)          # 复位供下一 case record
                _set("REPRO_FREECADCMD", saved["REPRO_FREECADCMD"])
                _set("OCC_DEBUG_MESH_BIN", saved["OCC_DEBUG_MESH_BIN"])

                check(f"{cid[:34]}: replay==live 字节一致 且 离线（二进制不存在仍产出）", rep == live)
    finally:
        for k, v in saved.items():
            _set(k, v)

    print("全部通过" if not fails else f"有 {len(fails)} 项失败")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
