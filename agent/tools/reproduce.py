"""reproduce(case) — 跑 FreeCADCmd recompute，返回结构化 RunEnd（A1 / G2 / 架构 §24）。

real 后端：env 驱动 `_fillet_harness.py` 在 FreeCADCmd 进程内构建几何 + `makeFillet`，
捕获异常/产出形状，回吐 RunEnd JSON。replay 后端：读已录制的 RunEnd fixture（G7），
让 eval 不必每次拉起重型 FreeCAD 栈。

⚠️ RunEnd.status 表"recompute 是否跑完并产出形状"，**非几何有效性**——产出形状
（bad_shape）的有效性由 check_valid 独立判（全项目禁用裸 IsDone()）。reproduce 刻意
不调 check_valid，两者在 investigate loop 里组合，避免"跑完=有效"的代理奖励陷阱。
"""
from __future__ import annotations

import hashlib
import json
import os
import re
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


def _safe_token(case_id: str) -> str:
    """把 case_id 变成 filename-safe token（G26）。

    合成 id（box/wedge/box-flat/wedge-thin/pocket…）本就 filename-safe → 原样返回，
    保持现有 fixture / record→replay 文件名逐字不变（回归零漂移）。含路径不安全字符的
    真实模型 id（`brep:/abs/path/m.brep` 等）→ basename + 全串短 hash，避免斜杠/冒号
    在文件名里造出不存在的嵌套路径（否则 out_json 写不出 → 静默 "harness 无输出"）。
    """
    if re.fullmatch(r"[A-Za-z0-9_.-]+", case_id):
        return case_id
    base = re.sub(r"[^A-Za-z0-9]+", "_", Path(case_id.split(":", 1)[-1]).stem) or "shape"
    return f"{base}_{hashlib.sha1(case_id.encode('utf-8')).hexdigest()[:8]}"


def _fixture_path(record_dir, case_id: str, radius: float) -> Path:
    return Path(record_dir) / f"{_safe_token(case_id)}__r{radius}.json"


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
    tolerance: float | None = None,
    backend: str = "real",
    out_dir: str | None = None,
    record_dir: str | None = None,
    timeout_s: int = 120,
    edges: str | None = None,
) -> RunEnd:
    """backend: "real"(FreeCADCmd) | "replay"(录制 fixture)。

    out_dir：产出（RunEnd json + bad_shape brep）落地目录；None → mkdtemp（持久，caller 负责清）。
    record_dir：real 跑完把 RunEnd + brep 录进去，供 replay 离线重放。
    tolerance：A7 WP3 互斥反事实——fillet 前对几何 fixTolerance(值)，只动容差不动半径（None=不动）。
    edges：G26 单/多边聚焦——逗号分隔 1-based 边号（"3" / "1,4"），透传 REPRO_EDGES；
    None/"" → fillet 全部边（合成 case 现状，向后兼容）。真实模型必给（否则 fillet 全部边失真）。
    """
    r = 1.0 if radius is None else float(radius)
    tok = _safe_token(case_id)

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
    out_json = out / f"{tok}__r{r}.runend.json"
    out_brep = out / f"{tok}__r{r}.brep"

    env = dict(os.environ)
    env.update({
        "REPRO_CASE": case_id,
        "REPRO_RADIUS": str(r),
        "REPRO_OUT_BREP": str(out_brep),
        "REPRO_OUT_JSON": str(out_json),
    })
    if tolerance is not None:
        env["REPRO_TOLERANCE"] = str(tolerance)
    else:
        env.pop("REPRO_TOLERANCE", None)            # 防继承外层 env 的残留值
    if edges:
        env["REPRO_EDGES"] = str(edges)
    else:
        env.pop("REPRO_EDGES", None)                # 防继承外层 env 的残留值污染合成 case
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
            dst = rec / f"{tok}__r{r}.brep"
            shutil.copy(data["bad_shape"], dst)
            data["bad_shape"] = str(dst)
        _fixture_path(rec, case_id, r).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    return _from_dict(data)
