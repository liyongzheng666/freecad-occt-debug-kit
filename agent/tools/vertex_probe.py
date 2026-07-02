"""vertex_probe(case, edges) — S4 顶点构型探针（P2.2 / G3，免埋点）。

薄封装：走 triage harness（TRIAGE_EDGES）取目标 blend 边端点的顶点构型
`[{vertex, n_edges, n_blended, convexity_mix}]`。**判定不在这里**——
fired/ruled_out/untestable 的裁定是纯函数 `investigate._vertex_verdict`
（与 `_ssi_verdict` 同模式，可离线单测）。

Parasolid 对照（para-study §3.1 vertex_c / §1.5）：顶点"过复杂"的构型 =
4+ 边顶点且其中 2 条及以上（但非全部）被圆角——全部圆角是合法例外
（Parasolid §77.2.1）。OCCT 落点 `PerformOneCorner/TwoCorner/ThreeCorner`
（truth anchor：ChFi3d_Builder_C1.cxx:999，WP2）。
"""
from __future__ import annotations

from agent.tools.triage_input import triage_input


def vertex_probe(case_id: str, edges: str | None = None, *, timeout_s: int = 60) -> list[dict]:
    """返回顶点构型列表（只含"至少 1 条 blend 边落脚"的顶点）。

    edges：逗号 1-based blend 目标边集；None → 全部边视为 blend
    （与 reproduce 无 REPRO_EDGES 语义一致，合成全边 case 直接可用）。
    harness 失败时 triage_input 返回 error 报告 → vertex_report 为空，
    由调用方（_vertex_verdict）判 untestable，不伪绿。
    """
    t = triage_input(case_id, edges=edges, timeout_s=timeout_s)
    if t.convexity.get("error"):                       # harness 超时/无输出的错误通道
        raise RuntimeError(f"triage harness 失败：{t.convexity['error']}")
    return t.vertex_report
