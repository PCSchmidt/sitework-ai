"""One-off capture of a real `prime-agent` RPC session, for the golden-session
contract replay test (tests/test_contract_agent.py, docs/07 §3, ADR-005 F1).

`prime-agent` isn't installable in CI yet (private npm registry -- see
docker/vendor/README.md and spike-01 Finding 1), so the contract test can't
drive the real CLI there. Instead, this script -- run manually, on a machine
that has the pinned version installed -- captures one real RPC transcript and
writes it to tests/fixtures/golden_prime_agent_session.jsonl. CI replays that
captured transcript byte-for-byte (tests/_fake_prime_agent.py's
"golden_replay" mode) to catch PrimeAdapter-side parsing regressions. This is
NOT a substitute for re-running the real spike against a new prime-agent
version -- it only guards this repo's own parsing code, not protocol drift on
prime-agent's side. Re-run this script (and re-verify against the real CLI)
whenever `PINNED_PRIME_AGENT_VERSION` changes.

Usage: uv run python -m scripts.record_golden_session
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from agent.prime_adapter import DEFAULT_TIMEOUT_S, PrimeAdapter
from agent.worker import build_prompt
from pipelines.schemas import TriggerEvent

REPO_ROOT = Path(__file__).parent.parent
FIXTURE_EVENT_DIR = REPO_ROOT / "evaluation" / "fixtures" / "incidents" / "evt_seed_near_miss_01"
OUT_DIR = REPO_ROOT / "tests" / "fixtures"


def main() -> None:
    event = TriggerEvent.model_validate_json(
        (FIXTURE_EVENT_DIR / "event.json").read_text(encoding="utf-8")
    )

    work_dir = REPO_ROOT / "golden_session_tmp" / event.event_id
    work_dir.mkdir(parents=True, exist_ok=True)
    (work_dir / "event.json").write_text(event.model_dump_json(indent=2), encoding="utf-8")
    shutil.copyfile(FIXTURE_EVENT_DIR / "tracks.jsonl", work_dir / "tracks.jsonl")

    prompt = build_prompt(event)
    with PrimeAdapter(cwd=work_dir) as adapter:
        result = adapter.prompt(prompt, timeout_s=DEFAULT_TIMEOUT_S)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    events_path = OUT_DIR / "golden_prime_agent_session.jsonl"
    with events_path.open("w", encoding="utf-8") as fh:
        for evt in result.events:
            fh.write(json.dumps(evt) + "\n")

    result_path = work_dir / "result.json"
    if result_path.exists():
        shutil.copyfile(result_path, OUT_DIR / "golden_prime_agent_result.json")

    print(f"captured {len(result.events)} events -> {events_path}")
    print(f"final_text: {result.final_text}")
    print(f"stats: {result.stats}")
    shutil.rmtree(REPO_ROOT / "golden_session_tmp", ignore_errors=True)


if __name__ == "__main__":
    main()
