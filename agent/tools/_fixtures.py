"""共享 record/replay fixture 层（P1b C1）——把 reproduce 的双后端模式抽出来给全工具层复用。

目标：`REPRO_BACKEND=replay` 一个环境开关，让 check_valid/triage/reproduce（及后续探针）全部读**录制
fixture**、不拉 OCCT/FreeCADCmd 栈 → 真·离线 eval（CI 无二进制也能跑全链）。

**诚实纪律**：
  - **键设计**含所有会改变输出的输入（reproduce: radius+tolerance+edges+op；check_valid: brep 内容哈希；
    triage: case+edge_index+edges）——避免"同名 fixture 撞键"这类静默错值（reproduce 旧键漏了
    tolerance/edges 就有此 bug）。
  - replay-miss 抛 `FixtureNotRecorded`（**刻意不继承 FileNotFoundError**）→ runner 归 **ERROR 非 SKIP**：
    漏录是响亮的失败，绝不静默当"环境缺件"而掉出打分（那正是幸存者偏差型撒谎 eval）。
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path


class FixtureNotRecorded(RuntimeError):
    """replay 后端遇未录制 fixture 时抛（不继承 FileNotFoundError → runner 归 ERROR 非 SKIP）。"""


def safe_token(s: str) -> str:
    """filename-safe token。已 filename-safe（合成 id）→ 原样（保号，现有 fixture 名零漂移）；含
    路径不安全字符（真实模型 brep:/abs 等）→ basename + 短 hash，避免斜杠/冒号造出不存在的嵌套路径。"""
    if re.fullmatch(r"[A-Za-z0-9_.-]+", s):
        return s
    base = re.sub(r"[^A-Za-z0-9]+", "_", Path(s.split(":", 1)[-1]).stem) or "shape"
    return f"{base}_{hashlib.sha1(s.encode('utf-8')).hexdigest()[:8]}"


def content_hash(path: str | Path) -> str:
    """文件内容哈希——brep 类工具按**内容**寻址（brep 落 per-run tmp 目录、路径不稳，内容才稳）。"""
    return hashlib.sha1(Path(path).read_bytes()).hexdigest()[:16]


def _sanitize(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.=-]+", "_", s)


def fixture_path(record_dir: str | Path, tool: str, key: dict) -> Path:
    """`{tool}__{k1-v1_k2-v2...}.json`，key 按名排序 → 跨 run 稳定；None 值不入键。超长名尾部换 hash。"""
    parts = "_".join(f"{k}-{key[k]}" for k in sorted(key) if key[k] is not None)
    name = _sanitize(f"{tool}__{parts}" if parts else tool)
    if len(name) > 180:
        name = name[:150] + "_" + hashlib.sha1(name.encode("utf-8")).hexdigest()[:12]
    return Path(record_dir) / f"{name}.json"


def resolve_backend(explicit: str | None) -> str:
    """显式 backend 优先；否则 REPRO_BACKEND（eval-wide 开关）；再否则 "real"。"""
    return explicit if explicit is not None else os.environ.get("REPRO_BACKEND", "real")


def resolve_record_dir(explicit: str | None) -> str | None:
    """显式 record_dir 优先；否则 REPRO_RECORD_DIR（runner --record-dir 注入）；再否则 None（不录）。"""
    return explicit if explicit is not None else os.environ.get("REPRO_RECORD_DIR")


def load(fp: str | Path) -> dict:
    return json.loads(Path(fp).read_text(encoding="utf-8"))


def dump(fp: str | Path, obj: dict) -> None:
    Path(fp).parent.mkdir(parents=True, exist_ok=True)
    Path(fp).write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
