"""Stand-in `prime-agent --mode rpc` process for tests (tests/test_prime_adapter.py,
tests/test_worker.py).

Speaks the same JSON-lines RPC subset PrimeAdapter drives (prompt -> agent_end ->
get_session_stats/get_last_assistant_text). Behavior is selected via the
FAKE_PRIME_AGENT_MODE env var:

- "success": emits agent_start/agent_end immediately, answers stats/text.
- "hang": emits agent_start, then blocks forever -- exercises PrimeAdapter's
  external timeout against exactly the failure mode spike-01 hit (a process
  that goes silent mid-run, not one that errors out).
- "run_incident": reads event.json/tracks.jsonl from --cwd and writes a real
  recomputed result.json, the way a working trajectory-inspector run would --
  for testing agent/worker.py's plumbing, not the LLM's reasoning (spike-01
  already validated that against the real CLI).
- "wrong_answer": writes a result.json with a deliberately wrong distance, to
  exercise the Band-3 gate's rejection path.
"""

from __future__ import annotations

import json
import os
import sys
import time


def _emit(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def _recompute_result(cwd: str) -> dict:
    with open(os.path.join(cwd, "event.json"), encoding="utf-8") as fh:
        event = json.load(fh)
    tracks = []
    with open(os.path.join(cwd, "tracks.jsonl"), encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                tracks.append(json.loads(line))

    ids = event["involved_track_ids"]
    best = None
    closing = None
    samples = []
    if len(ids) == 2:
        for frame in sorted(tracks, key=lambda f: f["frame_ts"]):
            by_id = {t["track_id"]: t for t in frame["tracks"]}
            a, b = by_id.get(ids[0]), by_id.get(ids[1])
            if not a or not b or not a.get("ground_point_m") or not b.get("ground_point_m"):
                continue
            dx = a["ground_point_m"][0] - b["ground_point_m"][0]
            dy = a["ground_point_m"][1] - b["ground_point_m"][1]
            dist = (dx * dx + dy * dy) ** 0.5
            samples.append((frame["frame_ts"], dist))
        if samples:
            min_idx = min(range(len(samples)), key=lambda i: samples[i][1])
            min_ts, best = samples[min_idx]
            if min_idx > 0:
                prev_ts, prev_dist = samples[min_idx - 1]
                dt = min_ts - prev_ts
                if dt > 0:
                    closing = (prev_dist - best) / dt

    classification = "normal_ops"
    if best is not None and best < 2.0:
        classification = "near_miss"
    if best is not None and best < 1.0:
        classification = "violation"

    return {
        "verified_min_distance_m": best,
        "closing_velocity_mps": closing,
        "ttc_s": None,
        "classification": classification,
        "recompute_inputs": {
            "track_a": str(ids[0]) if ids else "",
            "track_b": str(ids[1]) if len(ids) > 1 else "",
            "frames_used": str(len(tracks)),
        },
    }


def main() -> None:
    argv = sys.argv[1:]
    if "--version" in argv:
        print("fake-prime-agent 0.0.0-test")
        return

    mode = os.environ.get("FAKE_PRIME_AGENT_MODE", "success")
    cwd = argv[argv.index("--cwd") + 1] if "--cwd" in argv else os.getcwd()

    line = sys.stdin.readline()
    json.loads(line)  # the prompt request; contents unused by the fake

    _emit({"type": "agent_start"})

    if mode == "hang":
        while True:
            time.sleep(1)

    if mode == "run_incident":
        result = _recompute_result(cwd)
        with open(os.path.join(cwd, "result.json"), "w", encoding="utf-8") as fh:
            json.dump(result, fh)
    elif mode == "wrong_answer":
        result = {
            "verified_min_distance_m": 999.0,
            "closing_velocity_mps": None,
            "ttc_s": None,
            "classification": "normal_ops",
            "recompute_inputs": {"track_a": "", "track_b": "", "frames_used": "0"},
        }
        with open(os.path.join(cwd, "result.json"), "w", encoding="utf-8") as fh:
            json.dump(result, fh)
    elif mode == "no_result":
        pass

    _emit({"type": "agent_end"})

    while True:
        line = sys.stdin.readline()
        if not line:
            break
        req = json.loads(line)
        if req.get("type") == "get_session_stats":
            _emit(
                {
                    "type": "response",
                    "command": "get_session_stats",
                    "data": {"tokens": {"total": 100}},
                }
            )
        elif req.get("type") == "get_last_assistant_text":
            _emit(
                {
                    "type": "response",
                    "command": "get_last_assistant_text",
                    "data": {"text": "done"},
                }
            )
        elif req.get("type") == "abort":
            break


if __name__ == "__main__":
    main()
