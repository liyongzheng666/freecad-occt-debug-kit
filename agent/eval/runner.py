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
import os
import shutil
import sys
import tempfile
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from concurrent.futures.process import BrokenProcessPool
from dataclasses import dataclass
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
    "mechanism": "机制†",
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
        mechanism_truth=g.get("mechanism_truth"),
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


def run_case(case_id: str, doc: dict, *, policy: str = "rule", out_dir: str | None = None) -> dict:
    """跑单 case：investigate(policy) → score。返回 {case_id, status, gt_*, scores, tool_calls, wall_s}。

    out_dir：per-case 沙箱产物目录（P0 并行隔离）——None → investigate 内部 mkdtemp（旧行为，
    串行路径不变）。并行路径由 _run_case_sandboxed 传入独立 tmp 并跑完即清，杜绝 100+ case 串扰/泄漏。
    """
    gt = _load_gt(doc)
    run = doc["agent_run"]
    row: dict = {
        "case_id": case_id,
        "policy": policy,
        "family": doc.get("family"),                 # 参数化套件按族分层（生成 case 带；手工 case 无 → None）
        "gt_root": gt.root_stage.value if gt.root_stage else "—",   # clean/弃权 case 无根
        "gt_chain": [s.value for s in gt.true_chain],
        "gt_failure_class": gt.failure_class,
    }
    trace: list[ToolResult] = []
    t0 = time.perf_counter()
    try:
        concl = investigate(run["case"], radius=run.get("radius"), ssi_fixture=run.get("ssi_fixture"),
                            policy=policy, trace=trace, edges=run.get("edges"), out_dir=out_dir,
                            op=run.get("op", "fillet"))
    except FileNotFoundError as e:           # FreeCADCmd 缺位 → SKIP（不假绿）
        row.update(status="SKIP", reason=str(e), wall_s=round(time.perf_counter() - t0, 2))
        return row
    except TimeoutError:                      # per-case wall 预算（沙箱 SIGALRM）→ 交沙箱层记 TIMEOUT，别误当 ERROR
        raise                                 # 串行路径无 SIGALRM、绝不产此异常，故 re-raise 安全
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
    """分层键：clean/弃权 case 自成一层（别和缺陷类混报），否则优先按 family（参数化套件按族分层），
    再按 failure_class；无三态类的缺陷（如 false-green 自交，非 S2-NotDone）归 '其它(无三态类)'。

    family 仅生成 case 带（gen_cases）；手工 13 case 无该字段 → 回落 failure_class，聚合逐位不变
    （baseline 门只跑手工 case，故此改动不影响门）。"""
    if r.get("expected_abstain"):
        return "clean/abstain"
    if r.get("family"):
        return r["family"]
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


# harness 错误率高于此 → 聚合可能是幸存者偏差，本轮标不可信（0 error 的正常轮不受影响）
_HEALTH_ERROR_RATE_MAX = 0.10


def _health(rows: list[dict]) -> dict:
    """run 级健康门：区分「产了可打分 verdict（含"fillet 失败"这一**发现**，status=OK）」与「没产 verdict」。

    ERROR = harness 自身崩（含 replay miss，见 `decide_llm.DecisionNotRecorded`）；SKIP = 环境缺件
    （如无 FreeCADCmd），非 harness 病、不入错误率分母。**有产出(ok>0)但 harness 错误率过高**
    → 聚合是对**幸存者**求均值（一个看着健康的假信号，正是"撒谎 eval"）→ 本轮标不可信。
    注：一个 case fillet **失败**是 status=OK 的发现、进分母、绝不该被此门审查（见 INTERVIEW-PREP Part 7）。
    """
    n_ok = sum(1 for r in rows if r["status"] == "OK")
    n_error = sum(1 for r in rows if r["status"] == "ERROR")
    n_skip = sum(1 for r in rows if r["status"] == "SKIP")
    attempted = n_ok + n_error                                   # SKIP 不计入（环境缺件非 harness 崩）
    error_rate = round(n_error / attempted, 3) if attempted else None
    trustworthy = not (n_ok > 0 and error_rate is not None and error_rate > _HEALTH_ERROR_RATE_MAX)
    return {"n": len(rows), "ok": n_ok, "error": n_error, "skip": n_skip,
            "error_rate": error_rate, "trustworthy": trustworthy}


def _fmt(x) -> str:
    return "  n/a" if x is None else f"{x:5.2f}"


def render(rows: list[dict], scale: dict | None = None) -> str:
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
    L += ["", "— 分层汇总（按失效类别 / 全集；机制†=真分但仅覆盖有 mechanism_truth 的子集、反事实*=仅判携带）—"]
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

    # run 健康门（幸存者偏差：别让干净均值盖住一堆 harness ERROR）
    h = _health(rows)
    if h["error"] or h["skip"]:
        L += ["", "— run 健康 —",
              f"  产出 OK={h['ok']} / ERROR={h['error']}（harness 崩，含 replay miss）/ "
              f"SKIP={h['skip']}（环境缺件）；harness 错误率={_fmt(h['error_rate']).strip()}"]
    if not h["trustworthy"]:
        L += ["", "‼ 本轮不可信（UNTRUSTWORTHY）：harness 错误率超阈——上面的分层聚合是对**幸存者**"
              f"求均值（幸存者偏差）。别信这些数字，先修 ERROR（{h['error']} 个）再重跑。"]
    # 规模化 run（P0）：并行吞吐 + 预算/隔离读数（scale=None 的旧串行路径不打印，逐位不变）
    if scale is not None:
        sp = _fmt(scale["speedup"]).strip() if scale["speedup"] is not None else "n/a"
        L += ["", "— 规模化（P0：并行 + per-case 沙箱/预算 + 失败隔离）—",
              f"  workers={scale['workers']}  case 数={scale['n']}  "
              f"wall_total={scale['wall_total_s']}s  Σper-case={scale['wall_sum_s']}s  "
              f"加速比={sp}×（>1 即亚线性）",
              f"  失败隔离：TIMEOUT={scale['timeout']}（超 per-case wall 预算）  "
              f"ERROR={scale['error']}（case 崩，仅落该行、未毒化全轮）  SKIP={scale['skip']}（环境缺件）"]
    n_mech = sum(1 for r in rows if r.get("status") == "OK" and r.get("scores", {}).get("mechanism") is not None)
    L += ["", f"† 机制=真分（P1b：预测机制签名 vs GT.mechanism_truth，非深度代理）；仅 {n_mech} 个 case 有"
          " mechanism_truth、其余 None **不计入**均值 → 上面'机制'列只覆盖那 {0} 个可判子集，别读成'全体机制满分'。"
          .format(n_mech),
          "  * 反事实=互斥判别 verdict vs GT 根（C1 已真分）。",
          "  弃权裁定：✓弃权=clean 正确弃权 / ✓结论=缺陷正确定位 / ✗幻觉=clean 上编根因 / ✗漏检=缺陷却弃权。"]
    return "\n".join(L)


# ═══ P0 规模化：并行 worker pool + per-case 沙箱/预算 + 失败隔离 + case 源 ═══════════
#
# 前沿实验室的 harness 日常是跨 worker 跑几千 case、隔离 + 容错。这一段把 13-case 串行升成
# "小但 production-shaped" 的 100+ case 并行 suite：
#   · 并行     ：ProcessPoolExecutor（case 级）——worker 是独立进程。**subprocess 级**崩溃（FreeCADCmd
#                段错误/抛异常/超时）只落该 case 的 ERROR/TIMEOUT 行、绝不毒化全轮；**worker 进程级**
#                死亡（--mem-mb OOM / native 崩溃穿回 worker → BrokenProcessPool）则由重跑隔离兜，
#                最终只有真凶落 ERROR（见 _run_parallel）。不宣称对进程级死亡的"绝对零毒化"。
#   · 沙箱     ：每 case 独立 tmp 产物目录，跑完即清——防 100+ case 串扰 / 临时目录泄漏。
#   · 预算     ：per-case wall（SIGALRM 背板）+ 每次 FreeCADCmd subprocess timeout（REPRO_TIMEOUT_S）
#                + 可选内存上限（RLIMIT_AS，Linux 强制 / macOS best-effort，诚实标注）。
#   · 容差归一 ：GT 参数区间都留余量、避开跨平台临界带（见 gen_cases）——不硬编临界值。
#
# 诚实边界：默认 `--suite cases`（13 手工 case）走**串行**路径（workers=1），与改造前 run_eval
# 逐位一致（baseline 门不漂移）。规模化能力经 `--suite parametric --workers N` 显式开启。


@dataclass
class Budget:
    """per-case 资源预算。wall_s：整 case 墙钟背板（SIGALRM，防病态 case 拖垮一个 worker slot）；
    repro_timeout_s：每次 FreeCADCmd subprocess 超时（透传 REPRO_TIMEOUT_S）；mem_mb：地址空间上限
    （RLIMIT_AS，None=不设。Linux 强制、macOS 多不生效——诚实标注 best-effort，不假装跨平台强隔离）。"""
    wall_s: float = 180.0
    repro_timeout_s: int = 60
    mem_mb: int | None = None
    # 诚实边界：wall 是**软背板**（单发 SIGALRM；若恰在某探针的 except Exception 里触发会被吞、
    # 定时器不再响 → 该 case 逃逸）。**硬**预算是 repro_timeout_s（每次 FreeCADCmd subprocess 强制超时，
    # 可靠封顶单调用）。两者叠加：正常 case 都不触发，病态 case 由 subprocess 超时先兜、wall 再背板。


def default_workers() -> int:
    """留 2 核给 OS/驱动，避免 FreeCADCmd 子进程过订阅（cpu_count 拿不到 → 保守 4）。"""
    return max(1, min(12, (os.cpu_count() or 4) - 2))


def _case_source(suite: str, only: str | None) -> list[tuple[str, dict]]:
    """按 suite 取 case：cases=13 手工真值 / parametric=gen_cases 生成族 / both=两者。only 后过滤。"""
    if suite == "cases":
        return _discover_cases(only)               # _discover_cases 已按 only 过滤
    from agent.eval.gen_cases import generate
    if suite == "parametric":
        cases = generate()
    elif suite == "both":
        cases = _discover_cases(None) + generate()
    else:
        raise ValueError(f"未知 suite={suite}（cases | parametric | both）")
    if only:
        cases = [(cid, doc) for cid, doc in cases if cid == only]
    return cases


def _run_case_sandboxed(case_id: str, doc: dict, policy: str, budget: Budget) -> dict:
    """worker 入口（ProcessPoolExecutor 中跑）：装好沙箱 + 预算 → run_case → 保证清理。

    失败隔离分两层，本函数只保证第一层（诚实边界，别宣称绝对隔离）：
      (1) **subprocess 级崩溃（本函数拦得住）**：FreeCADCmd 是独立 subprocess，其段错误/超时回吐
          RunEnd 或被 run_case 收成 ERROR，worker 存活、下一 case 照跑 → 绝不毒化全轮。wall 超预算
          → SIGALRM→TimeoutError（subprocess 被 kill、无孤儿）；一发 itimer 被吞则由 fired 兜底改判
          TIMEOUT（不假绿）。
      (2) **worker 进程级死亡（本函数拦不住）**：若 worker 自身被 SIGKILL（--mem-mb 的 RLIMIT_AS
          OOM、或 native 崩溃穿回 worker）→ ProcessPoolExecutor 整池损坏、全 pending future 抛
          BrokenProcessPool。这层由 `_run_parallel` 的**重跑隔离**兜（pending 逐个塞进一次性单池，
          只有真凶落 ERROR、健康兄弟恢复）——不是本函数能拦的。
    """
    import signal
    # 测试专用故障注入：把 case_id 填进 EVAL_FAULT_INJECT_SELFKILL → worker 自 SIGKILL，模拟进程级
    # 死亡（--mem-mb OOM / native 崩溃穿回 worker）。生产 env 不设 → 一次 dict 查、完全 inert。
    # 用途：test_runner_scale 用它证明"重跑隔离"真能只让真凶落 ERROR、健康兄弟恢复（非口号）。
    if os.environ.get("EVAL_FAULT_INJECT_SELFKILL") == case_id:
        os.kill(os.getpid(), signal.SIGKILL)
    os.environ["REPRO_TIMEOUT_S"] = str(budget.repro_timeout_s)   # 透传每次 FreeCADCmd 超时
    if budget.mem_mb:                                             # 地址空间上限（子进程 fork 继承）
        try:
            import resource
            cap = budget.mem_mb * 1024 * 1024
            resource.setrlimit(resource.RLIMIT_AS, (cap, cap))
        except Exception:                                        # noqa: BLE001 — macOS 常不支持，忽略
            pass

    base = {"case_id": case_id, "policy": policy, "family": doc.get("family")}
    sandbox = tempfile.mkdtemp(prefix="evalcase_")

    fired: list[bool] = []                       # 可变单元：_on_alarm 抛前置位（闭包捕获）

    def _on_alarm(signum, frame):
        fired.append(True)
        raise TimeoutError(f"per-case wall 预算 {budget.wall_s}s 超时")

    prev = signal.signal(signal.SIGALRM, _on_alarm)
    signal.setitimer(signal.ITIMER_REAL, budget.wall_s)
    t0 = time.perf_counter()
    try:
        row = run_case(case_id, doc, policy=policy, out_dir=sandbox)
        # A1（铁律：不假绿）：一发 itimer 若恰在 investigate 某个 `except Exception` 里响，
        # TimeoutError 会被吞、定时器不再响 → run_case 照常返回一个 status=OK 行（超预算却蒙混成
        # 干净分）。fired 兜底：只要闹钟响过就强制改判 TIMEOUT，绝不让吞掉的 deadline 以 OK 过关。
        if fired and row.get("status") == "OK":
            return {**base, "status": "TIMEOUT",
                    "reason": f"per-case wall 预算 {budget.wall_s}s 超时"
                              "（investigate 的 except 吞了 SIGALRM，fired 兜底改判，未假绿）",
                    "wall_s": round(time.perf_counter() - t0, 2)}
        return row
    except TimeoutError as e:
        return {**base, "status": "TIMEOUT", "reason": str(e),
                "wall_s": round(time.perf_counter() - t0, 2)}
    except Exception as e:                                        # noqa: BLE001 — worker 级兜底，绝不外泄杀池
        return {**base, "status": "ERROR", "reason": f"{type(e).__name__}: {e}",
                "wall_s": round(time.perf_counter() - t0, 2)}
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, prev)
        shutil.rmtree(sandbox, ignore_errors=True)               # 沙箱跑完即清（防泄漏/串扰）


def _drain_pool(cases: list[tuple[str, dict]], policy: str, workers: int, budget: Budget
                ) -> tuple[list[dict], list[tuple[str, dict]]]:
    """把 cases 灌进一个新池跑一轮，返回 (已完成行, 仍 pending 的 case)。

    池损坏（worker 被 SIGKILL）时：已在损坏前拿到结果的 future 正常返回；其余（含真凶 + 还没跑的
    健康兄弟）抛 BrokenProcessPool → 归 pending（交调用方重跑隔离）。非池级的 per-case 异常仍就地
    收成 ERROR 行（那是真 per-case 崩，不该重跑）。"""
    completed: list[dict] = []
    pending: list[tuple[str, dict]] = []
    with ProcessPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(_run_case_sandboxed, cid, doc, policy, budget): (cid, doc) for cid, doc in cases}
        for fut in as_completed(futs):
            cid, doc = futs[fut]
            try:
                completed.append(fut.result())
            except BrokenProcessPool:
                pending.append((cid, doc))                       # 池碎 → 重跑隔离，别误当 per-case 崩
            except Exception as e:                               # noqa: BLE001 — 真 per-case 崩，就地 ERROR
                completed.append({"case_id": cid, "policy": policy, "status": "ERROR",
                                  "reason": f"{type(e).__name__}: {e}", "wall_s": None})
    return completed, pending


def _run_isolated_single(cid: str, doc: dict, policy: str, budget: Budget) -> dict:
    """把一个 case 单独放进一次性单 worker 池跑 → 精确暴露真凶。

    若它就是毒池的那个（worker 再次被 SIGKILL）→ 池碎 → 该 case 落 ERROR（真凶已隔离）；否则拿到
    正常行（健康兄弟恢复）。这是"单 case 崩不杀全轮"从口号变成真保证的落点。"""
    try:
        completed, pending = _drain_pool([(cid, doc)], policy, 1, budget)
    except Exception as e:                                       # noqa: BLE001 — 建池本身失败也别外泄
        return {"case_id": cid, "policy": policy, "status": "ERROR",
                "reason": f"隔离重跑建池失败：{type(e).__name__}: {e}", "wall_s": None}
    if completed:
        return completed[0]
    return {"case_id": cid, "policy": policy, "status": "ERROR",             # 单池仍碎 → 真凶
            "reason": "worker 进程死亡（隔离重跑单池仍损坏 → 本 case 即真凶；健康兄弟已恢复）",
            "wall_s": None}


def _run_parallel(cases: list[tuple[str, dict]], policy: str, workers: int, budget: Budget) -> list[dict]:
    """ProcessPoolExecutor 并行跑，结果按 case_id 稳定排序（打分与顺序无关 → 与串行等价）。

    失败隔离**真的成立**（非口号）：正常路径一个池跑完、pending 空、零开销。若某 worker 进程被
    SIGKILL 毒化了池（--mem-mb OOM / native 崩溃），BrokenProcessPool 会让全 pending future 报错
    ——此时**不**把健康兄弟一并误判 ERROR，而是把 pending 拿去**重跑隔离**：先减半 worker 再跑一轮
    （抵御瞬时 OOM），仍碎的才逐个塞进一次性单池精确暴露真凶。故最终只有真崩的 case 落 ERROR。"""
    rows, pending = _drain_pool(cases, policy, workers, budget)
    if pending:
        # 池碎了：worker 进程级死亡毒化了全池。降级重跑，别让健康兄弟背锅。
        print(f"⚠ worker 池损坏，{len(pending)} case 转入重跑隔离（只有真凶会落 ERROR）",
              file=sys.stderr)
        second, pending = _drain_pool(pending, policy, max(1, workers // 2), budget)
        rows.extend(second)
        for cid, doc in pending:                                 # 仍碎的 → 逐个单池隔离出真凶
            rows.append(_run_isolated_single(cid, doc, policy, budget))
    rows.sort(key=lambda r: r["case_id"])
    return rows


def _scale_summary(rows: list[dict], workers: int, wall_total_s: float) -> dict:
    """并行吞吐 + 隔离读数：Σper-case（≈串行成本）/ wall_total（并行墙钟）= 加速比（亚线性证据）。"""
    wall_sum = sum(r.get("wall_s") or 0.0 for r in rows)
    return {
        "workers": workers, "n": len(rows),
        "wall_total_s": round(wall_total_s, 2), "wall_sum_s": round(wall_sum, 2),
        "speedup": round(wall_sum / wall_total_s, 2) if wall_total_s > 0 else None,
        "timeout": sum(1 for r in rows if r["status"] == "TIMEOUT"),
        "error": sum(1 for r in rows if r["status"] == "ERROR"),
        "skip": sum(1 for r in rows if r["status"] == "SKIP"),
    }


def run_suite(*, suite: str = "cases", only: str | None = None, policy: str = "rule",
              workers: int | None = None, budget: Budget | None = None) -> tuple[list[dict], dict | None]:
    """跑一个 suite，返回 (rows, scale_meta)。workers<=1 → 串行（旧路径，逐位不变，scale_meta=None）；
    workers>1 → 并行 + 沙箱/预算 + 失败隔离。cases suite 默认串行、parametric/both 默认并行。"""
    cases = _case_source(suite, only)
    if workers is None:
        workers = 1 if suite == "cases" else default_workers()
    workers = min(workers, max(1, len(cases)))     # 别开比 case 还多的 worker
    t0 = time.perf_counter()
    if workers <= 1:
        rows = [run_case(cid, doc, policy=policy) for cid, doc in cases]   # 旧串行路径，无沙箱、逐位不变
        return rows, None
    rows = _run_parallel(cases, policy, workers, budget or Budget())
    return rows, _scale_summary(rows, workers, time.perf_counter() - t0)


def run_eval(only: str | None = None, *, policy: str = "rule") -> list[dict]:
    """向后兼容入口（cases suite 串行）——与改造前逐位一致。规模化走 run_suite/main --suite。"""
    rows, _ = run_suite(suite="cases", only=only, policy=policy, workers=1)
    return rows


def main(argv: list[str]) -> int:
    only = None
    json_out = None
    policy = "rule"
    suite = "cases"
    workers = None
    budget = Budget()
    i = 0
    while i < len(argv):
        if argv[i] == "--case":
            only = argv[i + 1]; i += 2
        elif argv[i] == "--json":
            json_out = argv[i + 1]; i += 2
        elif argv[i] == "--policy":
            policy = argv[i + 1]; i += 2          # rule(默认) | llm；llm 后端见 decide_llm（env）
        elif argv[i] == "--suite":
            suite = argv[i + 1]; i += 2           # cases(默认,手工真值) | parametric(生成族) | both
        elif argv[i] == "--workers":
            workers = int(argv[i + 1]); i += 2    # 并行 worker 数；省略→cases 串行、parametric 自动
        elif argv[i] == "--wall-budget":
            budget.wall_s = float(argv[i + 1]); i += 2
        elif argv[i] == "--repro-timeout":
            budget.repro_timeout_s = int(argv[i + 1]); i += 2
        elif argv[i] == "--mem-mb":
            budget.mem_mb = int(argv[i + 1]); i += 2
        elif argv[i] == "--record-dir":
            os.environ["REPRO_RECORD_DIR"] = argv[i + 1]; i += 2   # C1：real 跑一遍把工具 fixture 录进去
        elif argv[i] == "--backend":
            os.environ["REPRO_BACKEND"] = argv[i + 1]; i += 2      # real（默认）| replay（离线，读 fixture）
        else:
            print(f"未知参数：{argv[i]}", file=sys.stderr); return 2
    rows, scale = run_suite(suite=suite, only=only, policy=policy, workers=workers, budget=budget)
    if not rows:
        print("无可跑 case（cases/*.json 需含 agent_run + ground_truth，或 --suite parametric）", file=sys.stderr)
        return 1
    print(render(rows, scale=scale))
    health = _health(rows)
    if json_out:
        Path(json_out).write_text(
            json.dumps({"rows": rows, "aggregate": _aggregate(rows), "health": health,
                        "scale": scale}, ensure_ascii=False, indent=2),
            encoding="utf-8")
        print(f"\n[结构化结果 → {json_out}]")
    # 退出码：全 SKIP/ERROR → 1（"没法跑"）；有产出但 harness 错误率超阈 → 3（幸存者偏差，聚合不可信）；否则 0。
    if not any(r["status"] == "OK" for r in rows):
        return 1
    return 0 if health["trustworthy"] else 3


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
