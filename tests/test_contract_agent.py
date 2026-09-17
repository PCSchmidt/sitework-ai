"""Golden RPC session contract test (docs/07 §3, ADR-005 / feasibility doc F1).

Replays a real, previously-captured `prime-agent` transcript
(tests/fixtures/golden_prime_agent_session.jsonl, captured by
scripts/record_golden_session.py against PINNED_PRIME_AGENT_VERSION) through
a stand-in process that emits those exact captured lines back
(tests/_fake_prime_agent.py's "golden_replay" mode) rather than a freshly
synthesized response. This exercises PrimeAdapter's parsing (agent_end
detection, stats/text extraction) against a real output shape without
needing the real CLI installed in CI -- still blocked on the private-registry
gap (spike-01 Finding 1, docs/spikes/spike-01-prime-agent-headless.md).

This is NOT a substitute for re-running spike-01 against a new prime-agent
version: it only catches regressions in this repo's own adapter code, not
protocol drift on prime-agent's side. Re-record the fixture (rerun
scripts/record_golden_session.py) whenever PINNED_PRIME_AGENT_VERSION bumps.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from agent.prime_adapter import PrimeAdapter

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "golden_prime_agent_session.jsonl"
GOLDEN_RESULT_PATH = Path(__file__).parent / "fixtures" / "golden_prime_agent_result.json"

pytestmark = pytest.mark.skipif(
    not FIXTURE_PATH.exists(),
    reason="golden session not captured yet -- run scripts/record_golden_session.py",
)


def test_replays_real_captured_transcript(
    tmp_path: Path, fake_prime_agent_on_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FAKE_PRIME_AGENT_MODE", "golden_replay")
    monkeypatch.setenv("GOLDEN_SESSION_FIXTURE", str(FIXTURE_PATH))

    with PrimeAdapter(cwd=tmp_path) as adapter:
        result = adapter.prompt("(golden replay -- prompt content unused)", timeout_s=15)

    golden_events = [
        json.loads(line) for line in FIXTURE_PATH.read_text(encoding="utf-8").splitlines() if line
    ]
    golden_final_text = next(
        (
            e["data"]["text"]
            for e in golden_events
            if e.get("type") == "response" and e.get("command") == "get_last_assistant_text"
        ),
        None,
    )
    golden_stats = next(
        (
            e["data"]
            for e in golden_events
            if e.get("type") == "response" and e.get("command") == "get_session_stats"
        ),
        None,
    )

    assert result.final_text == golden_final_text
    assert result.stats == golden_stats
    assert any(e.get("type") == "agent_end" for e in result.events)


def test_golden_result_json_is_schema_valid() -> None:
    """The real result.json this session produced must still satisfy
    KinematicsVerdict -- a schema change here is exactly the drift this
    contract test exists to catch."""
    if not GOLDEN_RESULT_PATH.exists():
        pytest.skip("golden result.json not captured yet")
    from pipelines.schemas import KinematicsVerdict

    verdict = KinematicsVerdict.model_validate_json(
        GOLDEN_RESULT_PATH.read_text(encoding="utf-8")
    )
    assert verdict.classification is not None
