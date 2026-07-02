"""falsegreen_probe(case, edges, result_brep, face_ids) — 假绿判别量采集（决策空间②）。

薄封装：env 驱动 `_falsegreen_harness.py` 在 FreeCADCmd 内量两组判别量：
  support_types    blend 边支撑面类型（S2-bsurf 候选：参数面上 blend 面构造写坏几何）
  defect_locality  缺陷面到自由端/边中点距离（S4-endcap 候选：端盖构造在曲面终止处写坏几何）
  free_ends        自由端（全边/闭链 blend 无自由端 → 端盖机器不参与 → S4 候选不适用）

裁定不在这里——fired/ruled_out/untestable 是 investigate 的 `_fg_*_verdict` 纯函数
（与 _ssi_verdict/_vertex_verdict 同模式）。判别阈值实证锚点（2026-07-02 locality 实测）：
E7 cylboss 端盖缺陷 d_end=0.000（fired）/ E4 凹槽 F11 d_end=14.0（ruled_out）/
E8 loft d_end≈1.9（不触 S4，S2-bsurf 更 distal 先 fired）。
"""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path

from agent.tools.reproduce import _resolve_freecadcmd

_HARNESS = Path(__file__).resolve().parent / "_falsegreen_harness.py"


def falsegreen_probe(case_id: str, *, edges: str | None = None,
                     result_brep: str | None = None, face_ids: list[str] | None = None,
                     timeout_s: int = 60) -> dict:
    """返回 {support_types, free_ends, n_blended, defect_locality}；harness 失败抛 RuntimeError。"""
    bin_path = _resolve_freecadcmd()
    with tempfile.TemporaryDirectory(prefix="fg_") as d:
        out_json = Path(d) / "fg.json"
        env = dict(os.environ)
        env["PYTHONIOENCODING"] = "utf-8"
        env["FG_CASE"] = case_id
        env["FG_OUT_JSON"] = str(out_json)
        for key, val in (("FG_EDGES", edges),
                         ("FG_RESULT_BREP", result_brep),
                         ("FG_FACE_IDS", ",".join(face_ids or []))):
            if val:
                env[key] = str(val)
            else:
                env.pop(key, None)                       # 防继承外层 env 残留
        try:
            proc = subprocess.run([str(bin_path), str(_HARNESS)], env=env,
                                  capture_output=True, text=True, timeout=timeout_s)
        except subprocess.TimeoutExpired:
            raise RuntimeError(f"falsegreen harness 超时(>{timeout_s}s)")
        if not out_json.exists():
            tail = (proc.stderr or proc.stdout or "")[-200:]
            raise RuntimeError(f"falsegreen harness 无输出: {tail}")
        return json.loads(out_json.read_text(encoding="utf-8"))
