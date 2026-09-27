"""Compact agent transcripts -- agent.transcript (against the real golden session)."""

from __future__ import annotations

import json
from pathlib import Path

from agent.transcript import MAX_OUTPUT_CHARS, compact_transcript

GOLDEN = Path(__file__).parent / "fixtures" / "golden_prime_agent_session.jsonl"


def _golden_events() -> list[dict[str, object]]:
    lines = GOLDEN.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def test_golden_session_reduces_to_ordered_code_and_thoughts() -> None:
    t = compact_transcript(_golden_events())
    assert t["turns"] == 5
    assert t["model"] == "z-ai/glm-5.3-flash"
    tools = [s for s in t["steps"] if s["kind"] == "tool"]
    assert len(tools) == 5
    assert all(s["tool"] == "ipython" and s["code"] for s in tools)
    # the agent's first cell really failed (wrong path) and it recovered
    assert tools[0]["status"] == "error" and "Traceback" in tools[0]["output"]
    assert tools[1]["status"] == "ok"
    assert any("1.4" in (s.get("text") or "") for s in t["steps"] if s["kind"] == "thought")


def test_streaming_deltas_are_ignored_and_outputs_clipped() -> None:
    events = [
        {"type": "turn_start"},
        {"type": "message_update", "message": {"role": "assistant", "content": []}},
        {
            "type": "tool_execution_start",
            "toolCallId": "a",
            "toolName": "ipython",
            "args": {"code": "print('x' * 5000)"},
        },
        {
            "type": "tool_execution_end",
            "toolCallId": "a",
            "result": {
                "content": [{"type": "text", "text": "x" * 5000}],
                "details": {"status": "ok", "durationMs": 3},
            },
        },
        {
            "type": "message_end",
            "message": {
                "role": "assistant",
                "model": "m",
                "content": [{"type": "text", "text": "done"}],
            },
        },
    ]
    t = compact_transcript(events)
    assert [s["kind"] for s in t["steps"]] == ["tool", "thought"]
    assert len(t["steps"][0]["output"]) < MAX_OUTPUT_CHARS + 40
    assert t["steps"][0]["ms"] == 3
