"""规模化 runner 离线自测：python -m agent.eval.test_runner_scale

覆盖 P0 并行/沙箱/预算/隔离机制里**不需要 FreeCAD**的确定性部分：
  · _scale_summary / default_workers / _case_source / Budget —— 纯函数，恒跑。
  · 失败隔离 —— 用 poison case（缺 radius / 缺 agent_run，investigate 在碰 FreeCADCmd 前就抛）
    经真 ProcessPoolExecutor 跑：证明"单 case 崩只落 ERROR 行、worker 存活、全轮不倒"。
  · 串行≡并行 打分等价 —— 需 FreeCADCmd，缺则 SKIP（退 0，同仓库 SKIP 契约）。
"""
from __future__ import annotations

from agent.eval.runner import (
    Budget, _case_source, _run_parallel, _scale_summary, default_workers,
)


def _poison(cid, doc):
    return (cid, doc)


def main() -> int:
    fails = []

    def check(name, cond):
        print(("PASS " if cond else "FAIL ") + name)
        if not cond:
            fails.append(name)

    # 1) default_workers 合理边界
    w = default_workers()
    check("default_workers ∈ [1,12]", 1 <= w <= 12)

    # 2) Budget 默认（wall 软背板 + repro 硬预算）
    b = Budget()
    check("Budget 默认 wall/repro/mem", b.wall_s == 180.0 and b.repro_timeout_s == 60 and b.mem_mb is None)

    # 3) _case_source：cases=13 手工 / parametric>=100 / both=两者和 / only 过滤
    cases13 = _case_source("cases", None)
    param = _case_source("parametric", None)
    both = _case_source("both", None)
    check("cases suite = 13 手工真值", len(cases13) == 13)
    check("parametric suite >= 100", len(param) >= 100)
    check("both = cases + parametric", len(both) == len(cases13) + len(param))
    one = _case_source("parametric", param[0][0])
    check("only 过滤命中单 case", len(one) == 1 and one[0][0] == param[0][0])

    # 4) _scale_summary：加速比 = Σper-case / wall_total，隔离计数正确
    fake = [
        {"case_id": "a", "status": "OK", "wall_s": 4.0},
        {"case_id": "b", "status": "OK", "wall_s": 6.0},
        {"case_id": "c", "status": "ERROR", "wall_s": 1.0},
        {"case_id": "d", "status": "TIMEOUT", "wall_s": 2.0},
        {"case_id": "e", "status": "SKIP", "wall_s": None},
    ]
    s = _scale_summary(fake, workers=4, wall_total_s=5.0)
    check("scale Σper-case=13.0", s["wall_sum_s"] == 13.0)
    check("scale 加速比=2.6", s["speedup"] == 2.6)
    check("scale 隔离计数 error/timeout/skip", s["error"] == 1 and s["timeout"] == 1 and s["skip"] == 1)

    # 5) 失败隔离（真 ProcessPoolExecutor，无 FreeCAD）：
    #    p1 缺 radius → investigate 在 FreeCADCmd 前抛 ValueError（run_case 自己的 except → ERROR）
    #    p2 缺 agent_run → run_case 取字段即 KeyError（run_case try 之前 → worker 层 except → ERROR）
    #    两条隔离路径都不该杀池；三个 poison 全落 ERROR、行数守恒。
    poisons = [
        ("POISON-no-radius", {"family": "poison",
                              "agent_run": {"case": "boxp:10,20,30"},
                              "ground_truth": {"true_chain": [], "entities": []}}),
        ("POISON-no-agentrun", {"family": "poison",
                                "ground_truth": {"true_chain": [], "entities": []}}),
        ("POISON-no-radius-2", {"family": "poison",
                                "agent_run": {"case": "pocketp:20,20,10,3"},
                                "ground_truth": {"true_chain": [], "entities": []}}),
    ]
    rows = _run_parallel(poisons, "rule", 3, Budget(wall_s=30, repro_timeout_s=10))
    check("隔离：3 poison → 3 行（行数守恒、harness 未倒）", len(rows) == 3)
    check("隔离：全部落 ERROR（非崩溃外泄）", all(r["status"] == "ERROR" for r in rows))
    check("隔离：结果按 case_id 稳定排序", [r["case_id"] for r in rows] == sorted(r["case_id"] for r in rows))

    # 5b) A1 铁律：wall deadline 被 investigate 的 except 吞掉 → fired 兜底强制改判 TIMEOUT（非假 OK）。
    #     无 FreeCAD：monkeypatch run_case 模拟"睡过预算 + 吞掉 SIGALRM + 返回 OK"。
    import time as _time
    import agent.eval.runner as _R

    def _fake_swallow(cid, doc, *, policy, out_dir):
        try:
            _time.sleep(0.6)                       # itimer(0.2) 会在此响 → 抛 TimeoutError
        except TimeoutError:
            pass                                   # 模拟 investigate 某个 except Exception 吞掉它
        return {"case_id": cid, "policy": policy, "status": "OK", "scores": {}, "wall_s": 0.6}

    _orig = _R.run_case
    _R.run_case = _fake_swallow
    try:
        r = _R._run_case_sandboxed("swallow", {"family": None}, "rule", Budget(wall_s=0.2, repro_timeout_s=5))
    finally:
        _R.run_case = _orig
    check("A1：吞掉的 wall deadline → fired 兜底改判 TIMEOUT（不假绿）", r["status"] == "TIMEOUT")

    # 5c) A2 隔离真成立：worker **进程级**死亡（SIGKILL）不该把健康兄弟一并误判 ERROR。
    #     故障注入 killme 自杀毒化池；workers=1 + killme 首位 → 兄弟必 pending → 走重跑隔离。
    #     断言：全行守恒、只有 killme 落"worker 死亡"、兄弟落各自 ValueError（已恢复、未背锅）。
    import os as _os
    mixed = [
        ("killme", {"family": "poison", "agent_run": {"case": "boxp:10,20,30"},
                    "ground_truth": {"true_chain": [], "entities": []}}),
        ("sib-1", {"family": "poison", "agent_run": {"case": "boxp:10,20,30"},   # 缺 radius → ValueError
                   "ground_truth": {"true_chain": [], "entities": []}}),
        ("sib-2", {"family": "poison", "agent_run": {"case": "boxp:10,20,30"},
                   "ground_truth": {"true_chain": [], "entities": []}}),
    ]
    _os.environ["EVAL_FAULT_INJECT_SELFKILL"] = "killme"
    try:
        krows = _run_parallel(mixed, "rule", 1, Budget(wall_s=30, repro_timeout_s=10))
    finally:
        _os.environ.pop("EVAL_FAULT_INJECT_SELFKILL", None)
    kmap = {r["case_id"]: r for r in krows}
    check("A2：SIGKILL 后行数守恒（harness 未倒）", len(krows) == 3)
    check("A2：真凶 killme 落 ERROR + '死亡' 归因", kmap.get("killme", {}).get("status") == "ERROR"
          and "死亡" in kmap.get("killme", {}).get("reason", ""))
    check("A2：健康兄弟恢复（各自 ValueError，未被池碎背锅为'死亡'）",
          all(kmap[s]["status"] == "ERROR" and "死亡" not in kmap[s].get("reason", "")
              for s in ("sib-1", "sib-2")))

    # 6) 串行 ≡ 并行 打分等价（需 FreeCADCmd）——决策/打分与并行顺序无关
    try:
        from agent.tools.reproduce import _resolve_freecadcmd
        _resolve_freecadcmd()
    except FileNotFoundError as e:
        print(f"SKIP: {e}（跳过串行≡并行等价，纯逻辑断言已过）")
        print("全部通过" if not fails else f"有 {len(fails)} 项失败")
        return 1 if fails else 0

    from agent.eval.gen_cases import generate
    from agent.eval.runner import run_case
    allc = dict(generate())
    pick = ["gen-clean-box-10x20x30-r3.0", "gen-curv-rc2-r2.6", "gen-neartan-a2.0-L20"]
    cases = [(p, allc[p]) for p in pick if p in allc]      # gen 网格若微调，缺的自动略过

    ser = {cid: run_case(cid, doc, policy="rule").get("scores")   # 串行：无沙箱直跑
           for cid, doc in cases}
    par_rows = _run_parallel(cases, "rule", len(cases), Budget(repro_timeout_s=45))  # 并行：沙箱 + pool
    par = {r["case_id"]: r.get("scores") for r in par_rows}
    check("串行≡并行：同 case 集", set(ser) == set(par))
    check("串行≡并行：逐 case 打分逐位一致（决策/打分与并行顺序无关）", ser == par)

    print("全部通过" if not fails else f"有 {len(fails)} 项失败")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
