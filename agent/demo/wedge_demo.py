"""wedge_demo —— wedge fillet 真实失败现场 + agent 结论，整合进 Print viewer。

把三层东西喂进一个 Print session（`.occ-debug/sessions/wedge-demo`）：
  1. capture：从活的 StartSol 失败里抓 HS1/HS2 两支撑面（add shape + brep；daemon 网格化）
  2. ssi_probe：量两面近切角（机制证据）
  3. investigate：agent 离线判 S2，结论经 session.py emit 成 run_end（viewer 可 review）

跑：  python -m agent.demo.wedge_demo
看：  按末尾打印的命令起 daemon + bridge + viewer，浏览器开 http://127.0.0.1:5777/
      （或 `agent/demo/view.sh` 一键起）
"""
from __future__ import annotations

import json
from pathlib import Path

from agent.contracts import ToolResult
from agent.loop.investigate import format_conclusion, investigate
from agent.session import SessionWriter
from agent.tools import capture as capmod
from agent.tools.ssi_probe import ssi_probe

REPO = Path(__file__).resolve().parents[2]
SESSION = REPO / ".occ-debug" / "sessions" / "wedge-demo"
BREAKPOINT = "ChFi3d_Builder_2.cxx:944"   # StartSol echec —— 见 agent/cases/wedge-sliver.json

_WEDGE_FAIL = """import Part, FreeCAD as App
V = App.Vector
pts = [V(0,0,0), V(20,0,0), V(20,0,0.6)]
w = Part.Face(Part.makePolygon(pts+[pts[0]])).extrude(V(0,8,0))
try:
    w.makeFillet(1.0, w.Edges); print("FILLET_OK")
except Exception as e:
    print("FILLET_EXC", type(e).__name__)
"""


def _launch_hint() -> str:
    return (
        "\n──────── 看 Print viewer ────────\n"
        f"export OCC_DEBUG_SESSION={SESSION}\n"
        "scripts/occ-debug-start.sh start                 # daemon：把抓到的 brep 网格化\n"
        f"python3 tools/Print/bridge/bridge.py --session {SESSION} &   # bridge :7341\n"
        "( cd tools/Print && npm run dev )                # viewer :5777\n"
        "浏览器打开 http://127.0.0.1:5777/   或直接： agent/demo/view.sh\n"
    )


def main() -> int:
    SESSION.mkdir(parents=True, exist_ok=True)
    (SESSION / "assets").mkdir(exist_ok=True)
    (SESSION / "manifest.json").write_text(
        json.dumps({"session_id": "wedge-demo"}, ensure_ascii=False), encoding="utf-8")
    script = SESSION / "wedge_fail.py"
    script.write_text(_WEDGE_FAIL, encoding="utf-8")

    # 1) capture 真失败现场两支撑面（add shape + brep 进 session；daemon 会网格化）
    rep = None
    try:
        capmod._resolve()
        print("[demo] capture HS1/HS2 from live StartSol failure ...")
        breps = capmod.capture(
            str(script), BREAKPOINT,
            [("wedge/HS1", "HS1->Face()"), ("wedge/HS2", "HS2->Face()")],
            session_dir=str(SESSION),
        )
        print("[demo] captured:", list(breps))
        if "wedge/HS1" in breps and "wedge/HS2" in breps:
            rep = ssi_probe(breps["wedge/HS1"], breps["wedge/HS2"], tangent_eps_deg=10.0)
            print(f"[demo] ssi: near_tangent={rep.near_tangent} dihedral={rep.min_dihedral_deg}deg")
    except Exception as e:  # noqa: BLE001 — demo 容错：capture 不可用仍出结论
        print(f"[demo] capture 跳过（{type(e).__name__}: {e}）——仍出 agent 结论。")

    # 2) agent 离线诊断 wedge → 结论 emit 进 session（tool notes + run_end）
    print("[demo] investigate(wedge, r=1.0) ...")
    concl = investigate("wedge", radius=1.0, policy="rule", session_dir=str(SESSION))

    # 3) 补一条 note：把 SSI 机制(捕获实测)挂进 viewer
    if rep is not None:
        SessionWriter(SESSION, run_id="agent").emit_tool_result(ToolResult(
            tool="ssi_probe(captured HS1/HS2)", ok=True,
            summary=(f"真失败现场两支撑面近切 {rep.min_dihedral_deg}° → 半径 1.0 滚球塞不进"
                     f"（StartSol echec，S2 容纳不下）"),
            payload={"min_dihedral_deg": rep.min_dihedral_deg, "near_tangent": rep.near_tangent,
                     "gap": rep.gap, "n_section_edges": rep.n_section_edges},
            source="ChFi3d_Builder_2.cxx:944",
        ))

    print("\n" + format_conclusion(concl, "wedge", 1.0))
    print(_launch_hint())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
