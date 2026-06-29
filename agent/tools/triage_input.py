"""triage_input(case) — S0 输入预检 + 失效分类判别（A2 / G18）。

env 驱动 `_triage_harness.py` 在 FreeCADCmd 内算 case 每条边的二面角(近切度) + 支撑面
曲率半径，回 TriageReport。用途：把 fillet-notdone 的 S2 失败分成
  geometric（近切：min_dihedral 小 / 曲率：fillet_r > min_support_curv_radius）
  vs algorithmic（overflow：两圆角重叠，可 SSI 互裁）
——见 playbook fillet-failures.json 的失效三态。
"""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path

from agent.contracts import TriageReport
from agent.tools.reproduce import _resolve_freecadcmd

_HARNESS = Path(__file__).resolve().parent / "_triage_harness.py"


def triage_input(case_id: str, *, near_tangent_eps_deg: float = 10.0, timeout_s: int = 60) -> TriageReport:
    """跑 triage harness → TriageReport（min_dihedral_deg / min_support_curv_radius / near_tangent_pairs）。"""
    bin_path = _resolve_freecadcmd()
    with tempfile.TemporaryDirectory(prefix="triage_") as d:
        out_json = Path(d) / "triage.json"
        env = dict(os.environ)
        env["PYTHONIOENCODING"] = "utf-8"
        env["TRIAGE_CASE"] = case_id
        env["TRIAGE_OUT_JSON"] = str(out_json)
        try:
            proc = subprocess.run([str(bin_path), str(_HARNESS)], env=env,
                                  capture_output=True, text=True, timeout=timeout_s)
        except subprocess.TimeoutExpired:
            return TriageReport(min_dihedral_deg=-1.0, convexity={"error": "timeout"})
        if not out_json.exists():
            tail = (proc.stderr or proc.stdout or "")[-200:]
            return TriageReport(min_dihedral_deg=-1.0, convexity={"error": f"harness 无输出: {tail}"})
        d_ = json.loads(out_json.read_text(encoding="utf-8"))

    return TriageReport(
        near_tangent_pairs=[(p["edge"], p["dihedral_deg"]) for p in d_.get("near_tangent_edges", [])],
        min_dihedral_deg=d_.get("min_dihedral_deg", 180.0),
        min_support_curv_radius=d_.get("min_support_curv_radius"),
        min_support_curv_face=d_.get("min_support_curv_face"),
    )
