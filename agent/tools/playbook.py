"""query_playbook(signature) — 检索决策表节点（A2 / G4 / G19）。

读 playbook/fillet-failures.json（环境无 PyYAML，故用 JSON；schema 见
playbook/blend-failure-ontology.md §5 与 fillet-failures.yaml）。

symptom 是**触发条件（适配层）**而非结论：按 symptom 匹配出一个近端签名节点，
节点带 distal→proximate 排序的 root_cause_candidates。匹配语义（symptom 里出现
哪些键就要求哪些键，缺省键不约束）：
  exception_contains : 子串 ∈ signature["exception"]
  phase / is_done / valid / 其它 : 全等
"""
from __future__ import annotations

import json
from pathlib import Path

_TABLE = Path(__file__).resolve().parents[1] / "playbook" / "fillet-failures.json"


def _load_nodes() -> list[dict]:
    if not _TABLE.exists():
        return []
    data = json.loads(_TABLE.read_text(encoding="utf-8"))
    if isinstance(data, list):
        return data
    return data.get("signatures", [])


def _matches(symptom: dict, signature: dict) -> bool:
    for key, want in symptom.items():
        if key == "exception_contains":
            if want not in (signature.get("exception") or ""):
                return False
        else:
            if signature.get(key) != want:
                return False
    return True


def query_playbook(signature: dict) -> dict | None:
    """signature: {exception, phase, is_done, ...}。返回首个命中的节点或 None。"""
    for node in _load_nodes():
        if _matches(node.get("symptom", {}), signature):
            return node
    return None
