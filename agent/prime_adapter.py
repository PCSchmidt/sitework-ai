"""THE ONLY module that may invoke prime-agent (docs/07 §2, ADR-005).

Pinned version matches `docker/Dockerfile.agent`'s `PRIME_AGENT_VERSION` build
arg; the golden-session contract test (CI workflow contract-agent.yaml, not
yet built) replays against this adapter to guard F1 drift.

Built after the M3.0 spike (docs/spikes/spike-01-prime-agent-headless.md),
which found `--autonomous-max-turns`/`-max-tokens` is not a trustworthy hard
ceiling (Finding 4) -- one run in the spike hung 20+ minutes past completion
with no event from the process at all. `prompt()`'s external timeout is
therefore enforced by a background reader thread + `queue.Queue.get(timeout=)`,
not by iterating `proc.stdout` directly (which blocks indefinitely on a
silent pipe, exactly the failure mode the spike hit) -- the deadline has to
be checkable even when prime-agent emits nothing at all.
"""

from __future__ import annotations

import contextlib
import json
import queue
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Matches docker/Dockerfile.agent's `ARG PRIME_AGENT_VERSION`; bump both
# together, only after a green contract-test run.
PINNED_PRIME_AGENT_VERSION = "0.9.3"

_PRIME_AGENT_EXE = "prime-agent.cmd" if sys.platform == "win32" else "prime-agent"

# docs/05 §4 T1 budget (first line of defense; not the real backstop -- see
# module docstring and PrimeAgentTimeout).
DEFAULT_MAX_TURNS = 8
DEFAULT_MAX_TOKENS = 40_000
# spike-01 Finding 6: p50 ran 82-96s against a 60s target; budgeted 90-120s
# (150s ceiling) until M5's larger eval set said otherwise: 4/30 fixtures hit
# the 150s ceiling on their first attempt (docs/eval-m5-agent-slow-path.md),
# then completed correctly in 48-65s each when re-run with more headroom --
# real run-to-run latency variance, not a capability failure, and not
# anywhere near needing the full 220s the retest allowed. 210s keeps ~2x
# margin over the highest max ever observed (96.0s, M3) while still bounding
# a genuine hang.
DEFAULT_TIMEOUT_S = 210.0


class PrimeAgentTimeout(RuntimeError):
    """The external supervisory deadline fired and the subprocess was killed.

    spike-01 Finding 4: prime-agent's own `--autonomous-max-*` flags did not
    reliably stop a runaway task (observed: 9 turns / 130+s against
    `--autonomous-max-turns 3`). This is the actual backstop.
    """


class PrimeAgentError(RuntimeError):
    """prime-agent exited, or its stdout stream ended, before completing the prompt."""


@dataclass
class PromptResult:
    final_text: str | None
    stats: dict[str, Any] | None
    events: list[dict[str, Any]] = field(default_factory=list)


class PrimeAdapter:
    """RPC JSON-lines driver for one `prime-agent --mode rpc` process.

    One adapter == one long-lived subprocess (docs/05 §6: "one RPC process
    per container, one incident in flight per session"). `prompt()` is not
    re-entrant; call it once at a time per adapter instance.
    """

    def __init__(
        self,
        cwd: str | Path,
        version: str = PINNED_PRIME_AGENT_VERSION,
        model: str | None = None,
        max_turns: int = DEFAULT_MAX_TURNS,
        max_tokens: int = DEFAULT_MAX_TOKENS,
    ) -> None:
        self.cwd = str(cwd)
        self.version = version
        self.model = model
        self.max_turns = max_turns
        self.max_tokens = max_tokens
        self._proc: subprocess.Popen[str] | None = None
        self._out_q: queue.Queue[str | None] = queue.Queue()
        self._reader: threading.Thread | None = None

    def start(self) -> None:
        if self._proc is not None:
            return
        cmd = [
            _PRIME_AGENT_EXE,
            "--mode",
            "rpc",
            "--no-session",
            "--cwd",
            self.cwd,
            "--autonomous",
            "--autonomous-max-turns",
            str(self.max_turns),
            "--autonomous-max-tokens",
            str(self.max_tokens),
        ]
        if self.model:
            cmd += ["--model", self.model]
        self._proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        self._out_q = queue.Queue()
        self._reader = threading.Thread(target=self._pump_stdout, daemon=True)
        self._reader.start()

    def _pump_stdout(self) -> None:
        proc = self._proc
        assert proc is not None and proc.stdout is not None
        for line in proc.stdout:
            self._out_q.put(line)
        self._out_q.put(None)  # EOF sentinel

    def stop(self) -> None:
        proc = self._proc
        if proc is None:
            return
        if proc.stdin:
            with contextlib.suppress(OSError):
                proc.stdin.close()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
        self._proc = None

    def __enter__(self) -> PrimeAdapter:
        self.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self.stop()

    def _send(self, obj: dict[str, Any]) -> None:
        proc = self._proc
        assert proc is not None and proc.stdin is not None
        proc.stdin.write(json.dumps(obj) + "\n")
        proc.stdin.flush()

    def switch_session(self, session_path: str) -> None:
        """spike-01 Finding 5: `switch_session`, not `--resume`, reloads state."""
        self._send({"id": "req-switch", "type": "switch_session", "sessionPath": session_path})

    def prompt(self, message: str, timeout_s: float = DEFAULT_TIMEOUT_S) -> PromptResult:
        """Send one prompt, block for its result, kill the process on timeout.

        The `deadline` here -- not `--autonomous-max-turns`/`-tokens` -- is
        what actually enforces the budget (spike-01 Finding 4).
        """
        if self._proc is None:
            self.start()
        assert self._proc is not None

        self._send({"id": "req-prompt", "type": "prompt", "message": message})

        events: list[dict[str, Any]] = []
        stats: dict[str, Any] | None = None
        final_text: str | None = None
        got_stats = False
        got_text = False
        agent_ended = False
        deadline = time.monotonic() + timeout_s

        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                self._kill()
                raise PrimeAgentTimeout(
                    f"prime-agent did not complete within {timeout_s}s (external supervisory "
                    "timeout -- spike-01 Finding 4: autonomous-max-turns alone is not enough)"
                )
            try:
                line = self._out_q.get(timeout=min(remaining, 1.0))
            except queue.Empty:
                continue

            if line is None:
                raise PrimeAgentError(
                    "prime-agent's stdout closed before the prompt completed "
                    f"(exit code {self._proc.poll()})"
                )
            line = line.strip()
            if not line:
                continue
            try:
                evt = json.loads(line)
            except json.JSONDecodeError:
                continue
            events.append(evt)
            etype = evt.get("type")

            if etype == "agent_end" and not agent_ended:
                agent_ended = True
                self._send({"id": "req-stats", "type": "get_session_stats"})
                self._send({"id": "req-text", "type": "get_last_assistant_text"})
            if etype == "response" and evt.get("command") == "get_session_stats":
                stats = evt.get("data")
                got_stats = True
            if etype == "response" and evt.get("command") == "get_last_assistant_text":
                final_text = evt.get("data", {}).get("text")
                got_text = True
            if agent_ended and got_stats and got_text:
                break

        return PromptResult(final_text=final_text, stats=stats, events=events)

    def _kill(self) -> None:
        proc = self._proc
        if proc is None:
            return
        with contextlib.suppress(Exception):
            self._send({"type": "abort"})
        proc.kill()
        with contextlib.suppress(subprocess.TimeoutExpired):
            proc.wait(timeout=5)
        self._proc = None

    def healthcheck(self) -> bool:
        """True if `prime-agent --version` runs. Does not start an RPC session."""
        try:
            result = subprocess.run(
                [_PRIME_AGENT_EXE, "--version"], capture_output=True, text=True, timeout=10
            )
        except (OSError, subprocess.TimeoutExpired):
            return False
        return result.returncode == 0
