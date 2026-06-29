"""capture(...) — agent 侧 LLDB 活几何 capture 桥（A7 capture 接缝 / G13）。

驱动 `lldb -b` 跑一个会触发 fillet 失败的 FreeCAD 脚本，在指定断点处用
scripts/occ_capture.py 的 occ_emit_shape 把**活的 OCCT 几何**经 `BRepTools::Write`
序列化成 BREP，返回 {entity_id: brep 路径}。配 ssi_probe：capture 失败现场两面 →
SSIReport，把 S3 机制判别用到**真 fillet 失败**上（而非构造夹具）。

前置（缺一不可，缺则抛 FileNotFoundError）：
  - FreeCAD/build/debug/bin/FreeCADCmd（debug 构建）
  - occt/install/debug/lib（debug OCCT，OSO 调试映射在 → 断点能绑；
    见记忆 occt-debug-map-stripped-by-wl-s / docs/occt-debugging.md）
  - scripts/occ_capture.py（已修 OCCT 7.8 的 BRepTools::Write 三参签名）

边界：断点位置与两面表达式（如 "S1.Face()"）依失败阶段而定，由调用方给——本桥
只负责 orchestrate + 收 BREP，不猜 ChFi3d 内部变量。
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from agent.contracts import SSIReport
from agent.tools.ssi_probe import ssi_probe

_REPO = Path(__file__).resolve().parents[2]
_FC = _REPO / "FreeCAD" / "build" / "debug" / "bin" / "FreeCADCmd"
_FC_DIR = _REPO / "FreeCAD"
_OCC_LIB = _REPO / "occt" / "install" / "debug" / "lib"
_OCC_CAPTURE = _REPO / "scripts" / "occ_capture.py"
_TOOLS_DIR = Path(__file__).resolve().parent       # 含 _fillet_harness.py（fail_script 复用其 build_shape）

# 已知失败现场的 SSI capture spec，按 **agent case 串**键控（与 _fillet_harness.build_shape 同约定）。
# 只登记 LLDB truth-run 验证过、句柄具名可抓的现场——box overflow 的 StripeEdgeInter 两带在匿名
# DStr 里（见记忆 fillet-overflow-crash-site），无法干净取面，故不登记 → 该处 SSI 判别照实 untestable。
CAPTURE_SPECS = {
    # 薄楔近切：StartSol，HS1/HS2 = Handle(BRepAdaptor_Surface) 两支撑面，具名可抓。
    # 见 cases/wedge-sliver.json truth_run + 记忆 fillet-startsol-capture-point（2026-06-27 验证）。
    "wedge": {
        "breakpoint": "ChFi3d_Builder_2.cxx:944",
        "face_a_expr": "HS1->Face()",
        "face_b_expr": "HS2->Face()",
    },
}


def _pixi() -> str:
    return shutil.which("pixi") or str(Path.home() / ".pixi" / "bin" / "pixi")


def _resolve() -> None:
    missing = [str(p) for p in (_FC, _OCC_LIB, _OCC_CAPTURE) if not p.exists()]
    if missing:
        raise FileNotFoundError("LLDB capture 前置缺失：" + ", ".join(missing))


def prereqs_ok() -> bool:
    """LLDB capture 前置（debug FreeCAD/OCCT + occ_capture）是否齐备（缺则调用方应弃权，不伪绿）。"""
    try:
        _resolve()
        return True
    except FileNotFoundError:
        return False


def capture_spec_for(case: str):
    """返回该 agent case 的 SSI capture spec（断点 + 两面表达式），未登记则 None。"""
    return CAPTURE_SPECS.get(case)


def make_fail_script(case: str, radius: float, *, edges: str = "", out_dir=None) -> str:
    """生成一个会触发该 case fillet 失败的 FreeCAD 脚本路径（供 capture 的断点命中）。

    复用 `_fillet_harness.build_shape/select_edges` 这一份几何真源（不重复构建逻辑）：
    脚本在 FreeCADCmd 内 build → makeFillet，断点在 OCCT 内命中后由 occ_emit_shape 抓面。
    """
    d = Path(out_dir or tempfile.mkdtemp(prefix="failscript_"))
    d.mkdir(parents=True, exist_ok=True)
    script = d / f"fail_{case}_r{radius}.py"
    script.write_text(
        "import sys\n"
        f"sys.path.insert(0, {str(_TOOLS_DIR)!r})\n"
        "from _fillet_harness import build_shape, select_edges\n"
        f"shape = build_shape({case!r})\n"
        f"edges = select_edges(shape, {edges!r})\n"
        "try:\n"
        f"    shape.makeFillet({float(radius)!r}, edges)\n"
        "except Exception as e:\n"
        "    print('FILLET_EXC', type(e).__name__, e)\n",
        encoding="utf-8",
    )
    return str(script)


def capture(fail_script, breakpoint, emits, *, session_dir=None, timeout_s=300) -> dict:
    """在 breakpoint 处对每个 (entity_id, shape_expr) 跑 occ_emit_shape，返回 {id: brep_path}。

    emits: [(entity_id, shape_expr), ...]；shape_expr 是断点作用域里可求值的 C++
           （如 "E"、"S1.Face()"）。entity_id 可含 "/"（落 assets/<run>/<id>.brep）。
    """
    _resolve()
    sess = Path(session_dir or tempfile.mkdtemp(prefix="capture_"))
    cmds = [
        f"settings set target.env-vars DYLD_LIBRARY_PATH={_OCC_LIB}",
        f"command script import {_OCC_CAPTURE}",
        f"b {breakpoint}",
        "run",
    ]
    cmds += [f"occ_emit_shape {expr} --id {ent_id}" for ent_id, expr in emits]
    cmds.append("quit")

    argv = [_pixi(), "run", "--frozen", "--", "lldb", "-b"]
    for c in cmds:
        argv += ["-o", c]
    argv += ["--", str(_FC), str(fail_script)]

    env = dict(os.environ)
    env["OCC_DEBUG_SESSION"] = str(sess)
    env["PYTHONIOENCODING"] = "utf-8"
    try:
        proc = subprocess.run(argv, cwd=str(_FC_DIR), env=env,
                              capture_output=True, text=True, timeout=timeout_s)
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"lldb capture 超时(>{timeout_s}s)")

    out = {}
    for ent_id, _ in emits:
        hits = list(sess.glob(f"assets/*/{ent_id}.brep"))
        if hits:
            out[ent_id] = str(hits[0])
    if not out:
        tail = (proc.stderr or proc.stdout or "")[-500:]
        raise RuntimeError(f"capture 未产出 BREP（断点未命中 / expr 求值失败）。lldb tail:\n{tail}")
    return out


def capture_ssi(fail_script, breakpoint, face_a_expr, face_b_expr,
                *, tangent_eps_deg=5.0, timeout_s=300) -> SSIReport:
    """capture 失败现场两面 → ssi_probe：S3 机制判别用到真 fillet 失败上。"""
    breps = capture(
        fail_script, breakpoint,
        [("ssi/faceA", face_a_expr), ("ssi/faceB", face_b_expr)],
        timeout_s=timeout_s,
    )
    if "ssi/faceA" not in breps or "ssi/faceB" not in breps:
        raise RuntimeError(f"两面未全部 capture 到：{list(breps)}")
    return ssi_probe(breps["ssi/faceA"], breps["ssi/faceB"], tangent_eps_deg=tangent_eps_deg)


if __name__ == "__main__":
    # 端到端 demo（已证）：在 BRepFilletAPI_MakeFillet::Add 抓被 fillet 的边 → 真 BREP。
    import sys

    script = sys.argv[1] if len(sys.argv) > 1 else None
    if not script:
        print("用法: python -m agent.tools.capture <会触发 fillet 的 FreeCAD 脚本.py>")
        raise SystemExit(2)
    got = capture(script, "BRepFilletAPI_MakeFillet.cxx:106", [("capdemo/edgeE", "E")])
    print("captured:", got)
    for ent_id, path in got.items():
        head = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()[:1]
        print(f"  {ent_id}: {path}  ({Path(path).stat().st_size}B, head={head})")
