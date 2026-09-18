"""M3.0 spike driver: golden-incident RPC round trip against real prime-agent."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cwd", required=True)
    ap.add_argument("--prompt-file", required=True)
    ap.add_argument("--max-turns", type=int, default=6)
    ap.add_argument("--max-tokens", type=int, default=40000)
    ap.add_argument("--timeout-s", type=float, default=180.0)
    ap.add_argument("--model", default=None)
    args = ap.parse_args()

    with open(args.prompt_file, encoding="utf-8") as f:
        prompt = f.read()

    prime_agent_exe = "prime-agent.cmd" if sys.platform == "win32" else "prime-agent"
    cmd = [
        prime_agent_exe,
        "--mode",
        "rpc",
        "--no-session",
        "--cwd",
        args.cwd,
        "--autonomous",
        "--autonomous-max-turns",
        str(args.max_turns),
        "--autonomous-max-tokens",
        str(args.max_tokens),
        "--autonomous-timeout-ms",
        str(int(args.timeout_s * 1000)),
    ]
    if args.model:
        cmd += ["--model", args.model]

    print(f"launching: {' '.join(cmd)}", file=sys.stderr)
    start = time.time()
    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )

    def send(obj: dict) -> None:
        assert proc.stdin is not None
        proc.stdin.write(json.dumps(obj) + "\n")
        proc.stdin.flush()

    send({"id": "req-1", "type": "prompt", "message": prompt})

    events = []
    final_text = None
    stats = None
    stats_requested = False
    agent_end_at = None
    got_stats = False
    got_text = False
    deadline = start + args.timeout_s + 30
    assert proc.stdout is not None
    for line in proc.stdout:
        line = line.strip()
        if not line:
            continue
        try:
            evt = json.loads(line)
        except json.JSONDecodeError:
            print(f"non-json line: {line[:200]}", file=sys.stderr)
            continue
        events.append(evt)
        etype = evt.get("type")
        print(f"[{time.time() - start:6.1f}s] event: {etype}", file=sys.stderr)

        if etype == "agent_end" and agent_end_at is None:
            agent_end_at = time.time() - start
            send({"id": "req-stats", "type": "get_session_stats"})
            send({"id": "req-text", "type": "get_last_assistant_text"})
            stats_requested = True

        if etype == "response" and evt.get("command") == "get_session_stats":
            stats = evt.get("data")
            got_stats = True
        if etype == "response" and evt.get("command") == "get_last_assistant_text":
            final_text = evt.get("data", {}).get("text")
            got_text = True

        if stats_requested and got_stats and got_text:
            break
        if time.time() > deadline:
            print("driver-side timeout, aborting", file=sys.stderr)
            send({"type": "abort"})
            break

    if proc.stdin:
        proc.stdin.close()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()

    elapsed = time.time() - start
    print(f"agent_end at: {agent_end_at}s (this is the real triage latency)", file=sys.stderr)
    print(f"\n=== DONE in {elapsed:.1f}s ===", file=sys.stderr)

    with open("spike_events.jsonl", "w", encoding="utf-8") as f:
        for evt in events:
            f.write(json.dumps(evt) + "\n")

    print(
        json.dumps(
            {
                "triage_latency_s": agent_end_at,
                "elapsed_s": elapsed,
                "stats": stats,
                "final_text": final_text,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
