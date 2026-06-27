"""ssi_probe(faceA, faceB) — S3 面面求交靶向子复现（A7 / G23）。

把相撞的两张面脱离 ChFi3d，单独跑 IntTools/GeomInt，记录交线条数 vs 期望
（docs/root-cause-verification.md §3 腿1 定位 + 腿2 机制）。
轻埋点：只需 capture 那两张面。占位：实现见 README §3 A7。
"""
from __future__ import annotations


def ssi_probe(face_a_brep: str, face_b_brep: str, *, expected_curves: int = 1) -> dict:
    """返回 {curve_count, expected, near_tangent, curves: [...]}。"""
    raise NotImplementedError("A7 — 见 agent/README.md §3 A7")
