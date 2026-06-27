"""session —— agent 工具/结论 → 既有事件协议的发射缝（emit seam）。（G25，缺口2）

agent/ 与既有 kit 的唯一物理接缝：把 ToolResult / Evidence / Conclusion 追加进
<session>/events.ndjson，让它们①进 Print viewer 供人 review、②进轨迹供离线评分。
复用 scripts/occ-mesh-daemon.py 的纪律：append-only + flock(LOCK_EX) + 一次写整行 +
fsync，绝不 truncate。事件 schema 真源在 tools/Print/protocol/event.schema.json。

分层：底层 `_append` 的并发纪律是 load-bearing；`_emit` 盖上协议必填头
（schema_version/session_id/run_id/seq/timestamp_ns）；`emit_*` 做【契约→Print op】
的语义映射（note / run_end）。
"""
from __future__ import annotations

import fcntl
import json
import os
import time
from pathlib import Path

from .contracts import CausalHypothesis, Conclusion, Stage, ToolResult

SCHEMA_VERSION = "1.0"


class SessionWriter:
    """把 agent 产物追加进一个 Print session 的 events.ndjson。"""

    def __init__(
        self,
        session_dir: str | Path,
        *,
        session_id: str | None = None,
        run_id: str = "agent",
    ):
        self.session = Path(session_dir)
        self.events_path = self.session / "events.ndjson"
        # session_id 默认取 session 目录名；run_id 默认 "agent"（agent 轨道自己的写者命名空间）
        self.session_id = session_id or self.session.name or "session"
        self.run_id = run_id
        # seq 续接已有事件行数，避免与既有写者重号（单一 agent 决策回路为预期写者）
        self._seq = self._existing_line_count()

    def _existing_line_count(self) -> int:
        if not self.events_path.exists():
            return 0
        with self.events_path.open("r", encoding="utf-8") as fp:
            return sum(1 for _ in fp)

    def _append(self, event: dict) -> None:
        """append-only + flock + 整行 + fsync（镜像 occ-mesh-daemon.py，禁止 truncate）。"""
        line = json.dumps(event, ensure_ascii=False) + "\n"
        self.events_path.parent.mkdir(parents=True, exist_ok=True)
        with self.events_path.open("a", encoding="utf-8") as fp:
            fcntl.flock(fp.fileno(), fcntl.LOCK_EX)
            try:
                fp.write(line)
                fp.flush()
                os.fsync(fp.fileno())
            finally:
                fcntl.flock(fp.fileno(), fcntl.LOCK_UN)

    def _emit(self, op: str, **fields) -> dict:
        """盖上协议必填头并落盘；返回写出的整条事件（便于测试/轨迹）。"""
        event = {
            "schema_version": SCHEMA_VERSION,
            "session_id": self.session_id,
            "run_id": self.run_id,
            "seq": self._seq,
            "timestamp_ns": time.time_ns(),
            "op": op,
        }
        event.update({k: v for k, v in fields.items() if v is not None})
        self._seq += 1
        self._append(event)
        return event

    @staticmethod
    def _source_obj(source: str | None) -> dict | None:
        """'file:line' → {file, line}（对齐 event.schema.json $defs.source）。"""
        if not source:
            return None
        file, sep, tail = source.rpartition(":")
        if sep and tail.isdigit():
            return {"file": file, "line": int(tail)}
        return {"file": source}

    @staticmethod
    def _hypothesis_dict(h: CausalHypothesis) -> dict:
        return {
            "stage": h.stage.value,
            "chain": [s.value for s in h.chain],
            "cause": h.cause,
            "entities": list(h.entities),
            "localization_depth": h.localization_depth,
            "counterfactual": h.counterfactual,
            "confidence": h.confidence,
            "evidence": [
                {"summary": e.summary, "artifact_id": e.artifact_id, "source": e.source}
                for e in h.evidence
            ],
        }

    def emit_tool_result(self, result: ToolResult) -> dict:
        """ToolResult → `note` 事件（op=note 需 level+message）。

        level：调用成功 → info；调用本身失败 → infrastructure_failure。
        （几何失败属 ok=True，其语义在 payload，不抬到 note 的 level。）
        """
        level = "info" if result.ok else "infrastructure_failure"
        message = result.summary or f"{result.tool}: {'ok' if result.ok else (result.error or 'failed')}"
        metadata = {"tool": result.tool, "ok": result.ok}
        if result.artifact_id is not None:
            metadata["artifact_id"] = result.artifact_id
        if result.payload:
            metadata["payload"] = result.payload
        if result.error is not None:
            metadata["error"] = result.error
        return self._emit(
            "note",
            level=level,
            message=message,
            source=self._source_obj(result.source),
            metadata=metadata,
        )

    def emit_conclusion(self, conclusion: Conclusion) -> dict:
        """Conclusion → `run_end` 事件（op=run_end 需 status）。

        status：弃权 → aborted；有因果假设 → succeeded；否则 → failed。
        分级因果假设 + 弃权理由进 summary（可渲染 / 可离线评分）。
        """
        if conclusion.abstained:
            status = "aborted"
        elif conclusion.hypotheses:
            status = "succeeded"
        else:
            status = "failed"

        top = conclusion.hypotheses[0] if conclusion.hypotheses else None
        if conclusion.abstained:
            message = f"abstained: {conclusion.abstain_reason or '证据不足，交人兜底'}"
        elif top is not None:
            message = f"root={top.stage.value} chain={'→'.join(s.value for s in top.chain)} conf={top.confidence:.2f}"
        else:
            message = "no hypothesis"

        summary = {
            "abstained": conclusion.abstained,
            "abstain_reason": conclusion.abstain_reason,
            "hypotheses": [self._hypothesis_dict(h) for h in conclusion.hypotheses],
        }
        return self._emit("run_end", status=status, message=message, summary=summary)
