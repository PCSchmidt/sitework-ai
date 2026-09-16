"""THE ONLY module that may invoke prime-agent (docs/07 §2, ADR-005).

Pinned version lives in docker/Dockerfile.agent; the golden-session contract test
(CI workflow contract-agent.yaml) replays against this adapter to guard F1 drift.
Implemented in M3 after the M3.0 spike.
"""

from __future__ import annotations

PINNED_PRIME_AGENT_VERSION = "0.9.5"  # bump only with a contract-test green run


class PrimeAdapter:
    """RPC JSON-lines driver for `prime-agent --mode rpc` (M3)."""

    def __init__(self, version: str = PINNED_PRIME_AGENT_VERSION) -> None:
        self.version = version

    def healthcheck(self) -> bool:
        raise NotImplementedError("M3")
