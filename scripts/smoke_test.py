"""Demo smoke test (docs/09 §6). M0 stub; wired end-to-end in M3/M4.

Final form: inject synthetic TriggerEvent into the broker -> assert incident row
created -> assert WS message observed -> print PASS. Runs in CI with the agent
stubbed, and locally against the real stack.
"""

from __future__ import annotations


def main() -> None:
    raise SystemExit("smoke test is wired in M3/M4 (see docs/09-testing-and-evaluation.md §6)")


if __name__ == "__main__":
    main()
