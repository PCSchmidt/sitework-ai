"""LiteLLM agent-loop fallback behind the same queue->schema contracts (ADR-005).

Selected only if the M3.0 spike fails its pass criteria; the architecture's value
proposition (triggered reasoning + Band-3 gate) is unchanged either way.
"""

from __future__ import annotations


def main() -> None:
    raise SystemExit("fallback worker exists only if spike-01 (M3.0) fails")


if __name__ == "__main__":
    main()
