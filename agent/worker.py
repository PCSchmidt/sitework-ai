"""Queue consumer + RPC driver for the slow path (docs/05 §3). Implemented in M3.

Flow: pop TriggerEvent -> write payload files -> RPC prompt via prime_adapter ->
Pydantic validate + Band-3 recomputation gate -> Postgres insert + WS push.
"""

from __future__ import annotations


def main() -> None:
    raise SystemExit("agent worker lands in M3 (see docs/12-roadmap.md)")


if __name__ == "__main__":
    main()
