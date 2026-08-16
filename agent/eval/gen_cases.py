"""参数化 case 生成器 —— 把 3 个已验证 builder 开成 100+ case 的规模化 eval 套件（P0）。

**为什么可批量而不造假**：GT 全部来自**几何第一性**（README §7 GT 四来源之②），不是拍脑袋：
  - box_false_green（boxp）：相邻两 fillet 带在最小维度上重叠 ⇔ 2·rf > minEdge。**实测**（见
    P0.3）rf=minEdge/2 恰为一条极窄的 NotDone 缝、rf>minEdge/2 则是一片宽而稳的**假绿**带
    （is_done=True 但自交无效 selfX=8）。取 rf ≥ minEdge·0.55 稳落假绿带 → agent 须靠
    check_valid（非 IsDone）抓出 → 这是 thinplate-false-green(box-flat r=1.5) 验证过的现象的
    规模化推广（root S2 距端、S3 自交为症状；免埋点定位止于症状级 0.4，正是该测的诚实下限）。
  - geometric_curvature（pocketp）：滚球半径 rf 大于凹壁曲率半径 RC ⇔ 偏移面无解。取
    rf ≥ RC·1.3 且 rf < boxMinEdge/2（大盒子，外边不抢戏）→ 唯一失效在凹壁 → S2 曲率。
  - geometric_near_tangent（wedgep）：两支撑面近切（二面角 θ<10°）→ 滚球塞不进，**半径无关**。
    取 θ∈{0.5,1,2,3,4}°（tip=LEN·tanθ 使实测二面角恰为标称值，稳定 fire near_tangent，避开
    <0.02° 弃权 / >8° 可行两条边界）。
  - clean（expected_abstain）：rf 远小于所有临界（box rf≤minEdge·0.3、pocket rf≤RC·0.5）→
    fillet 成功且有效 → agent 应正确弃权（测 false_commit 幻觉率）。

**诚实边界**：
  - 参数区间都留**余量**、避开临界带（跨平台 OCCT 非确定，README P0 容差归一）；临界带**不造 case**。
  - 本套件测【失效分类 + stage 级定位 + 吞吐】，**不**测实体级定位（entities=[]，故 entity 维
    None、不参与）——实体精度是 13 个手工真值 case 的活（那里有 LLDB/几何真值支持具名 token）。
  - 每 case 标 `synthetic:True` + `gt_basis:"parametric_first_principles"` + `family`，
    runner/报告按此把参数化套件与 13 手工套件**分开**，绝不把合成分布冒充真实世界分布。

用法：
  python -m agent.eval.gen_cases            # 打印 case 清单 + 各族计数
  python -m agent.eval.gen_cases --json d/  # 把每个 case 落成 JSON（与 cases/*.json 同 schema）
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

# ── 扫描网格（都在各 regime 内留余量，见模块 docstring 的第一性推导）────────────────
_FG_DIMS = [                             # (LX,LY,LZ)；minEdge=min → 相邻带在最小维度重叠自交
    (10, 20, 30), (12, 20, 30), (8, 20, 30), (10, 16, 40), (14, 22, 28),
    (9, 18, 27), (11, 20, 30), (13, 24, 30), (10, 24, 36), (12, 26, 30),
]
_FG_FRACS = [0.55, 0.65, 0.75, 0.85]     # rf = minEdge·frac，全 > minEdge/2 → 稳落假绿带

_CURV_RC = [2, 3, 4, 5, 6, 7]                  # 凹壁曲率半径
_CURV_MULTS = [1.3, 1.6, 1.9, 2.2]            # rf = RC·mult > RC → 曲率无解（且 < boxMinEdge/2）

_NT_ANGLES_DEG = [0.5, 1.0, 2.0, 3.0, 4.0]    # 支撑面二面角（近切带，半径无关）
_NT_LENS = [14, 18, 20, 22, 26]               # 楔长；tip = LEN·tan(θ)
_NT_WIDTH = 8
_NT_RADIUS = 1.0

_CLEAN_BOX_FRACS = [0.2, 0.3]                 # rf = minEdge·frac « minEdge/2 → 干净成功
_CLEAN_POCKET_MULT = 0.5                      # rf = RC·0.5 < RC → 凹壁可圆角、且远小于盒子


def _doc(case_id, family, builder, radius, *, true_chain, failure_class,
         expected_abstain, evidence, fix, dims=None, op="fillet") -> dict:
    """组装与 cases/*.json 同 schema 的 case doc（entities=[] —— 本套件不测实体级定位）。
    op：P1a 域轴——"chamfer" 时 agent_run 带 op；"fillet"（默认）不带 → 既有 fillet 族逐位不变。"""
    run = {"case": builder, "radius": radius}
    if op != "fillet":
        run["op"] = op
    return {
        "case_id": case_id,
        "synthetic": True,
        "gt_basis": "parametric_first_principles",
        "family": family,
        "input": {"builder": builder, "radius": radius, "dims": dims, "op": op},
        "agent_run": run,
        "ground_truth": {
            "true_chain": true_chain,
            "entities": [],                    # 规模套件不断言具名实体（见 docstring 诚实边界）
            "expected_evidence": evidence,
            "aligned_fix": fix,
            "failure_class": failure_class,
            "expected_abstain": expected_abstain,
        },
    }


def _box_false_green_cases() -> list[dict]:
    out = []
    for (lx, ly, lz) in _FG_DIMS:
        min_edge = min(lx, ly, lz)
        for frac in _FG_FRACS:
            rf = round(min_edge * frac, 2)
            out.append(_doc(
                f"gen-fgbox-{lx}x{ly}x{lz}-r{rf}", "box_false_green",
                f"boxp:{lx},{ly},{lz}", rf,
                true_chain=["S2", "S3"], failure_class=None,
                expected_abstain=False, dims=[lx, ly, lz],
                evidence=(f"2·rf={2 * rf} > minEdge={min_edge} → 相邻两 fillet 带重叠自交："
                          "is_done=True 但 check_valid 判无效（selfX）→ 假绿（root S2 距端 / S3 自交症状）"),
                fix="降半径至 < minEdge/2（假绿的根是半径过大致带重叠，非算法可救）"))
    return out


def _curvature_cases() -> list[dict]:
    out = []
    for rc in _CURV_RC:
        bx = by = 10 * rc                       # 大盒子：外边远离溢出（rf < boxMinEdge/2）
        bz = 5 * rc
        for mult in _CURV_MULTS:
            rf = round(rc * mult, 2)
            out.append(_doc(
                f"gen-curv-rc{rc}-r{rf}", "geometric_curvature",
                f"pocketp:{bx},{by},{bz},{rc}", rf,
                true_chain=["S2"], failure_class="geometric_curvature",
                expected_abstain=False, dims=[bx, by, bz, rc],
                evidence=(f"rf={rf} > 凹壁曲率半径 RC={rc} → 滚球比孔还大、偏移面无解（S2 几何曲率）；"
                          f"盒子 {bx}×{by}×{bz} 足够大、外边不溢出"),
                fix="降半径至 < 凹壁曲率半径（几何硬约束，非算法可救）"))
    return out


def _near_tangent_cases() -> list[dict]:
    out = []
    for ang in _NT_ANGLES_DEG:
        for length in _NT_LENS:
            tip = round(length * math.tan(math.radians(ang)), 4)
            out.append(_doc(
                f"gen-neartan-a{ang}-L{length}", "geometric_near_tangent",
                f"wedgep:{length},{tip},{_NT_WIDTH}", _NT_RADIUS,
                true_chain=["S2"], failure_class="geometric_near_tangent",
                expected_abstain=False, dims=[length, tip, _NT_WIDTH],
                evidence=(f"支撑面二面角 θ≈{ang}° < 10° → 两面近切、滚球塞不进（S2 近切，半径无关）"),
                fix="heal 近切支撑面使二面角非退化（几何约束）"))
    return out


def _clean_cases() -> list[dict]:
    out = []
    for (lx, ly, lz) in _FG_DIMS:
        min_edge = min(lx, ly, lz)
        for frac in _CLEAN_BOX_FRACS:
            rf = round(min_edge * frac, 2)
            out.append(_doc(
                f"gen-clean-box-{lx}x{ly}x{lz}-r{rf}", "clean",
                f"boxp:{lx},{ly},{lz}", rf,
                true_chain=[], failure_class=None, expected_abstain=True, dims=[lx, ly, lz],
                evidence=(f"rf={rf} « minEdge/2={min_edge / 2} → 无带重叠 → fillet 成功且有效，"
                          "agent 应正确弃权（无缺陷可归因）"),
                fix="—（无缺陷）"))
    for rc in _CURV_RC:
        bx = by = 10 * rc
        bz = 5 * rc
        rf = round(rc * _CLEAN_POCKET_MULT, 2)
        out.append(_doc(
            f"gen-clean-pocket-rc{rc}-r{rf}", "clean",
            f"pocketp:{bx},{by},{bz},{rc}", rf,
            true_chain=[], failure_class=None, expected_abstain=True, dims=[bx, by, bz, rc],
            evidence=(f"rf={rf} < 凹壁曲率半径 RC={rc} 且 « 盒子尺度 → fillet 成功且有效 → 正确弃权"),
            fix="—（无缺陷）"))
    return out


# ── P1a：chamfer 域族（op="chamfer"；GT 同几何第一性、实测 FreeCADCmd 定 margin）──────────
# 域差异（实测）：chamfer 溢出是"平斜面盖过面宽"2·d>minEdge、且 d>minEdge/2 是宽而稳的 NotDone 带
# （fillet 同处翻假绿）；假绿搬到**凹壁支撑**（pocketp d∈[RC·1.1,RC·1.7] 带）。见 chamfer-failures.json。

_CH_OVERFLOW_DIMS = _FG_DIMS[:6]              # boxp；2·d>minEdge → 相邻斜面重叠（NotDone，非假绿）
_CH_OVERFLOW_FRACS = [0.55, 0.7, 0.85]       # d = minEdge·frac，全 > minEdge/2 → 稳落 NotDone 溢出带
_CH_NT_ANGLES = [0.5, 1.0, 2.0, 3.0, 4.0]    # 近切二面角（与 fillet 同，triage op-无关）
_CH_NT_LENS = [16, 20, 24]
_CH_CURV_RC = [3, 4, 5, 6]                    # 凹壁曲率半径；大盒子(10·RC) 外边不抢戏
_CH_FG_MULTS = [1.2, 1.3]                     # d = RC·mult ∈ 假绿带（实测 RC·1.3 假绿 / RC·2.0 转 NotDone）


def _chamfer_overflow_cases() -> list[dict]:
    out = []
    for (lx, ly, lz) in _CH_OVERFLOW_DIMS:
        me = min(lx, ly, lz)
        for frac in _CH_OVERFLOW_FRACS:
            d = round(me * frac, 2)
            out.append(_doc(
                f"gen-ch-overflow-{lx}x{ly}x{lz}-d{d}", "chamfer_overflow",
                f"boxp:{lx},{ly},{lz}", d, op="chamfer",
                true_chain=["S2"], failure_class="algorithmic_overflow",
                expected_abstain=False, dims=[lx, ly, lz],
                evidence=(f"2·d={2 * d} > minEdge={me} → 最小维度上相邻两斜面重叠 → StdFail_NotDone（S2 溢出）"),
                fix="lower_distance 至 < minEdge/2，或两斜面求交互裁"))
    return out


def _chamfer_near_tangent_cases() -> list[dict]:
    out = []
    for ang in _CH_NT_ANGLES:
        for length in _CH_NT_LENS:
            tip = round(length * math.tan(math.radians(ang)), 4)
            out.append(_doc(
                f"gen-ch-neartan-a{ang}-L{length}", "chamfer_near_tangent",
                f"wedgep:{length},{tip},8", 1.0, op="chamfer",
                true_chain=["S2"], failure_class="geometric_near_tangent",
                expected_abstain=False, dims=[length, tip, 8],
                evidence=(f"支撑面二面角 θ≈{ang}° < 10° → 平斜面塞不进近切楔（S2 近切，triage op-无关）"),
                fix="heal 近切支撑面或 lower_distance"))
    return out


def _chamfer_false_green_cases() -> list[dict]:
    out = []
    for rc in _CH_CURV_RC:
        bx = by = 10 * rc
        bz = 5 * rc
        for mult in _CH_FG_MULTS:
            d = round(rc * mult, 2)
            out.append(_doc(
                f"gen-ch-fg-rc{rc}-d{d}", "chamfer_false_green",
                f"pocketp:{bx},{by},{bz},{rc}", d, op="chamfer",
                true_chain=["S2", "S6"], failure_class=None,
                expected_abstain=False, dims=[bx, by, bz, rc],
                evidence=(f"d={d} > 凹壁曲率半径 RC={rc}（但 <RC·1.7 未硬 NotDone）→ 斜面互穿写坏几何："
                          "is_done=True 但 check_valid 判无效（假绿）。根 S2 距端 / S6 检出。"
                          "诚实：免埋点定位止于 S6 症状级——凹壁假绿是 chamfer 域特定，见 transfer 文档。"),
                fix="lower_distance 至 ≤ 凹壁曲率半径（假绿根是 d>曲率致斜面互穿）"))
    return out


def _chamfer_clean_cases() -> list[dict]:
    out = []
    for (lx, ly, lz) in _CH_OVERFLOW_DIMS:
        me = min(lx, ly, lz)
        d = round(me * 0.3, 2)
        out.append(_doc(
            f"gen-ch-clean-box-{lx}x{ly}x{lz}-d{d}", "chamfer_clean",
            f"boxp:{lx},{ly},{lz}", d, op="chamfer",
            true_chain=[], failure_class=None, expected_abstain=True, dims=[lx, ly, lz],
            evidence=(f"d={d} « minEdge/2={me / 2} → 无斜面重叠 → chamfer 成功且有效 → 正确弃权"),
            fix="—（无缺陷）"))
    for rc in _CH_CURV_RC:
        bx = by = 10 * rc
        bz = 5 * rc
        d = round(rc * 0.5, 2)
        out.append(_doc(
            f"gen-ch-clean-pocket-rc{rc}-d{d}", "chamfer_clean",
            f"pocketp:{bx},{by},{bz},{rc}", d, op="chamfer",
            true_chain=[], failure_class=None, expected_abstain=True, dims=[bx, by, bz, rc],
            evidence=(f"d={d} < 凹壁曲率半径 RC={rc} 且 « 盒子尺度 → chamfer 成功且有效 → 正确弃权"),
            fix="—（无缺陷）"))
    return out


_FAMILIES = {
    "box_false_green": _box_false_green_cases,
    "geometric_curvature": _curvature_cases,
    "geometric_near_tangent": _near_tangent_cases,
    "clean": _clean_cases,
    # P1a chamfer 域族（证明本体领域无关；op="chamfer"）
    "chamfer_overflow": _chamfer_overflow_cases,
    "chamfer_near_tangent": _chamfer_near_tangent_cases,
    "chamfer_false_green": _chamfer_false_green_cases,
    "chamfer_clean": _chamfer_clean_cases,
}


def generate(families: list[str] | None = None) -> list[tuple[str, dict]]:
    """返回 [(case_id, doc)]，按 case_id 排序（与 runner._discover_cases 同形，可直接喂 run_case）。"""
    out: list[tuple[str, dict]] = []
    for fam, fn in _FAMILIES.items():
        if families and fam not in families:
            continue
        out.extend((d["case_id"], d) for d in fn())
    out.sort(key=lambda kv: kv[0])
    return out


def _counts() -> dict[str, int]:
    return {fam: len(fn()) for fam, fn in _FAMILIES.items()}


def main(argv: list[str]) -> int:
    json_dir = None
    i = 0
    while i < len(argv):
        if argv[i] == "--json":
            json_dir = argv[i + 1]; i += 2
        else:
            print(f"未知参数：{argv[i]}", file=sys.stderr); return 2
    cases = generate()
    counts = _counts()
    print(f"参数化 case 生成器（P0 规模化套件）—— 共 {len(cases)} case")
    for fam, n in counts.items():
        print(f"  {fam:<24} {n:>4}")
    if json_dir:
        d = Path(json_dir)
        d.mkdir(parents=True, exist_ok=True)
        for cid, doc in cases:
            (d / f"{cid}.json").write_text(json.dumps(doc, ensure_ascii=False, indent=2),
                                           encoding="utf-8")
        print(f"\n[{len(cases)} case → {d}]")
    else:
        for cid, _ in cases:
            print(f"    {cid}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
