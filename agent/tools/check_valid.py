"""check_valid(brep_path) — 几何有效性判据，替代 IsDone()（A2 / G17）。

成功判据 = BRepCheck_Analyzer + 自交 + G1/切向 + 拓扑增量（docs/root-cause-verification.md §2）。
全项目以此为成功判据；裸 IsDone() 仅作诊断信号。

实做：shell out 到同 ABI 的 `tools/occ-debug-mesh`（已编译，link debug OCCT V7_8_1）。
它用 `BRepCheck_Analyzer` 遍历 standalone + context 状态，写 `<base>.defects.json`
（每条 {category, source, severity, status, ref?}）。本函数解析该 sidecar → ValidityReport。

⚠️ 覆盖边界（诚实标注——reward signal 一旦悄悄判错整个 eval 跟着腐坏）：
  ✅ BRepCheck_Analyzer 全量（NotClosed / FreeEdge / Invalid* / SelfIntersectingWire …）
  ✅ wire 级自交（BRepCheck_SelfIntersectingWire）
  ✅ 面面 / 实体级自交（BOPAlgo_CheckerSI，O1）——occ-debug-mesh `--check-si` 跑，抓
     "IsDone+BRepCheck 过但两面互相穿插"的假绿（source=bop_checkersi）。
  ❌ G1 / 切向连续性、拓扑增量——本工具不覆盖；g1_violations 恒空，notes 标明（follow-up）。

valid = 没有 severity=="error" 的缺陷。
"""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path

from agent.contracts import ValidityReport

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_BIN = _REPO_ROOT / "tools" / "occ-debug-mesh" / "build" / "occ-debug-mesh"


def _resolve_bin() -> Path:
    """occ-debug-mesh 路径：环境变量 OCC_DEBUG_MESH_BIN 优先，否则仓库内默认构建。"""
    env = os.environ.get("OCC_DEBUG_MESH_BIN")
    bin_path = Path(env) if env else _DEFAULT_BIN
    if not bin_path.exists():
        raise FileNotFoundError(
            f"occ-debug-mesh 未找到：{bin_path}"
            f"（设 OCC_DEBUG_MESH_BIN，或先 scripts/build-occ-debug-mesh.sh）"
        )
    return bin_path


def _summary_line(stdout: str) -> str:
    """从 stdout 摘出 'N faces, … , X failed, Y defects' 一段（仅供 notes 展示）。"""
    for line in stdout.splitlines():
        if "faces" in line and "defects" in line:
            return line.split(": ", 1)[-1].strip() if ": " in line else line.strip()
    return ""


def check_valid(brep_path: str, *, timeout_s: int = 30) -> ValidityReport:
    """跑 occ-debug-mesh 的 BRepCheck 缺陷遍历 → 结构化有效性判据。

    工具失败（超时 / 非零退出 / 无 sidecar）一律判 valid=False 并在 notes 说明，
    绝不把"工具崩了"静默当成"几何有效"。
    """
    brep = Path(brep_path)
    if not brep.exists():
        raise FileNotFoundError(f"BREP 不存在：{brep}")
    bin_path = _resolve_bin()

    with tempfile.TemporaryDirectory(prefix="check_valid_") as d:
        out_mesh = Path(d) / "s.mesh.json"
        cmd = [str(bin_path), "--timeout", str(timeout_s), "--check-si", str(brep), str(out_mesh)]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_s + 10)
        except subprocess.TimeoutExpired:
            return ValidityReport(valid=False, notes=f"occ-debug-mesh 超时(>{timeout_s}s)：{brep.name}")
        if proc.returncode != 0:
            err = proc.stderr.strip() or proc.stdout.strip()
            return ValidityReport(valid=False, notes=f"occ-debug-mesh 退出码 {proc.returncode}：{err}")

        defect_files = list(Path(d).glob("*.defects.json"))
        if not defect_files:
            return ValidityReport(valid=False, notes="occ-debug-mesh 未产出 defects sidecar")
        defects = json.loads(defect_files[0].read_text(encoding="utf-8"))

    errors = [x for x in defects if x.get("severity") == "error"]
    self_x = [x for x in defects if x.get("category") == "self_intersection"]

    bop_si = [x for x in self_x if x.get("source") == "bop_checkersi"]
    notes = (
        f"{len(defects)} defects ({len(errors)} error); "
        f"自交=BRepCheck wire 级 + BOPAlgo_CheckerSI 面面级（bop_si={len(bop_si)}）；"
        f"G1/切向/拓扑增量未覆盖。"
    )
    summary = _summary_line(proc.stdout)
    if summary:
        notes = f"{summary} | {notes}"

    return ValidityReport(
        valid=not errors,
        self_intersections=self_x,
        invalid_subshapes=errors,
        g1_violations=[],
        notes=notes,
    )
