"""Queue consumer + RPC driver for the slow path (docs/05 §3).

Flow: pop a `TriggerEvent` off the `trigger_events` Redis stream (via a
consumer group, so a crashed worker's in-flight entry gets reclaimed rather
than lost -- pipelines.broker.streams) -> write payload files under
`workspace_root/incidents/{event_id}/` -> one RPC prompt via
`agent.prime_adapter.PrimeAdapter` (trajectory-inspector role) -> Pydantic-
validate the agent's `result.json` as a `KinematicsVerdict` -> Band-3
recomputation gate (`agent.band3`) -> pass: `IncidentRecord` with
`state=confirmed`; fail (bad schema, gate mismatch, timeout, crash):
`IncidentRecord` with `state=needs_review` and a `rejection_reason` --
raw evidence is always kept, never silently dropped (docs/05 §8).

Postgres insert + WS push land with the dashboard (docs/12 M4); for now
`run_forever` logs each `IncidentRecord` and callers of `AgentWorker`
directly (e.g. tests, or a future thin CLI) get it back from `process_one`.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path
from string import Template

import redis
from pipelines.broker.streams import ConsumerGroupReader
from pipelines.schemas import IncidentRecord, IncidentState, KinematicsVerdict, TriggerEvent
from pipelines.vision.pipeline import TRIGGER_STREAM_KEY

from agent.band3 import check as band3_check
from agent.prime_adapter import PrimeAdapter, PrimeAgentError, PrimeAgentTimeout

logger = logging.getLogger(__name__)

GROUP_NAME = "agent-worker"
# docs/05 §6: "visibility timeout 300s > max triage" -- an entry idle longer
# than this was very likely left behind by a crashed consumer, not one still
# working (max single-incident wall clock is PrimeAdapter's own timeout, well
# under this).
STALE_CLAIM_MS = 300_000

PROMPT_DIR = Path(__file__).parent / "prompts"
_TRAJECTORY_TEMPLATE = Template(
    (PROMPT_DIR / "trajectory_inspector.md").read_text(encoding="utf-8")
)
_GENERIC_TEMPLATE = Template(
    (PROMPT_DIR / "generic_classification.md").read_text(encoding="utf-8")
)


def build_prompt(event: TriggerEvent) -> str:
    """Proximity-class triggers (exactly two involved tracks) get the
    pairwise-distance verification prompt validated in spike-01; everything
    else (zone_intrusion, speed) gets the single-track sanity-check prompt --
    there's no pairwise distance for those rule kinds to recompute."""
    if len(event.involved_track_ids) == 2:
        track_a, track_b = event.involved_track_ids
        return _TRAJECTORY_TEMPLATE.substitute(
            event_id=event.event_id, track_a=track_a, track_b=track_b
        )
    solo_track: int | str = event.involved_track_ids[0] if event.involved_track_ids else ""
    return _GENERIC_TEMPLATE.substitute(event_id=event.event_id, track_a=solo_track)


class AgentWorker:
    def __init__(
        self,
        redis_client: redis.Redis,
        workspace_root: Path,
        evidence_root: Path,
        consumer_name: str,
        prompt_timeout_s: float | None = None,
    ) -> None:
        self.reader = ConsumerGroupReader(
            redis_client, TRIGGER_STREAM_KEY, GROUP_NAME, consumer_name
        )
        self.workspace_root = workspace_root
        self.evidence_root = evidence_root
        self.prompt_timeout_s = prompt_timeout_s

    def run_forever(self) -> None:
        while True:
            for entry in self.reader.claim_stale(min_idle_ms=STALE_CLAIM_MS):
                logger.warning(
                    "reclaimed stale entry %s (previous consumer likely crashed)", entry.entry_id
                )
                self._handle(entry.entry_id, entry.payload)
            for entry in self.reader.read(count=1, block_ms=5000):
                self._handle(entry.entry_id, entry.payload)

    def _handle(self, entry_id: str, payload: dict[str, str]) -> None:
        event = TriggerEvent.model_validate_json(payload["payload"])
        try:
            record = self.process_one(event)
            logger.info(
                "incident %s -> %s (%s)", event.event_id, record.state, record.classification
            )
        except Exception:
            logger.exception("incident %s failed before producing any verdict", event.event_id)
            # Not acked: XAUTOCLAIM hands this to the next consumer after
            # STALE_CLAIM_MS. A worker crash mid-incident must not drop the
            # trigger silently.
            return
        self.reader.ack(entry_id)

    def process_one(self, event: TriggerEvent) -> IncidentRecord:
        incident_dir = self.workspace_root / "incidents" / event.event_id
        incident_dir.mkdir(parents=True, exist_ok=True)
        (incident_dir / "event.json").write_text(event.model_dump_json(indent=2), encoding="utf-8")

        tracks_dst = incident_dir / "tracks.jsonl"
        tracks_src = self.evidence_root / event.event_id / "tracks.jsonl"
        if not tracks_src.exists():
            return self._needs_review(event, f"evidence window missing: {tracks_src} not found")
        shutil.copyfile(tracks_src, tracks_dst)

        clip_src = self.evidence_root / event.event_id / "clip.mp4"
        if clip_src.exists():
            shutil.copyfile(clip_src, incident_dir / "clip.mp4")

        prompt = build_prompt(event)

        with PrimeAdapter(cwd=incident_dir) as adapter:
            try:
                if self.prompt_timeout_s is not None:
                    adapter.prompt(prompt, timeout_s=self.prompt_timeout_s)
                else:
                    adapter.prompt(prompt)
            except PrimeAgentTimeout as exc:
                return self._needs_review(event, str(exc))
            except PrimeAgentError as exc:
                return self._needs_review(event, f"prime-agent process error: {exc}")

        result_path = incident_dir / "result.json"
        if not result_path.exists():
            return self._needs_review(
                event, "no result.json written (agent/prompts/root_policy.md §3 violation)"
            )

        try:
            verdict = KinematicsVerdict.model_validate_json(result_path.read_text(encoding="utf-8"))
        except Exception as exc:
            return self._needs_review(event, f"result.json failed schema validation: {exc}")

        gate = band3_check(event, verdict, tracks_dst)
        if not gate.passed:
            return self._needs_review(
                event, "Band-3 recomputation mismatch: " + "; ".join(gate.reasons), verdict=verdict
            )

        return IncidentRecord(
            event_id=event.event_id,
            camera_id=event.camera_id,
            trigger_ts=event.trigger_ts,
            severity=event.severity_hint,
            state=IncidentState.CONFIRMED,
            classification=verdict.classification,
            verified_kinematics=verdict,
            rule_citations=[event.rule_id],
            evidence_refs=[event.track_window_ref] + ([event.clip_ref] if event.clip_ref else []),
        )

    def _needs_review(
        self, event: TriggerEvent, reason: str, verdict: KinematicsVerdict | None = None
    ) -> IncidentRecord:
        # docs/05 §8: never silently dropped -- persisted with state,
        # rejection_reason, and the evidence refs for a human reviewer.
        logger.warning("incident %s -> needs_review: %s", event.event_id, reason)
        return IncidentRecord(
            event_id=event.event_id,
            camera_id=event.camera_id,
            trigger_ts=event.trigger_ts,
            severity=event.severity_hint,
            state=IncidentState.NEEDS_REVIEW,
            classification=verdict.classification if verdict else None,
            verified_kinematics=verdict,
            rejection_reason=reason,
            rule_citations=[event.rule_id],
            evidence_refs=[event.track_window_ref] + ([event.clip_ref] if event.clip_ref else []),
        )


def main() -> None:
    import argparse
    import socket

    logging.basicConfig(level=logging.INFO)
    ap = argparse.ArgumentParser()
    ap.add_argument("--redis-url", default="redis://localhost:6379")
    ap.add_argument("--workspace-root", default="/workspace")
    ap.add_argument("--evidence-root", default="incidents")
    ap.add_argument("--consumer-name", default=socket.gethostname())
    args = ap.parse_args()

    client = redis.Redis.from_url(args.redis_url)
    worker = AgentWorker(
        redis_client=client,
        workspace_root=Path(args.workspace_root),
        evidence_root=Path(args.evidence_root),
        consumer_name=args.consumer_name,
    )
    worker.run_forever()


if __name__ == "__main__":
    main()
