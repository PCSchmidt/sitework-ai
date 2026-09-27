"""Compact, human-readable transcript of one prime-agent session.

`PrimeAdapter.prompt()` returns the full RPC event stream (hundreds of
streaming `message_update` deltas). For audit and for the dashboard's
"slow plane" replay, only three things matter, in order: what the agent said
(assistant text), what code it ran in its REPL, and what that code returned.
`compact_transcript` keeps exactly those; `AgentWorker` writes the result to
`incidents/{event_id}/agent_transcript.json` next to the evidence.
"""

from __future__ import annotations

from typing import Any

MAX_CODE_CHARS = 4000
MAX_OUTPUT_CHARS = 1500


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit] + f"\n... [{len(text) - limit} chars cut]"


def compact_transcript(events: list[dict[str, Any]]) -> dict[str, Any]:
    """Reduce an RPC event stream to ordered `thought` / `tool` steps.

    `tool` steps carry the tool name, the code (for `ipython`) or arguments,
    the text result, status, and duration. Streaming deltas are ignored: the
    final `message_end` / `tool_execution_end` events hold the full content.
    """
    steps: list[dict[str, Any]] = []
    pending: dict[str, dict[str, Any]] = {}
    turns = 0
    model: str | None = None

    for evt in events:
        etype = evt.get("type")
        if etype == "turn_start":
            turns += 1
        elif etype == "message_end":
            message = evt.get("message") or {}
            if message.get("role") != "assistant":
                continue
            model = message.get("model") or model
            for block in message.get("content") or []:
                if block.get("type") == "text" and str(block.get("text", "")).strip():
                    steps.append({"kind": "thought", "text": _clip(block["text"].strip(), 2000)})
        elif etype == "tool_execution_start":
            args = evt.get("args") or {}
            code = args.get("code") if isinstance(args.get("code"), str) else None
            step: dict[str, Any] = {
                "kind": "tool",
                "tool": evt.get("toolName"),
                "code": _clip(code, MAX_CODE_CHARS) if code is not None else None,
                "args": None if code is not None else args,
                "output": None,
                "status": None,
                "ms": None,
            }
            steps.append(step)
            pending[str(evt.get("toolCallId"))] = step
        elif etype == "tool_execution_end":
            open_step = pending.pop(str(evt.get("toolCallId")), None)
            if open_step is None:
                continue
            result = evt.get("result") or {}
            texts = [
                str(c.get("text", ""))
                for c in result.get("content") or []
                if c.get("type") == "text"
            ]
            details = result.get("details") or {}
            open_step["output"] = _clip("\n".join(texts).rstrip(), MAX_OUTPUT_CHARS)
            open_step["status"] = details.get("status")
            open_step["ms"] = details.get("durationMs")

    return {"turns": turns, "model": model, "steps": steps}
