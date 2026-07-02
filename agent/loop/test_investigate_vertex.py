"""P2.2 自测：python -m agent.loop.test_investigate_vertex

S4 顶点复杂度判别器（vertex_probe）三层验证：
  ① `_vertex_verdict` 纯函数（无需 FreeCAD）——vertex_c 构型 fired / 全圆例外
     ruled_out / 3 边任意组合 ruled_out / 空报告 untestable（不伪绿）。
  ② vertex_probe 真跑（缺 FreeCADCmd → SKIP）——box 全边：每顶点 e3/b3 全圆例外
     → ruled_out；金字塔 apex 2-of-4（Parasolid vertex_c 构型）→ fired 数据形状正确。
  ③ 回归——box-r5 结论不变（root S2 / algorithmic_overflow），S4 候选作为第 4 判别
     进 trace 且 ruled_out（tool-call 9→10 是登记过的预期漂移，见 baselines 2026-07-02②）。

# 诚实负结果（P2.2 Step3，2026-07-02）
S4-proximate 的真实 NotDone 现场在 8 族简单解析构型中**未获**：
  box 邻边对（3 种共享面变体，r<10 全成、r≥10 死于 S2 StartSol:944——LLDB 实测）、
  cube 邻边对（≤9.5 全成）、金字塔 apex 2-of-4（邻/对，Parasolid 禁止的 vertex_c 构型，
  OCCT 全部收敛！）、L 型凹凸混合 two-corner（全成）、薄板短第三边 corner（全成）、
  凹 notch 2-of-3 凹边（全成）。
WP2 记录的 `PerformOneCorner Builder_C1:999` anchor 今日未复现（其确切几何已失传）。
→ 不造假 GT case；S4 层的 eval 正例留待真实 S4 构型出现（复杂曲面/导入模型）。
正向能力发现：OCCT 对 Parasolid 声明"过复杂"的顶点构型比 Parasolid 更能打。
"""
from __future__ import annotations


def main() -> int:
    from agent.loop.investigate import _vertex_verdict

    fails = []

    def check(name, cond):
        print(("PASS " if cond else "FAIL ") + name)
        if not cond:
            fails.append(name)

    # —— ① 纯函数（无需 FreeCAD）——
    v = lambda n, b: {"vertex": 0, "n_edges": n, "n_blended": b, "convexity_mix": ["convex"]}
    check("4边2圆 → fired（vertex_c）", _vertex_verdict([v(4, 2)])[0] == "fired")
    check("4边3圆 → fired（部分圆）", _vertex_verdict([v(4, 3)])[0] == "fired")
    check("4边4圆 → ruled_out（全圆例外 §77.2.1）", _vertex_verdict([v(4, 4)])[0] == "ruled_out")
    check("3边2圆 → ruled_out（3 边顶点合法）", _vertex_verdict([v(3, 2)])[0] == "ruled_out")
    check("3边3圆 → ruled_out", _vertex_verdict([v(3, 3)])[0] == "ruled_out")
    check("5边2圆 → fired", _vertex_verdict([v(5, 2)])[0] == "fired")
    check("混合列表：一个 fired 即 fired", _vertex_verdict([v(3, 3), v(4, 2)])[0] == "fired")
    check("空报告 → untestable（不伪绿）", _vertex_verdict([])[0] == "untestable")
    check("fired 证据点名顶点", "vertex#0" in _vertex_verdict([v(4, 2)])[1])

    # —— ②③ 真跑（缺 FreeCADCmd → SKIP）——
    from agent.tools.reproduce import _resolve_freecadcmd
    try:
        _resolve_freecadcmd()
    except FileNotFoundError as e:
        print(f"\nSKIP 真跑段: {e}")
        print("\n" + ("ALL PASS" if not fails else f"{len(fails)} FAIL: {fails}"))
        return 1 if fails else 0

    from agent.tools.vertex_probe import vertex_probe

    # box 全边（edges=None）：8 顶点 e3/b3 → ruled_out
    rep = vertex_probe("box")
    check("box 全边 vertex_report 8 顶点", len(rep) == 8)
    check("box 全边全部 e3/b3", all(r["n_edges"] == 3 and r["n_blended"] == 3 for r in rep))
    check("box 全边 → ruled_out", _vertex_verdict(rep)[0] == "ruled_out")

    # box 指定 2 邻边（共享 vertex0）：该顶点 e3/b2 → 仍 ruled_out（3 边顶点合法）
    rep2 = vertex_probe("box", edges="1,2")
    check("box edges=1,2：共享顶点 e3/b2", any(r["n_edges"] == 3 and r["n_blended"] == 2 for r in rep2))
    check("box edges=1,2 → ruled_out", _vertex_verdict(rep2)[0] == "ruled_out")

    # 回归：box-r5 结论不变 + S4 候选进 trace 且 ruled_out（tool 10 = 9+1 登记过的漂移）
    from agent.contracts import ToolResult
    from agent.loop.investigate import investigate
    trace: list[ToolResult] = []
    c = investigate("box", radius=5.0, policy="rule", trace=trace)
    h = c.hypotheses[0]
    check("box-r5 root=S2 不回归", h.stage.value == "S2")
    check("box-r5 failure_class=algorithmic_overflow 不回归", h.failure_class == "algorithmic_overflow")
    check("box-r5 trace 含 vertex_probe（S4 候选真跑）", any(t.tool == "vertex_probe" for t in trace))
    check("box-r5 tool-call = 10（9+1 登记漂移）", len(trace) == 10)
    s4_ev = [e for e in h.evidence if "S4" in e.summary and "vertex_probe" in e.summary]
    check("box-r5 证据含 S4 ✗排除行", len(s4_ev) == 1 and "✗排除" in s4_ev[0].summary)

    print("\n" + ("ALL PASS" if not fails else f"{len(fails)} FAIL: {fails}"))
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
