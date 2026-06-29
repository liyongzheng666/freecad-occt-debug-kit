"""根因 Eval runner —— 跑全 case 集，按失效类别分层打分（A4 / G5 / G11）。

  一条命令：observe→定位→失效分类→反事实→结论（investigate）→ scorer 五维打分。
  指标：定位 / 失效分类 / 机制(代理) / 反事实(携带) / 校准 + tool-call 成本 + wall-clock。
  分层：按 GT.failure_class 分组报（别让 box 的绿盖住 wedge 的红，README §3 A4）+ 全集汇总。

诚实边界（呼应 README §7 B1 + scorer 文档）：机制/反事实此刻只是代理/是否携带，真分待
truth-run 中间态 / OCCT 执行接入（A8）；表里照实标 basis，绝不用代理冒充真分。

GT 来源：cases/*.json 的 ground_truth 四元组 + failure_class；如何驱动 investigate 见各
case 的 agent_run（{case, radius}——harness builder id，可能 ≠ input.builder）。

用法：
  python -m agent.eval.runner                 # 真跑全集，打印分层表
  python -m agent.eval.runner --json out.json # 另存结构化结果（轨迹/回归基线用）
  python -m agent.eval.runner --case box-r5   # 只跑指定 case
缺 FreeCADCmd（REPRO_FREECADCMD/默认路径都没有）→ 该 case 标 SKIP，不算分、不假绿。
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from agent.contracts import GroundTruth, Stage, ToolResult
from agent.eval.scorer import score
from agent.loop.investigate import investigate

_CASES_DIR = Path(__file__).resolve().parents[1] / "cases"

# 打分维度（None 维不参与均值）；basis 见 scorer，机制/反事实为代理/携带
_DIMS = ["localization", "failure_class", "mechanism", "counterfactual", "calibration"]
_DIM_LABEL = {
    "localization": "定位",
    "failure_class": "失效分类",
    "mechanism": "机制*",
    "counterfactual": "反事实*",
    "calibration": "校准",
}

# 弃权四态的紧凑标记（逐 case 列）
_ABST_MARK = {
    "correct_abstain": "✓弃权",
    "correct_commit": "✓结论",
    "false_commit": "✗幻觉",
    "wrong_abstain": "✗漏检",
}


def _load_gt(doc: dict) -> GroundTruth:
    g = doc["ground_truth"]
    return GroundTruth(
        true_chain=[Stage(s) for s in g["true_chain"]],
        entities=list(g.get("entities", [])),
        expected_evidence=g.get("expected_evidence", ""),
        aligned_fix=g.get("aligned_fix", "") if isinstance(g.get("aligned_fix"), str)
        else json.dumps(g.get("aligned_fix"), ensure_ascii=False),
        failure_class=g.get("failure_class"),
        expected_abstain=g.get("expected_abstain", False),
    )


def _discover_cases(only: str | None) -> list[tuple[str, dict]]:
    """返回 [(case_id, doc)]，按 case_id 排序；跳过非 case（无 agent_run/ground_truth）。"""
    out = []
    for fp in sorted(_CASES_DIR.glob("*.json")):
        doc = json.loads(fp.read_text(encoding="utf-8"))
        if "agent_run" not in doc or "ground_truth" not in doc:
            continue
        cid = doc.get("case_id", fp.stem)
        if only and cid != only:
            continue
        out.append((cid, doc))
    return out


def run_case(case_id: str, doc: dict, *, policy: str = "rule") -> dict:
    """跑单 case：investigate(policy) → score。返回 {case_id, status, gt_*, scores, tool_calls, wall_s}。"""
    gt = _load_gt(doc)
    run = doc["agent_run"]
    row: dict = {
        "case_id": case_id,
        "policy": policy,
        "gt_root": gt.root_stage.value if gt.root_stage else "—",   # clean/弃权 case 无根
        "gt_chain": [s.value for s in gt.true_chain],
        "gt_failure_class": gt.failure_class,
    }
    trace: list[ToolResult] = []
    t0 = time.perf_counter()
    try:
        concl = investigate(run["case"], radius=run["radius"], policy=policy, trace=trace)
    except FileNotFoundError as e:           # FreeCADCmd 缺位 → SKIP（不假绿）
        row.update(status="SKIP", reason=str(e), wall_s=round(time.perf_counter() - t0, 2))
        return row
    except Exception as e:                    # noqa: BLE001 — harness/基础设施级失败如实记 ERROR
        row.update(status="ERROR", reason=f"{type(e).__name__}: {e}",
                   wall_s=round(time.perf_counter() - t0, 2))
        return row
    wall_s = round(time.perf_counter() - t0, 2)

    sc = score(concl, gt, tool_calls=len(trace))
    row.update(
        status="OK",
        abstained=sc["detail"]["abstained"],
        expected_abstain=gt.expected_abstain,
        pred_root=(concl.hypotheses[0].stage.value if concl.hypotheses else None),
        pred_failure_class=(concl.hypotheses[0].failure_class if concl.hypotheses else None),
        scores={d: sc[d] for d in _DIMS},
        abstention=sc["abstention"],
        tool_calls=sc["tool_calls"],
        wall_s=wall_s,
    )
    return row


# ---- 汇总 + 渲染 --------------------------------------------------------------

def _mean(vals: list) -> float | None:
    v = [x for x in vals if x is not None]
    return round(sum(v) / len(v), 3) if v else None


def _layer_of(r: dict) -> str:
    """分层键：clean/弃权 case 自成一层（别和缺陷类混报），否则按 failure_class；
    无三态类的缺陷（如 false-green 自交，非 S2-NotDone）归 '其它(无三态类)'。"""
    if r.get("expected_abstain"):
        return "clean/abstain"
    return r["gt_failure_class"] or "其它(无三态类)"


def _aggregate(rows: list[dict]) -> dict:
    """按层（failure_class / clean）分组 + 全集，对每维求均值（None 维跳过）；只统计 status=OK。"""
    ok = [r for r in rows if r["status"] == "OK"]
    groups: dict[str, list[dict]] = {}
    for r in ok:
        groups.setdefault(_layer_of(r), []).append(r)
    groups["全集"] = ok

    agg = {}
    for name, grp in groups.items():
        if not grp:
            continue
        agg[name] = {
            "n": len(grp),
            **{d: _mean([r["scores"][d] for r in grp]) for d in _DIMS},
            "tool_calls": _mean([r["tool_calls"] for r in grp]),
            "wall_s": _mean([r["wall_s"] for r in grp]),
        }
    return agg


def _abstention_summary(rows: list[dict]) -> dict:
    """弃权混淆 + abstention precision（集合量，跨 case 汇总）。"""
    ok = [r for r in rows if r["status"] == "OK"]
    counts = {"correct_abstain": 0, "false_commit": 0, "wrong_abstain": 0, "correct_commit": 0}
    for r in ok:
        counts[r["abstention"]] = counts.get(r["abstention"], 0) + 1
    n_abstain = counts["correct_abstain"] + counts["wrong_abstain"]      # 所有弃权
    precision = round(counts["correct_abstain"] / n_abstain, 3) if n_abstain else None
    return {"counts": counts, "abstention_precision": precision,
            "false_commit": counts["false_commit"]}


def _fmt(x) -> str:
    return "  n/a" if x is None else f"{x:5.2f}"


def render(rows: list[dict]) -> str:
    pol = next((r.get("policy", "rule") for r in rows), "rule")
    _label = {"rule": "规则版 policy / A3 基线", "llm": "LLM 版 policy / A5（decide_llm）"}.get(pol, pol)
    L = [f"═══ 根因 Eval（{_label}）═══", ""]

    # 逐 case
    L.append("— 逐 case —")
    hdr = f"{'case':<22}{'状态':<6}{'根 GT/预测':<14}{'失效类 GT/预测':<28}"
    hdr += "".join(f"{_DIM_LABEL[d]:<9}" for d in _DIMS) + f"{'tool':>6}{'wall_s':>8}  {'弃权裁定':<8}"
    L.append(hdr)
    for r in rows:
        if r["status"] != "OK":
            L.append(f"{r['case_id']:<22}{r['status']:<6}{r.get('reason', '')[:60]}")
            continue
        root = f"{r['gt_root']}/{r['pred_root']}"
        fc = f"{r['gt_failure_class']}/{r['pred_failure_class']}"
        line = f"{r['case_id']:<22}{'OK':<6}{root:<14}{fc:<28}"
        line += "".join(f"{_fmt(r['scores'][d]):<9}" for d in _DIMS)
        line += f"{r['tool_calls']:>6}{r['wall_s']:>8}  {_ABST_MARK.get(r['abstention'], r['abstention']):<8}"
        L.append(line)

    # 分层 + 全集
    L += ["", "— 分层汇总（按失效类别 / 全集；机制*=深度代理、反事实*=仅判携带）—"]
    hdr2 = f"{'层':<24}{'n':>3}  "
    hdr2 += "".join(f"{_DIM_LABEL[d]:<9}" for d in _DIMS) + f"{'tool':>6}{'wall_s':>8}"
    L.append(hdr2)
    agg = _aggregate(rows)
    # 失效类别层在前，全集压轴
    for name in [k for k in agg if k != "全集"] + (["全集"] if "全集" in agg else []):
        a = agg[name]
        line = f"{name:<24}{a['n']:>3}  "
        line += "".join(f"{_fmt(a[d]):<9}" for d in _DIMS)
        line += f"{_fmt(a['tool_calls']):>6}{_fmt(a['wall_s']):>8}"
        L.append(line)

    # 弃权汇总（集合量：abstention precision + false-commit 安全指标）
    ab = _abstention_summary(rows)
    c = ab["counts"]
    L += ["", "— 弃权/校准汇总（集合量）—",
          f"  混淆：correct_abstain={c['correct_abstain']} wrong_abstain={c['wrong_abstain']} "
          f"correct_commit={c['correct_commit']} false_commit={c['false_commit']}",
          f"  abstention precision（弃权对率）= {_fmt(ab['abstention_precision']).strip()}"
          f"（弃权时有几次是对的）；false_commit（clean 上幻觉根因）= {ab['false_commit']} ← 越低越安全"]

    skipped = [r for r in rows if r["status"] != "OK"]
    if skipped:
        L += ["", f"⚠ {len(skipped)} case 未计分（SKIP/ERROR）——见上，未假绿。"]
    L += ["", "* 机制=localization_depth 深度代理；反事实=仅判是否携带靶向修法。",
          "  真机制正确性待 truth-run 中间态、反事实 S6 有效性待 OCCT 执行（A8）。见 scorer 文档。",
          "  弃权裁定：✓弃权=clean 正确弃权 / ✓结论=缺陷正确定位 / ✗幻觉=clean 上编根因 / ✗漏检=缺陷却弃权。"]
    return "\n".join(L)


def run_eval(only: str | None = None, *, policy: str = "rule") -> list[dict]:
    return [run_case(cid, doc, policy=policy) for cid, doc in _discover_cases(only)]


def main(argv: list[str]) -> int:
    only = None
    json_out = None
    policy = "rule"
    i = 0
    while i < len(argv):
        if argv[i] == "--case":
            only = argv[i + 1]; i += 2
        elif argv[i] == "--json":
            json_out = argv[i + 1]; i += 2
        elif argv[i] == "--policy":
            policy = argv[i + 1]; i += 2          # rule(默认) | llm；llm 后端见 decide_llm（env）
        else:
            print(f"未知参数：{argv[i]}", file=sys.stderr); return 2
    rows = run_eval(only, policy=policy)
    if not rows:
        print("无可跑 case（cases/*.json 需含 agent_run + ground_truth）", file=sys.stderr)
        return 1
    print(render(rows))
    if json_out:
        Path(json_out).write_text(
            json.dumps({"rows": rows, "aggregate": _aggregate(rows)}, ensure_ascii=False, indent=2),
            encoding="utf-8")
        print(f"\n[结构化结果 → {json_out}]")
    # 退出码：有 OK 即 0；全 SKIP/ERROR 则 1（CI 能区分"没法跑"与"跑了"）
    return 0 if any(r["status"] == "OK" for r in rows) else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
