"""M0.5 exit gate: cross-doc consistency checks.

Greps the doc suite for the values that must be single-sourced. Green here means the
M0.5 doc-revision pass held. Fails loudly with the offending file/line.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = [ROOT / "PLAN.md", *sorted((ROOT / "docs").rglob("*.md"))]

FAILURES: list[str] = []


def check(description: str, ok: bool) -> None:
    print(f"{'PASS' if ok else 'FAIL'}  {description}")
    if not ok:
        FAILURES.append(description)


def grep(pattern: str) -> list[tuple[Path, int, str]]:
    hits = []
    rx = re.compile(pattern)
    for doc in DOCS:
        for i, line in enumerate(doc.read_text(encoding="utf-8").splitlines(), 1):
            if rx.search(line):
                hits.append((doc, i, line.strip()))
    return hits


def main() -> int:
    # 1. Band-3 tolerance: old value must be gone, new value normative in docs/06.
    check(
        "stale Band-3 tolerance '0.1 m / 0.1 s' removed everywhere",
        not grep(r"0\.1 m / 0\.1 s"),
    )
    check(
        "normative Band-3 tolerance present in docs/06",
        any(h[0].name == "06-schemas-and-api.md" for h in grep(r"0\.15 m")),
    )

    # 2. Vision baseline: pre-spike-00 the rule was "11n until probe"; spike-00 resolved
    # it (11s is free at 1080p). Guard now: the resolution must be recorded, and nothing
    # may claim 11n is the default anymore.
    check(
        "spike-00 resolution recorded (11s default justified by probe)",
        any(
            h[0].name == "spike-00-gpu-benchmark.md" and "Default detector is YOLO11s" in h[2]
            for h in grep(r"Default detector is YOLO11s")
        ),
    )
    check(
        "no doc still claims YOLO11n as the default",
        not grep(r"YOLO11n.{0,30}default"),
    )

    # 3. Calibration hard gate consistent.
    rms_docs = {h[0].name for h in grep(r"rms_px ≤ 2\.0")}
    check(
        "hard RMS gate (2.0 px) stated in docs/04 and docs/06",
        rms_docs >= {"04-data-and-models.md", "06-schemas-and-api.md"},
    )

    # 4. M3 scope: watchdog + parameter reviewer marked optional M5+ in docs/05.
    check(
        "watchdog/parameter-reviewer scoped M5+ in docs/05",
        len([h for h in grep(r"optional, M5\+") if h[0].name == "05-agent-orchestration.md"]) == 2,
    )

    # 5. Spikes exist and are referenced.
    for spike in ("spike-00-gpu-benchmark.md", "spike-01", "spike-02-forklift-class.md"):
        check(f"roadmap references {spike}", bool(grep(re.escape(spike))))

    # 6. Cost model Scenario B has a total row.
    check(
        "Scenario B total row present in docs/10",
        any(h[0].name == "10-cost-model.md" for h in grep(r"Scenario B total")),
    )

    if FAILURES:
        print(f"\n{len(FAILURES)} consistency check(s) failed:")
        for f in FAILURES:
            print(f"  - {f}")
        return 1
    print("\nAll consistency checks green.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
