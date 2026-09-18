"""Runs the seeded incident eval set (10 at M3, 30 at M5) against the real
`agent.worker.AgentWorker` pipeline (docs/09 §3).

Each fixture in `evaluation/fixtures/incidents/{event_id}/` is a real
TriggerEvent + tracks.jsonl + hand-labeled `expected.json`
(evaluation/build_seed_incidents.py generates them). This script drives each
one through `AgentWorker.process_one()` against a real `prime-agent` process
(not a stand-in -- unlike tests/test_worker.py, which validates the worker's
own plumbing against a scripted fake, this measures the actual metric the
roadmap's exit criterion cares about) and reports:

- Validation pass rate: fraction reaching `state=confirmed` (schema + Band-3
  gate passed first try). Target >= 90% (docs/09 §3).
- Classification agreement: fraction whose final `classification` matches
  `expected.json`'s label, among fixtures with `check_classification: true`
  (docs/09 §3 target >= 80%; some fixtures test gate rejection, not
  classification, and are excluded from this metric by design).

Requires a working `prime-agent` on PATH -- this is real inference, not a
mock; run count is small (10) but each incident is a genuine RPC round trip
and will take a few minutes total.
"""

from __future__ import annotations

import argparse
import json
import shutil
import statistics
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import fakeredis
from agent.prime_adapter import DEFAULT_TIMEOUT_S
from agent.worker import AgentWorker
from pipelines.schemas import TriggerEvent

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "incidents"


@dataclass
class EvalOutcome:
    event_id: str
    expected_state: str
    actual_state: str
    expected_classification: str | None
    actual_classification: str | None
    check_classification: bool
    rejection_reason: str | None
    wall_s: float
    tokens_in: int | None
    tokens_out: int | None


def run(fixtures_dir: Path, workspace_root: Path, prompt_timeout_s: float) -> list[EvalOutcome]:
    client = fakeredis.FakeRedis()
    worker = AgentWorker(
        redis_client=client,
        workspace_root=workspace_root,
        evidence_root=fixtures_dir,
        consumer_name="eval-runner",
        prompt_timeout_s=prompt_timeout_s,
    )

    outcomes: list[EvalOutcome] = []
    for event_dir in sorted(fixtures_dir.iterdir()):
        if not event_dir.is_dir():
            continue
        event_text = (event_dir / "event.json").read_text(encoding="utf-8")
        event = TriggerEvent.model_validate_json(event_text)
        expected = json.loads((event_dir / "expected.json").read_text(encoding="utf-8"))

        print(f"running {event.event_id} ...", file=sys.stderr)
        start = time.monotonic()
        record = worker.process_one(event)
        wall_s = time.monotonic() - start
        print(f"  -> {record.state} / {record.classification} ({wall_s:.1f}s)", file=sys.stderr)

        outcomes.append(
            EvalOutcome(
                event_id=event.event_id,
                expected_state=expected["expected_state"],
                actual_state=str(record.state),
                expected_classification=expected["expected_classification"],
                actual_classification=str(record.classification) if record.classification else None,
                check_classification=expected["check_classification"],
                rejection_reason=record.rejection_reason,
                wall_s=wall_s,
                tokens_in=record.agent_run.tokens_in if record.agent_run else None,
                tokens_out=record.agent_run.tokens_out if record.agent_run else None,
            )
        )
    return outcomes


def summarize(outcomes: list[EvalOutcome]) -> dict[str, object]:
    n = len(outcomes)
    validation_pass = sum(1 for o in outcomes if o.actual_state == o.expected_state)
    classification_checked = [o for o in outcomes if o.check_classification]
    classification_agree = sum(
        1 for o in classification_checked if o.actual_classification == o.expected_classification
    )
    wall_times = sorted(o.wall_s for o in outcomes)
    # None for timed-out/crashed runs (no agent_run stats produced) -- excluded
    # rather than treated as 0, which would understate the real per-incident cost.
    tokens_total = [
        o.tokens_in + o.tokens_out
        for o in outcomes
        if o.tokens_in is not None and o.tokens_out is not None
    ]

    return {
        "n": n,
        "validation_pass_rate": validation_pass / n if n else 0.0,
        "validation_pass": validation_pass,
        "classification_agreement_rate": (
            classification_agree / len(classification_checked) if classification_checked else None
        ),
        "classification_agree": classification_agree,
        "classification_checked": len(classification_checked),
        "p50_wall_s": wall_times[len(wall_times) // 2] if wall_times else None,
        "max_wall_s": max(wall_times) if wall_times else None,
        "mean_tokens_per_incident": round(statistics.mean(tokens_total)) if tokens_total else None,
        "p95_tokens_per_incident": (
            round(sorted(tokens_total)[min(len(tokens_total) - 1, int(len(tokens_total) * 0.95))])
            if tokens_total
            else None
        ),
        "tokens_measured_n": len(tokens_total),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fixtures-dir", default=str(FIXTURES_DIR))
    ap.add_argument("--workspace-root", default=None)
    ap.add_argument("--prompt-timeout-s", type=float, default=DEFAULT_TIMEOUT_S)
    ap.add_argument("--report-json", default=None)
    args = ap.parse_args()

    default_workspace = Path("eval_workspace_tmp")
    workspace_root = Path(args.workspace_root) if args.workspace_root else default_workspace
    workspace_root.mkdir(parents=True, exist_ok=True)

    outcomes = run(Path(args.fixtures_dir), workspace_root, args.prompt_timeout_s)
    summary = summarize(outcomes)

    print()
    header = (
        f"{'event_id':<32} {'expected':<12} {'actual':<12} "
        f"{'exp_cls':<16} {'act_cls':<16} wall_s"
    )
    print(header)
    for o in outcomes:
        print(
            f"{o.event_id:<32} {o.expected_state:<12} {o.actual_state:<12} "
            f"{o.expected_classification!s:<16} {o.actual_classification!s:<16} {o.wall_s:.1f}"
        )
    print()
    print(json.dumps(summary, indent=2))

    if args.report_json:
        Path(args.report_json).write_text(
            json.dumps(
                {"summary": summary, "outcomes": [o.__dict__ for o in outcomes]}, indent=2
            ),
            encoding="utf-8",
        )

    if not args.workspace_root:
        shutil.rmtree(workspace_root, ignore_errors=True)

    pass_rate = float(summary["validation_pass_rate"])  # type: ignore[arg-type]
    pass_target_met = pass_rate >= 0.90
    print(
        f"\nvalidation pass rate {'PASS' if pass_target_met else 'FAIL'} "
        f"(target >= 90%, got {pass_rate:.0%})"
    )


if __name__ == "__main__":
    main()
