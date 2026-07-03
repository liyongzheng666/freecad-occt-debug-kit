"""G26 真实模型输入 adapter 自测：python -m agent.tools.test_g26_realmodel

两段：
1) 纯逻辑（始终跑，无需 FreeCAD）——_safe_token 文件名消毒 + _single_edge_index。
2) 真跑 round-trip（缺 FreeCADCmd → SKIP 退 0）——用现有 export-only 分支把合成 wedge 导出成
   真 .brep（再顺带转一个 .step），走 brep:/step: 前缀载回来诊断，断言结论与合成 wedge 一致。
   这是自足回归：不依赖外部模型文件，全链路（build_shape 前缀分支 + REPRO_EDGES + triage 单边聚焦）
   都被覆盖。不断言 entity token 相等（brep/step 可能重排边序，见计划 B3）。
"""
from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from agent.loop.investigate import _single_edge_index
from agent.tools.reproduce import _resolve_freecadcmd, _safe_token, reproduce
from agent.tools.triage_input import triage_input
from agent.loop.investigate import investigate


def _export_step(brep_path: str, step_path: str, timeout_s: int = 60) -> bool:
    """一次性 FreeCADCmd 脚本把 brep 转 step（测 step: 前缀走同一 Part.Shape().read()）。"""
    bin_path = _resolve_freecadcmd()
    script = (
        "import Part\n"
        "s = Part.Shape()\n"
        f"s.read({brep_path!r})\n"
        f"s.exportStep({step_path!r})\n"
    )
    sp = Path(tempfile.mkdtemp(prefix="g26conv_")) / "conv.py"
    sp.write_text(script, encoding="utf-8")
    subprocess.run([str(bin_path), str(sp)], capture_output=True, text=True, timeout=timeout_s)
    return Path(step_path).exists()


def _make_fcstd(fcstd_path: str, timeout_s: int = 60) -> bool:
    """建含两个具名 Part::Feature（BoxA 大 / BoxB 小）的 FreeCAD 文档并存盘（测 O2 fcstd: 直读）。"""
    bin_path = _resolve_freecadcmd()
    script = (
        "import FreeCAD as App, Part\n"
        "doc = App.newDocument('t')\n"
        "a = doc.addObject('Part::Feature', 'BoxA'); a.Shape = Part.makeBox(10, 20, 30)\n"
        "b = doc.addObject('Part::Feature', 'BoxB'); b.Shape = Part.makeBox(5, 5, 5)\n"
        "doc.recompute()\n"
        f"doc.saveAs({fcstd_path!r})\n"
    )
    sp = Path(tempfile.mkdtemp(prefix="g26fcstd_")) / "mk.py"
    sp.write_text(script, encoding="utf-8")
    subprocess.run([str(bin_path), str(sp)], capture_output=True, text=True, timeout=timeout_s)
    return Path(fcstd_path).exists()


def main() -> int:
    fails = []

    def check(name, cond):
        print(("PASS " if cond else "FAIL ") + name)
        if not cond:
            fails.append(name)

    # —— 1) 纯逻辑（无需 FreeCAD）——
    # _safe_token：合成 id 原样（保回归零漂移），真实模型路径 → filename-safe 且确定
    check("_safe_token box 原样", _safe_token("box") == "box")
    check("_safe_token box-flat 原样", _safe_token("box-flat") == "box-flat")
    check("_safe_token wedge-thin 原样", _safe_token("wedge-thin") == "wedge-thin")
    tok = _safe_token("brep:/Users/x/My Model.brep")
    check("_safe_token 真实路径无路径分隔符", "/" not in tok and ":" not in tok and " " not in tok)
    check("_safe_token 确定（同入同出）", tok == _safe_token("brep:/Users/x/My Model.brep"))
    check("_safe_token 不同路径不同 token",
          _safe_token("brep:/a/m.brep") != _safe_token("brep:/b/m.brep"))

    # _single_edge_index：恰一条边 → 1-based int；多边/空/非法 → None（triage 回落聚合）
    check("_single_edge_index None→None", _single_edge_index(None) is None)
    check("_single_edge_index ''→None", _single_edge_index("") is None)
    check("_single_edge_index '3'→3", _single_edge_index("3") == 3)
    check("_single_edge_index ' 3 '→3", _single_edge_index(" 3 ") == 3)
    check("_single_edge_index '1,4'→None(多边)", _single_edge_index("1,4") is None)
    check("_single_edge_index 'x'→None", _single_edge_index("x") is None)

    # —— 2) 真跑 round-trip（缺 FreeCADCmd → SKIP，不算失败）——
    try:
        _resolve_freecadcmd()
    except FileNotFoundError as e:
        print(f"\nSKIP round-trip 集成: {e}")
        print(f"\n{'ALL PASS' if not fails else str(len(fails)) + ' FAILED: ' + ', '.join(fails)}")
        return 1 if fails else 0

    tmp = tempfile.mkdtemp(prefix="g26test_")
    # 用现有 radius<=0 export-only 分支导出真 wedge solid（无需新 harness）
    brep = reproduce("wedge", radius=0.0, out_dir=tmp).bad_shape
    check("wedge 导出 brep 落盘", bool(brep) and Path(brep).exists())
    case = "brep:" + brep

    # 无聚焦 triage 载 brep：发现近切边（wedge 已知 ~1.72°）
    t = triage_input(case)
    check("brep 载入 + 无聚焦 triage 发现近切边", len(t.near_tangent_pairs) >= 1)
    check("brep 近切角 ≈ wedge 真值(<10°)", 0.0 < t.min_dihedral_deg < 10.0)
    n0 = t.near_tangent_pairs[0][0] if t.near_tangent_pairs else None      # 0-based sliver 边
    N = (n0 + 1) if n0 is not None else None                              # → 1-based

    # 单边聚焦 triage：只报该边，min_dihedral 与无聚焦一致
    if N is not None:
        tf = triage_input(case, edge_index=N)
        check("brep 单边聚焦 triage 命中该边", any(p[0] == n0 for p in tf.near_tangent_pairs))
        check("brep 聚焦 min_dihedral 与无聚焦一致", abs(tf.min_dihedral_deg - t.min_dihedral_deg) < 1e-6)
        # 聚焦到不存在的边 → 诚实空报告（不抛、不误判）
        tm = triage_input(case, edge_index=999)
        check("brep 聚焦越界边 → 无近切(诚实空)", tm.near_tangent_pairs == [] and tm.min_dihedral_deg == 180.0)

    # 端到端 investigate（brep: + 指定边）→ 结论与合成 wedge 一致（root S2 / 近切型）
    if N is not None:
        c = investigate(case, radius=1.0, edges=str(N), policy="rule")
        check("brep investigate 不弃权", not c.abstained and len(c.hypotheses) == 1)
        if c.hypotheses:
            h = c.hypotheses[0]
            check("brep investigate root=S2", h.stage.value == "S2")
            check("brep investigate 失效类=geometric_near_tangent",
                  h.failure_class == "geometric_near_tangent")
            check("brep investigate 有实体级定位", len([e for e in h.entities if e]) >= 1)

    # STEP 前缀走同一 read()：把 brep 转 step 再诊断
    step = str(Path(tmp) / "wedge.step")
    if _export_step(brep, step):
        ts = triage_input("step:" + step)
        check("step 载入 + triage 发现近切边", len(ts.near_tangent_pairs) >= 1)
    else:
        print("SKIP step 子测（exportStep 未产出文件）")

    # O2：fcstd: 直读——建含两具名对象的文档，测默认(最后带 solid 者)+#选择器+越界诚实失败
    fcstd = str(Path(tmp) / "t.FCStd")
    if _make_fcstd(fcstd):
        rd = reproduce("fcstd:" + fcstd, radius=0.0, out_dir=tmp)          # 默认=最后一个(BoxB 小)
        check("fcstd 默认读出 solid（export-only ok）",
              rd.status == "ok" and bool(rd.bad_shape) and Path(rd.bad_shape).exists())
        ra = reproduce("fcstd:" + fcstd + "#BoxA", radius=0.0, out_dir=tmp)  # 选择器=BoxA 大
        check("fcstd #BoxA 选择器读出 solid",
              ra.status == "ok" and bool(ra.bad_shape) and Path(ra.bad_shape).exists())
        if rd.bad_shape and ra.bad_shape:
            check("fcstd 默认(BoxB) ≠ #BoxA（选择器真的在选不同对象）",
                  Path(rd.bad_shape).read_bytes() != Path(ra.bad_shape).read_bytes())
        rn = reproduce("fcstd:" + fcstd + "#NoSuchObj", radius=0.0, out_dir=tmp)  # 越界对象名
        check("fcstd #越界对象 → harness 失败（不静默假绿）",
              rn.status == "failed" and rn.phase == "harness")
    else:
        print("SKIP fcstd 子测（saveAs 未产出文件）")

    print(f"\n{'ALL PASS' if not fails else str(len(fails)) + ' FAILED: ' + ', '.join(fails)}")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
