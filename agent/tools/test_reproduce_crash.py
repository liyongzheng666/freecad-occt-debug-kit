"""P1.1 自测：python -m agent.tools.test_reproduce_crash

G6 崩溃归类：FreeCADCmd/OCCT 进程被信号打死（段错误/abort）时，reproduce 须把它归
phase="kernel_crash"（→ investigate 分支 C infrastructure 兜底弃权），而非与"harness 逻辑
没产出"混为 phase="harness"，更不能静默当成功。

用 monkeypatch 造确定性信号退出（returncode=-11 / 139）→ 无需真崩溃、无需 FreeCADCmd。
（OCCT 自然崩溃未必隔离可复现，见 docs 诚实修正——故这里测『归类逻辑』而非碰运气触发真崩溃。）
"""
from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from agent.tools import reproduce as R


class _FakeProc:
    def __init__(self, rc):
        self.returncode = rc
        self.stdout = ""
        self.stderr = "Segmentation fault: 11"


def _run_with_rc(rc):
    """跑 reproduce，但把 subprocess.run 换成"不产出 out_json + 指定 rc"，
    并把 FreeCADCmd 解析换成任意存在路径（不真跑）。返回 RunEnd。"""
    orig_run, orig_resolve = subprocess.run, R._resolve_freecadcmd
    R.subprocess.run = lambda *a, **k: _FakeProc(rc)          # 不写 out_json
    R._resolve_freecadcmd = lambda: Path(__file__)            # 任意存在文件即可
    try:
        with tempfile.TemporaryDirectory() as d:
            return R.reproduce("box", radius=15.0, out_dir=d)
    finally:
        R.subprocess.run, R._resolve_freecadcmd = orig_run, orig_resolve


def main() -> int:
    fails = []

    def check(name, cond):
        print(("PASS " if cond else "FAIL ") + name)
        if not cond:
            fails.append(name)

    neg = _run_with_rc(-11)                                   # POSIX：负 = 被信号 N 打死
    check("rc=-11(SIGSEGV) → phase=kernel_crash", neg.phase == "kernel_crash")
    check("rc=-11 → status=failed", neg.status == "failed")
    check("rc=-11 → 信号号 11 入 exception", "信号 11" in (neg.exception or ""))

    sh = _run_with_rc(139)                                    # 经 shell：128+11
    check("rc=139(128+SIGSEGV) → phase=kernel_crash", sh.phase == "kernel_crash")

    logic = _run_with_rc(1)                                   # 普通非零退出 = harness 逻辑没产出
    check("rc=1(普通失败) → phase=harness（非 kernel_crash）", logic.phase == "harness")

    print("\n" + ("ALL PASS" if not fails else f"{len(fails)} FAIL: {fails}"))
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
