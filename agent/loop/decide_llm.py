"""LLM 版 policy（A5 / G8）—— decide(state) 接缝的 LLM 臂。

与 `decide_rule` **同签名** `decide(state) -> {"run": cand} | {"conclude": True}`，在 investigate
同一决策接缝直接替换，便于 rule-vs-LLM A/B（同一 case 集、同一组工具、同一 eval.sh）。

**模型只在这一个点出现**：prompt 只含角色 + 当前结构化证据（verdicts / run_end）+ 命中的
playbook 节点（未跑候选 + 各自判别器）+ "选下一个未跑候选或下结论"。**不含**算法细节 / 算术 /
几何提取逻辑——这些都在确定性工具里。结论合成（取最 distal 命中者为根 + 失效三态）仍在
investigate 的确定性后处理，不归 LLM。

后端可插拔（env `AGENT_DECIDE_BACKEND`，与 reproduce 的 real/replay 同纪律）：
  claude_cli（默认）：shell out 本地 `claude -p`，**复用现有 Claude Code 鉴权**（无需 API key）。
  replay            ：读 `AGENT_DECIDE_RECORD` 录制的决策 → 离线确定复跑、零计费、可进 CI。
  api               ：留给他人接 anthropic SDK + key（见下方 stub）。

确定性：默认模型 `claude-opus-4-8` 已移除 sampling 参数（temperature/top_p/top_k 传了 400，
adaptive-thinking-only），故**确定性靠 record/replay**，不是 temperature=0。claude_cli 跑完把
(签名→action) 落 record_dir，replay 后端据此离线复现同一条决策轨迹。
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess

_MODEL = os.environ.get("AGENT_DECIDE_MODEL", "claude-opus-4-8")


class DecisionNotRecorded(RuntimeError):
    """replay 后端遇未录制决策时抛此（**刻意不继承 FileNotFoundError**）。

    这样 runner 的 `except FileNotFoundError → SKIP` 不会吞它，它落到 `except Exception → ERROR`：
    一个漏录的决策是**响亮的、被计数的失败**，不会被静默当成"环境缺件 SKIP"而掉出打分均值
    （那正是幸存者偏差型撒谎 eval）。见 INTERVIEW-PREP Part 7 / runner._health。
    """

_SYSTEM = (
    "You are a root-cause investigation policy for CAD fillet failures. "
    "Given the structured evidence so far and a decision-table node listing candidate "
    "root-cause stages (each with a discriminator tool), choose the next candidate "
    "discriminator to run, or conclude when further discriminators won't change the root "
    "localization. Candidates are ordered distal->proximate; the most distal fired one "
    "becomes the root (done deterministically downstream — you only choose order / when to stop). "
    'Reply with ONLY a JSON object, no prose, no markdown: '
    '{"action":"run","stage":"<one of the unrun stages>"} or {"action":"conclude"}.'
)


# ---- 纯函数：prompt 构造 + action 解析（可单测，不碰网络）------------------------

def _unrun_candidates(state: dict) -> list[dict]:
    run_stages = {c["stage"] for (c, _st, _ev) in state["verdicts"]}
    return [c for c in state["node"]["root_cause_candidates"] if c["stage"] not in run_stages]


def _build_user_prompt(state: dict) -> str:
    run = state["run_end"]
    payload = {
        "symptom": {"exception": run.exception, "phase": run.phase, "is_done": run.is_done},
        "playbook_node": state["node"]["id"],
        "candidates_unrun": [
            {"stage": c["stage"], "cause": c.get("cause", ""),
             "discriminator": c.get("localize", {}).get("tool")}
            for c in _unrun_candidates(state)
        ],
        "verdicts_so_far": [
            {"stage": c["stage"], "status": st, "evidence": ev}
            for (c, st, ev) in state["verdicts"]
        ],
    }
    return json.dumps(payload, ensure_ascii=False)


def _parse_action(text: str, unrun: list[dict]) -> dict:
    """LLM 文本 → {"run": cand} | {"conclude": True}。

    稳健性：只接受 unrun 里的 stage；选了已跑/未知/conclude 一律收结论（保证回路有界）。
    """
    s = text.strip()
    if s.startswith("```"):                                   # 去掉可能的 markdown 围栏
        s = s.strip("`")
        s = s[s.find("{"):s.rfind("}") + 1] if "{" in s else s
    try:
        obj = json.loads(s[s.find("{"):s.rfind("}") + 1])
    except (ValueError, json.JSONDecodeError):
        return {"conclude": True}                             # 解析不出 → 安全收结论
    if obj.get("action") == "run":
        stage = obj.get("stage")
        for c in unrun:
            if c["stage"] == stage:
                return {"run": c}
    return {"conclude": True}


def _signature(state: dict) -> str:
    """state 的确定性签名（节点 + 已跑候选+裁定）——record/replay 的 key。

    **不变式**：签名必须含决策**实际依赖的每一项、且仅含这些**。今天 LLM 只看
    `_build_user_prompt` 暴露的 {症状(exc/phase/is_done)、节点 id、未跑候选、已跑裁定}——
    radius/tolerance/edges **不进 prompt、决策不依赖它们**，故不进签名。这也正是"同签名跨
    case 复用录制决策、零重录"的**正解、非 bug**：两 case 只差 radius 但决策依赖项相同时，
    它们**本就该**得同一决策。
    ⚠️ 若将来决策空间让候选或决策**依赖** tolerance/edges/radius（如引入 tolerance-level
    候选），必须把它们加进本签名**并重录**决策，否则会别名到错决策。见 INTERVIEW-PREP Part 7。
    """
    run = state["run_end"]
    key = json.dumps({
        "node": state["node"]["id"],
        "exc": run.exception, "phase": run.phase,
        "verdicts": [[c["stage"], st] for (c, st, _ev) in state["verdicts"]],
    }, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


# ---- 后端 -----------------------------------------------------------------------

def _claude_cli(system: str, user: str, *, model: str = _MODEL, timeout_s: int = 120) -> str:
    """shell out 本地 `claude -p`（headless），复用现有 Claude Code 鉴权。返回模型文本。"""
    proc = subprocess.run(
        ["claude", "-p", user, "--model", model, "--system-prompt", system,
         "--output-format", "json", "--allowedTools", ""],
        capture_output=True, text=True, timeout=timeout_s,
    )
    if proc.returncode != 0 or not proc.stdout.strip():
        raise RuntimeError(f"claude -p 失败(rc={proc.returncode}): {(proc.stderr or '')[:200]}")
    env = json.loads(proc.stdout)                             # 信封 {type:result, result:"...", ...}
    return env.get("result", "")


def _replay(signature: str, record_dir: str) -> dict:
    fp = os.path.join(record_dir, f"{signature}.json")
    if not os.path.exists(fp):
        # 未录制 ≠ 环境缺件：抛 DecisionNotRecorded（非 FileNotFoundError）→ runner 归 ERROR 非 SKIP。
        raise DecisionNotRecorded(
            f"无录制决策：{fp}（先用 claude_cli 后端跑一遍录制；replay miss 记 ERROR，不静默 SKIP）")
    with open(fp, encoding="utf-8") as f:
        return json.load(f)["action_raw"]


def _api(system: str, user: str, *, model: str = _MODEL) -> str:  # noqa: ARG001
    """留给他人接 anthropic SDK + ANTHROPIC_API_KEY（见 .claude claude-api 技能）。

    示意（未启用，避免本仓引入 anthropic 依赖 + key）：
        import anthropic
        c = anthropic.Anthropic()
        r = c.messages.create(model=model, max_tokens=256,
                              system=system, messages=[{"role":"user","content":user}],
                              output_config={"effort":"low"})   # 注：opus-4-8 无 temperature
        return next(b.text for b in r.content if b.type == "text")
    """
    raise NotImplementedError("api 后端：接 anthropic SDK + key（留好的配置接口，见 docstring）")


# ---- 决策接缝 -------------------------------------------------------------------

def decide_llm(state: dict) -> dict:
    """与 decide_rule 同签名。后端/录制目录从 env 读，保持接缝签名统一（A/B 对称）。

      AGENT_DECIDE_BACKEND : claude_cli(默认) | replay | api
      AGENT_DECIDE_RECORD  : 录制/回放目录（claude_cli 跑完落盘，replay 读）
    """
    backend = os.environ.get("AGENT_DECIDE_BACKEND", "claude_cli")
    record_dir = os.environ.get("AGENT_DECIDE_RECORD")
    unrun = _unrun_candidates(state)
    if not unrun:                                             # 候选已穷尽 → 收结论（与 rule 一致）
        return {"conclude": True}

    sig = _signature(state)
    if backend == "replay":
        raw = _replay(sig, record_dir or "")
        return _action_from_raw(raw, unrun)

    system, user = _SYSTEM, _build_user_prompt(state)
    text = _api(system, user) if backend == "api" else _claude_cli(system, user)
    action = _parse_action(text, unrun)

    if record_dir:                                            # 录制：签名 → 原始 action（供 replay）
        os.makedirs(record_dir, exist_ok=True)
        raw = {"conclude": True} if "conclude" in action else {"run_stage": action["run"]["stage"]}
        with open(os.path.join(record_dir, f"{sig}.json"), "w", encoding="utf-8") as f:
            json.dump({"action_raw": raw, "llm_text": text}, f, ensure_ascii=False)
    return action


def _action_from_raw(raw: dict, unrun: list[dict]) -> dict:
    """录制的原始 action（{conclude} | {run_stage}）→ {"run": cand} | {"conclude": True}。"""
    if "run_stage" in raw:
        for c in unrun:
            if c["stage"] == raw["run_stage"]:
                return {"run": c}
    return {"conclude": True}
