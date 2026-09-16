"""Benchmark harness (docs/04 section 5). v1 lands in M1; drives spike-00.

Planned output axes: model (YOLO11n/11s) x precision (FP16/INT8) x streams (1-3),
metrics FPS/stream, latency p50/p95, VRAM peak. Hardware recorded in
docs/spikes/spike-00-gpu-benchmark.md; published to docs/benchmarks.md at M5.
"""

from __future__ import annotations


def main() -> None:
    raise SystemExit("benchmark harness lands in M1 (spike-00 runs on v1)")


if __name__ == "__main__":
    main()
