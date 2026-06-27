"""reproduce(case) — 跑 FreeCADCmd recompute，返回结构化 RunEnd（A1 / G2 / 架构 §24）。

real 后端：env 驱动 `_fillet_harness.py` 在 FreeCADCmd 进程内构建几何 + `makeFillet`，
捕获异常/产出形状，回吐 RunEnd JSON。replay 后端：读已录制的 RunEnd fixture（G7），
让 eval 不必每次拉起重型 FreeCAD 栈。

⚠️ RunEnd.status 表"recompute 是否跑完并产出形状"，**非几何有效性**——产出形状
（bad_shape）的有效性由 check_valid 独立判（全项目禁用裸 IsDone()）。reproduce 刻意
不调 check_valid，两者在 investigate loop 里组合，避免"跑完=有效"的代理奖励陷阱。
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from agent.contracts import RunEnd

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_FREECADCMD = _REPO_ROOT / "FreeCAD" / "build" / "debug" / "bin" / "FreeCADCmd"
_HARNESS = Path(__file__).resolve().parent / "_fillet_harness.py"


def _resolve_freecadcmd() -> Path:
    env = os.environ.get("REPRO_FREECADCMD")
    p = Path(env) if env else _DEFAULT_FREECADCMD
    if not p.exists():
        raise FileNotFoundError(
            f"FreeCADCmd 未找到：{p}"
            f"（设 REPRO_FREECADCMD，或先 scripts/bootstrap.sh 构建 FreeCAD fork）"
        )
    return p


def _fixture_path(record_dir, case_id: str, radius: float) -> Path:
    return Path(record_dir) / f"{case_id}__r{radius}.json"


def _from_dict(d: dict) -> RunEnd:
    return RunEnd(
        status=d.get("status", "failed"),
        exception=d.get("exception"),
        phase=d.get("phase"),
        faulty_contours=d.get("faulty_contours", []),
        faulty_vertices=d.get("faulty_vertices", []),
        bad_shape=d.get("bad_shape"),
        is_done=d.get("is_done"),
    )


def reproduce(
    case_id: str,
    *,
    radius: float | None = None,
    backend: str = "real",
    out_dir: str | None = None,
    record_dir: str | None = None,
    timeout_s: int = 120,
) -> RunEnd:
    """backend: "real"(FreeCADCmd) | "replay"(录制 fixture)。

    out_dir：产出（RunEnd json + bad_shape brep）落地目录；None → mkdtemp（持久，caller 负责清）。
    record_dir：real 跑完把 RunEnd + brep 录进去，供 replay 离线重放。
    """
    r = 1.0 if radius is None else float(radius)

    if backend == "replay":
        if not record_dir:
            raise ValueError("replay 后端需 record_dir")
        fp = _fixture_path(record_dir, case_id, r)
        if not fp.exists():
            raise FileNotFoundError(f"无录制 fixture：{fp}")
        return _from_dict(json.loads(fp.read_text(encoding="utf-8")))

    if backend != "real":
        raise ValueError(f"未知 backend：{backend}")

    bin_path = _resolve_freecadcmd()
    out = Path(out_dir) if out_dir else Path(tempfile.mkdtemp(prefix="reproduce_"))
    out.mkdir(parents=True, exist_ok=True)
    out_json = out / f"{case_id}__r{r}.runend.json"
    out_brep = out / f"{case_id}__r{r}.brep"

    env = dict(os.environ)
    env.update({
        "REPRO_CASE": case_id,
        "REPRO_RADIUS": str(r),
        "REPRO_OUT_BREP": str(out_brep),
        "REPRO_OUT_JSON": str(out_json),
    })
    try:
        proc = subprocess.run(
            [str(bin_path), str(_HARNESS)], env=env,
            capture_output=True, text=True, timeout=timeout_s,
        )
    except subprocess.TimeoutExpired:
        return RunEnd(status="failed", exception=f"FreeCADCmd 超时(>{timeout_s}s)", phase="timeout")

    if not out_json.exists():
        tail = (proc.stderr or proc.stdout or "")[-300:]
        return RunEnd(status="failed", exception=f"harness 无输出(rc={proc.returncode}): {tail}", phase="harness")

    data = json.loads(out_json.read_text(encoding="utf-8"))

    if record_dir:
        rec = Path(record_dir)
        rec.mkdir(parents=True, exist_ok=True)
        # brep 一并录进 record_dir，让 replay 自洽（否则 bad_shape 指向临时目录会失效）
        if data.get("bad_shape") and Path(data["bad_shape"]).exists():
            dst = rec / f"{case_id}__r{r}.brep"
            shutil.copy(data["bad_shape"], dst)
            data["bad_shape"] = str(dst)
        _fixture_path(rec, case_id, r).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    return _from_dict(data)
