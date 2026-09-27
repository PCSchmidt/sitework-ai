"""Run the real slow plane over the showcase recorder's incidents (M7 showcase).

`pipelines.vision.record --evidence-dir DIR` leaves one folder per TriggerEvent
(event.json, tracks.jsonl, clip.mp4) -- the same evidence the live pipeline
writes. This script drives each one through `agent.worker.AgentWorker.process_one`
against a real `prime-agent` process (real LLM inference, same path as
`evaluation/agent_eval.py`), which includes the deterministic Band-3 gate, and
writes the resulting IncidentRecords for the static dashboard:

    {out}/incidents.json   list of IncidentRecord JSON, newest first
    {out}/evidence/{event_id}/tracks.jsonl

Nothing here is simulated: a timeout or gate rejection is saved as the
`needs_review` record it really produced. Existing records are kept unless
`--rerun` is passed, so re-running doesn't spend inference on finished incidents.

Usage:
    uv run python -m scripts.showcase_agent \\
        --evidence-dir build/showcase-evidence --out ui/public/showcase
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path

import fakeredis
from agent.worker import AgentWorker
from pipelines.schemas import TriggerEvent


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--evidence-dir", type=Path, required=True)
    ap.add_argument("--out", type=Path, default=Path("ui/public/showcase"))
    ap.add_argument("--rerun", action="store_true", help="re-run incidents already in the output")
    args = ap.parse_args()

    out_path = args.out / "incidents.json"
    existing: dict[str, dict[str, object]] = {}
    if out_path.exists() and not args.rerun:
        existing = {r["event_id"]: r for r in json.loads(out_path.read_text(encoding="utf-8"))}

    with tempfile.TemporaryDirectory(prefix="showcase-agent-") as workspace:
        worker = AgentWorker(
            redis_client=fakeredis.FakeRedis(),
            workspace_root=Path(workspace),
            evidence_root=args.evidence_dir,
            consumer_name="showcase-runner",
        )
        for event_dir in sorted(p for p in args.evidence_dir.iterdir() if p.is_dir()):
            event = TriggerEvent.model_validate_json(
                (event_dir / "event.json").read_text(encoding="utf-8")
            )
            if event.event_id in existing:
                print(f"{event.event_id}: kept existing record", file=sys.stderr)
                continue
            print(f"{event.event_id} ({event.camera_id}, {event.rule_id}) ...", file=sys.stderr)
            record = worker.process_one(event)
            print(f"  -> {record.state} / {record.classification}", file=sys.stderr)
            existing[event.event_id] = json.loads(record.model_dump_json())

            dst = args.out / "evidence" / event.event_id
            dst.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(event_dir / "tracks.jsonl", dst / "tracks.jsonl")

    records = sorted(existing.values(), key=lambda r: float(r["trigger_ts"]), reverse=True)
    args.out.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(records, indent=1), encoding="utf-8")
    print(f"{len(records)} incident records -> {out_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
