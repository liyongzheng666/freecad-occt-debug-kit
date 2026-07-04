"""gen_cases 离线自测（纯 Python，无 FreeCAD 依赖）：python -m agent.eval.test_gen_cases

守住 P0 规模化套件的**第一性 GT 不变量**——参数区间必须真落在各 regime 内、且各族 GT 与
几何谓词自洽（避免"造假 GT"：若哪天有人把网格调到临界带外，这些断言当场变红）。同款"reward
signal 不能悄悄判错"纪律：GT 生成逻辑自己也要被测。
"""
from __future__ import annotations

import math

from agent.eval.gen_cases import generate


def _nums(builder: str) -> list[float]:
    return [float(x) for x in builder.split(":", 1)[1].split(",") if x.strip()]


def main() -> int:
    fails = []

    def check(name, cond):
        print(("PASS " if cond else "FAIL ") + name)
        if not cond:
            fails.append(name)

    cases = generate()
    docs = dict(cases)

    # 1) 规模 + 唯一性 + 排序
    check(">=100 cases (P0 规模)", len(cases) >= 100)
    check("case_id 唯一", len(docs) == len(cases))
    check("按 case_id 排序", [c for c, _ in cases] == sorted(c for c, _ in cases))

    # 2) schema 完整（每 case 可直接喂 runner.run_case）
    schema_ok = True
    for cid, d in cases:
        gt = d.get("ground_truth", {})
        if not (d.get("synthetic") and d.get("gt_basis") == "parametric_first_principles"
                and d.get("family") and "agent_run" in d
                and "case" in d["agent_run"] and "radius" in d["agent_run"]
                and "true_chain" in gt and "entities" in gt
                and "expected_abstain" in gt and "failure_class" in gt):
            schema_ok = False
            print(f"   schema 缺字段：{cid}")
            break
    check("schema 完整（synthetic/gt_basis/family/agent_run/ground_truth）", schema_ok)
    check("规模套件不断言实体（entity 是 13-case 的活）",
          all(d["ground_truth"]["entities"] == [] for _, d in cases))

    # 3) 各族第一性不变量
    by_fam: dict[str, list] = {}
    for cid, d in cases:
        by_fam.setdefault(d["family"], []).append((cid, d))

    # box_false_green: 2·rf > minEdge（稳落假绿带）; GT=(S2,S3)/fc None/不弃权
    fg = by_fam.get("box_false_green", [])
    check("box_false_green 非空", len(fg) > 0)
    ok = True
    for cid, d in fg:
        lx, ly, lz = _nums(d["agent_run"]["case"])
        rf = d["agent_run"]["radius"]
        g = d["ground_truth"]
        if not (2 * rf > min(lx, ly, lz) and g["true_chain"] == ["S2", "S3"]
                and g["failure_class"] is None and g["expected_abstain"] is False):
            ok = False; print(f"   fg 违反不变量：{cid} rf={rf} dims={lx,ly,lz}"); break
    check("box_false_green: 2·rf>minEdge ∧ GT=(S2,S3)/None/commit", ok)

    # geometric_curvature: rf>RC（曲率无解）∧ rf<boxMinEdge/2（外边不抢戏）; fc=geometric_curvature
    cv = by_fam.get("geometric_curvature", [])
    check("geometric_curvature 非空", len(cv) > 0)
    ok = True
    for cid, d in cv:
        bx, by, bz, rc = _nums(d["agent_run"]["case"])
        rf = d["agent_run"]["radius"]
        g = d["ground_truth"]
        if not (rf > rc and rf < min(bx, by, bz) / 2 and g["failure_class"] == "geometric_curvature"
                and g["true_chain"] == ["S2"] and g["expected_abstain"] is False):
            ok = False; print(f"   curv 违反：{cid} rf={rf} rc={rc} box={bx,by,bz}"); break
    check("geometric_curvature: RC<rf<boxMinEdge/2 ∧ fc 对", ok)

    # geometric_near_tangent: 二面角 θ=atan(tip/LEN) ∈ (0,10°); fc=geometric_near_tangent
    nt = by_fam.get("geometric_near_tangent", [])
    check("geometric_near_tangent 非空", len(nt) > 0)
    ok = True
    for cid, d in nt:
        length, tip, width = _nums(d["agent_run"]["case"])
        theta = math.degrees(math.atan(tip / length))
        g = d["ground_truth"]
        if not (0 < theta < 10 and g["failure_class"] == "geometric_near_tangent"
                and g["true_chain"] == ["S2"] and g["expected_abstain"] is False):
            ok = False; print(f"   nt 违反：{cid} θ={theta:.2f}°"); break
    check("geometric_near_tangent: 0<θ<10° ∧ fc 对", ok)

    # clean: expected_abstain=True ∧ 无根/无类; box rf<minEdge/2、pocket rf<RC（留余量）
    cl = by_fam.get("clean", [])
    check("clean 非空", len(cl) > 0)
    ok = True
    for cid, d in cl:
        g = d["ground_truth"]
        if not (g["expected_abstain"] is True and g["true_chain"] == []
                and g["failure_class"] is None):
            ok = False; print(f"   clean 违反：{cid}"); break
        scheme = d["agent_run"]["case"].split(":", 1)[0]
        rf = d["agent_run"]["radius"]
        n = _nums(d["agent_run"]["case"])
        if scheme == "boxp" and not (rf < min(n) / 2):
            ok = False; print(f"   clean box rf 太大：{cid} rf={rf}"); break
        if scheme == "pocketp" and not (rf < n[3]):     # rf < RC
            ok = False; print(f"   clean pocket rf≥RC：{cid} rf={rf} rc={n[3]}"); break
    check("clean: expected_abstain ∧ rf 落干净带", ok)

    # 4b) P1a chamfer 域族：op=chamfer 必带；各族第一性同 fillet 对偶 + 域差异 GT
    ch = [(cid, d) for cid, d in cases if d["family"].startswith("chamfer")]
    check("chamfer 族非空", len(ch) > 0)
    check("chamfer 族 agent_run.op == chamfer",
          all(d["agent_run"].get("op") == "chamfer" for _, d in ch))
    ch_ov = by_fam.get("chamfer_overflow", [])
    ok = all(2 * d["agent_run"]["radius"] > min(_nums(d["agent_run"]["case"]))
             and d["ground_truth"]["failure_class"] == "algorithmic_overflow"
             and d["ground_truth"]["true_chain"] == ["S2"]
             and d["ground_truth"]["expected_abstain"] is False for _, d in ch_ov)
    check("chamfer_overflow: 2·d>minEdge ∧ fc=algorithmic_overflow", len(ch_ov) > 0 and ok)
    ch_nt = by_fam.get("chamfer_near_tangent", [])
    ok = True
    for _, d in ch_nt:
        length, tip, _w = _nums(d["agent_run"]["case"])
        if not (0 < math.degrees(math.atan(tip / length)) < 10
                and d["ground_truth"]["failure_class"] == "geometric_near_tangent"):
            ok = False; break
    check("chamfer_near_tangent: 0<θ<10° ∧ fc 对", len(ch_nt) > 0 and ok)
    ch_fg = by_fam.get("chamfer_false_green", [])
    ok = all(d["agent_run"]["radius"] > _nums(d["agent_run"]["case"])[3]     # d > RC
             and d["ground_truth"]["true_chain"] == ["S2", "S6"]
             and d["ground_truth"]["failure_class"] is None
             and d["ground_truth"]["expected_abstain"] is False for _, d in ch_fg)
    check("chamfer_false_green: d>RC ∧ GT=(S2,S6)/None/commit（凹壁假绿域差异）", len(ch_fg) > 0 and ok)

    print(f"\n族计数：{ {k: len(v) for k, v in by_fam.items()} }")
    print("全部通过" if not fails else f"有 {len(fails)} 项失败")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
