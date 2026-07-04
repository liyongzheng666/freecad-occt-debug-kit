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


def triage_input(case_id: str, *, near_tangent_eps_deg: float = 10.0, timeout_s: int | None = None,
                 edge_index: int | None = None, edges: str | None = None) -> TriageReport:
    """跑 triage harness → TriageReport（min_dihedral_deg / min_support_curv_radius / near_tangent_pairs）。

    edge_index：G26 单边聚焦——1-based 边号。设了则只报该边的二面角/曲率（真实模型多边不误判）；
    None → 对全 shape 聚合（合成 case 现状，向后兼容）。
    edges：P2.2 vertex_probe——逗号 1-based blend 目标边集（"9,12"），透传 TRIAGE_EDGES，
    决定 vertex_report 的 n_blended；None → 全部边视为 blend（与 reproduce 无 REPRO_EDGES 一致）。
    """
    if timeout_s is None:                               # per-subprocess 预算：REPRO_TIMEOUT_S（P0 沙箱）→ 60（旧默认）
        timeout_s = int(os.environ.get("REPRO_TIMEOUT_S", "60"))
    bin_path = _resolve_freecadcmd()
    with tempfile.TemporaryDirectory(prefix="triage_") as d:
        out_json = Path(d) / "triage.json"
        env = dict(os.environ)
        env["PYTHONIOENCODING"] = "utf-8"
        env["TRIAGE_CASE"] = case_id
        env["TRIAGE_OUT_JSON"] = str(out_json)
        if edge_index is not None:
            env["TRIAGE_EDGE_INDEX"] = str(edge_index)
        else:
            env.pop("TRIAGE_EDGE_INDEX", None)          # 防继承外层 env 残留
        if edges:
            env["TRIAGE_EDGES"] = str(edges)
        else:
            env.pop("TRIAGE_EDGES", None)               # 防继承外层 env 残留

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
        # P1.3 输入质量四项（只报告/作证据，不进 S0/S2 判别——判别语义不动是硬约束）
        convexity=d_.get("convexity", {}),
        short_edges=d_.get("short_edges", []),
        sliver_faces=d_.get("sliver_faces", []),
        tolerance_outliers=d_.get("tolerance_outliers", []),
        vertex_report=d_.get("vertex_report", []),      # P2.2/S4 顶点构型
    )
