"""ssi_probe(faceA, faceB) — 面面求交靶向子复现：S3 机制证据（A7 / G23）。

脱离 ChFi3d 单独跑 OCCT 面面求交（env 驱动 `_ssi_harness.py` 在 FreeCADCmd 内
intersectSS + section + 近切角），返回 SSIReport。S3 失效签名 = 近切 + 期望接触却 0。

⚠️ 边界：本探针判"给定两张面的 SSI 是否退化"。从**活的失败 ChFi3d** 里 capture 那
两张 blend 面（占满失败现场的真实输入）属深埋点（occdbg/LLDB，A7 第一条 / G13），
不在此函数内——这里先把"机制证据"这一腿做实，capture 接缝后续接。
"""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path

from agent.contracts import SSIReport
from agent.tools.reproduce import _resolve_freecadcmd

_HARNESS = Path(__file__).resolve().parent / "_ssi_harness.py"


def _run(env_extra: dict, timeout_s: int) -> dict:
    bin_path = _resolve_freecadcmd()
    with tempfile.TemporaryDirectory(prefix="ssi_") as d:
        out_json = Path(d) / "ssi.json"
        env = dict(os.environ)
        env["PYTHONIOENCODING"] = "utf-8"
        env["SSI_OUT_JSON"] = str(out_json)
        env.update(env_extra)
        try:
            proc = subprocess.run(
                [str(bin_path), str(_HARNESS)], env=env,
                capture_output=True, text=True, timeout=timeout_s,
            )
        except subprocess.TimeoutExpired:
            return {"error": f"FreeCADCmd 超时(>{timeout_s}s)"}
        if not out_json.exists():
            tail = (proc.stderr or proc.stdout or "")[-300:]
            return {"error": f"harness 无输出(rc={proc.returncode}): {tail}"}
        return json.loads(out_json.read_text(encoding="utf-8"))


def _to_report(d: dict) -> SSIReport:
    if d.get("error"):
        # 工具失败不静默判 S3：给一个明确"未测出"的报告
        return SSIReport(
            n_curves_ss=-1, n_section_edges=-1, min_dihedral_deg=-1.0, gap=-1.0,
            near_tangent=False, degenerate_contact=False, s3_signature=False,
            notes="ssi_probe 失败：" + str(d["error"]),
        )
    return SSIReport(
        n_curves_ss=d["n_curves_ss"],
        n_section_edges=d["n_section_edges"],
        min_dihedral_deg=d["min_dihedral_deg"],
        gap=d["gap"],
        near_tangent=d["near_tangent"],
        degenerate_contact=d["degenerate_contact"],
        s3_signature=d["s3_signature"],
        notes=(f"intersectSS={d['n_curves_ss']} section_edges={d['n_section_edges']} "
               f"dihedral={d['min_dihedral_deg']}deg gap={d['gap']}"),
    )


def ssi_probe(
    face_a_brep: str | None = None,
    face_b_brep: str | None = None,
    *,
    fixture: str | None = None,
    tangent_eps_deg: float = 5.0,
    timeout_s: int = 60,
) -> SSIReport:
    """给两张面 BREP（face_a_brep/face_b_brep）或内置面对（fixture）跑 SSI。

    fixture: "transversal" | "secant" | "tangent" | "near-tangent"。
    """
    env_extra = {"SSI_TANGENT_EPS": str(tangent_eps_deg)}
    if face_a_brep and face_b_brep:
        env_extra["SSI_FACE_A"] = str(face_a_brep)
        env_extra["SSI_FACE_B"] = str(face_b_brep)
    elif fixture:
        env_extra["SSI_FIXTURE"] = fixture
    else:
        raise ValueError("需提供 (face_a_brep, face_b_brep) 或 fixture")
    return _to_report(_run(env_extra, timeout_s))
