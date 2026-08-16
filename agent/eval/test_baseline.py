"""离线基线回归门（C2 Phase 2 / Option A）：python -m agent.eval.test_baseline

用【当前】scorer + runner 聚合，对 baseline_snapshot.json 冻结的 Conclusion 重打分，
断言分层指标 + 弃权汇总 == 冻结期望。**纯离线**（不拉 OCCT），自动被 run-agent-tests.sh
发现、进 CI。

红了说明 scorer / _aggregate / _load_gt / failure_class 判定等**改变了 baselines 数字**：
  - 若是 bug（无意漂移）→ 修回。
  - 若是有意改动（如 C1 反事实真分、C3 加 case）→ 重跑 `python -m agent.eval.snapshot`
    （需 FreeCADCmd）更新快照，把新数字连同改动一起提交、复审 diff。

覆盖：scorer 五维打分 + runner 分层聚合 + 弃权 precision + case 集与快照的一致性。
不覆盖：investigate 逻辑（其输出被冻结）→ 那由本地真跑 test_investigate_* 把关。
"""
from __future__ import annotations

import json

from agent.eval.runner import _abstention_summary, _aggregate, _discover_cases, _health
from agent.eval.snapshot import _SNAP, build_row, strip_wall
from agent.trajectory import conclusion_from_dict

_EPS = 1e-9


def _num_eq(a, b) -> bool:
    if a is None or b is None:
        return a is b or a == b
    return abs(float(a) - float(b)) < _EPS


def _diff_layer(got: dict, exp: dict, fails: list, ctx: str) -> None:
    keys = set(got) | set(exp)
    for k in sorted(keys):
        gv, ev = got.get(k), exp.get(k)
        ok = (gv == ev) if isinstance(ev, int) and k == "n" else _num_eq(gv, ev)
        if not ok:
            fails.append(f"{ctx}.{k}: 现={gv} 期望={ev}")


def main() -> int:
    # run 健康门（Part 7 幸存者偏差修）：纯函数、离线可测。ERROR 是 harness 崩、SKIP 是环境缺件。
    _hfail = []
    _hc = lambda n, c: (_hfail.append(n) if not c else None)  # noqa: E731
    _hc("全 OK → 可信", _health([{"status": "OK"}] * 13)["trustworthy"] is True)
    _hc("8 OK+5 ERROR → 不可信（幸存者偏差）", _health([{"status": "OK"}] * 8 + [{"status": "ERROR"}] * 5)["trustworthy"] is False)
    _hc("6 OK+7 SKIP → 可信（SKIP=环境缺件非 harness 崩）", _health([{"status": "OK"}] * 6 + [{"status": "SKIP"}] * 7)["trustworthy"] is True)
    _hc("13 OK+1 ERROR(7%<10%阈) → 可信", _health([{"status": "OK"}] * 13 + [{"status": "ERROR"}])["trustworthy"] is True)
    if _hfail:
        print(f"{len(_hfail)} FAILED（health 门）: " + " / ".join(_hfail))
        return 1

    if not _SNAP.exists():
        print(f"SKIP: 无快照 {_SNAP.name}（先 python -m agent.eval.snapshot 生成，需 FreeCADCmd）")
        return 0

    snap = json.loads(_SNAP.read_text(encoding="utf-8"))
    docs = {cid: doc for cid, doc in _discover_cases(None)}
    fails: list[str] = []

    # 覆盖核对：快照 ↔ cases/ 双向一致（新增/删除 case 未重生成快照 → 红，逼你更新）
    snap_ids, case_ids = set(snap["cases"]), set(docs)
    for cid in sorted(snap_ids - case_ids):
        fails.append(f"快照有 {cid} 但 cases/ 无（case 删了？重跑 snapshot）")
    for cid in sorted(case_ids - snap_ids):
        fails.append(f"cases/ 有 {cid} 但快照无（新增 case？重跑 snapshot）")

    # 用当前 scorer 对冻结 Conclusion 重打分 → 重聚合
    rows = [build_row(cid, docs[cid], conclusion_from_dict(cs["conclusion"]), cs["tool_calls"])
            for cid, cs in snap["cases"].items() if cid in docs]
    got_agg = strip_wall(_aggregate(rows))
    got_abst = _abstention_summary(rows)
    exp = snap["expected"]

    # 分层聚合逐层逐维比对
    exp_agg = exp["aggregate"]
    for layer in sorted(set(got_agg) | set(exp_agg)):
        if layer not in got_agg:
            fails.append(f"聚合层缺失：{layer}（现无、期望有）")
        elif layer not in exp_agg:
            fails.append(f"聚合层多出：{layer}（现有、期望无）")
        else:
            _diff_layer(got_agg[layer], exp_agg[layer], fails, f"[{layer}]")

    # 弃权汇总比对
    if got_abst.get("counts") != exp["abstention"].get("counts"):
        fails.append(f"弃权混淆：现={got_abst.get('counts')} 期望={exp['abstention'].get('counts')}")
    if not _num_eq(got_abst.get("abstention_precision"), exp["abstention"].get("abstention_precision")):
        fails.append(f"abstention_precision：现={got_abst.get('abstention_precision')} "
                     f"期望={exp['abstention'].get('abstention_precision')}")
    if got_abst.get("false_commit") != exp["abstention"].get("false_commit"):
        fails.append(f"false_commit：现={got_abst.get('false_commit')} 期望={exp['abstention'].get('false_commit')}")

    if fails:
        print(f"{len(fails)} FAILED（baselines 漂移——修回，或有意改动则重跑 snapshot 更新）:")
        for f in fails:
            print(f"  ✗ {f}")
        return 1

    n = len(rows)
    full = got_agg.get("全集", {})
    print(f"ALL PASS：{n} case 分层指标与快照一致"
          f"（全集 定位={full.get('localization')} 失效分类={full.get('failure_class')} "
          f"false_commit={got_abst.get('false_commit')}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
