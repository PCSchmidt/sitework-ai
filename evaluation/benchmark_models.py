"""Benchmark harness v1 (docs/04 section 5; drives spike-00).

Measures decode+detect throughput for a model on a clip and appends one
JSON row per run to the output file. spike-00 runs this on the target GPU
with YOLO11n/11s and records the results in
docs/spikes/spike-00-gpu-benchmark.md.

Usage:
    uv run python evaluation/benchmark_models.py \
        --clip assets/clips/worker_walking_aisle.mp4 \
        --model yolo11n.pt --device cuda:0 \
        --out docs/spikes/spike-00-results.jsonl
"""

from __future__ import annotations

import argparse
import json
import statistics
import time
from pathlib import Path

import av


def run_benchmark(
    clip: Path,
    weights: str,
    device: str,
    max_frames: int,
    imgsz: int,
) -> dict[str, object]:
    from ultralytics import YOLO  # deferred: heavy import

    model = YOLO(weights)
    model.predict(str(clip), device=device, imgsz=imgsz, verbose=False, stream=True)  # warm-up

    latencies_ms: list[float] = []
    started = time.perf_counter()
    n = 0
    container = av.open(str(clip))
    try:
        for packet in container.demux(video=0):
            for frame in packet.decode():
                img = frame.to_ndarray(format="bgr24")
                t0 = time.perf_counter()
                model.predict(img, device=device, imgsz=imgsz, verbose=False)
                latencies_ms.append((time.perf_counter() - t0) * 1000)
                n += 1
                if n >= max_frames:
                    break
            if n >= max_frames:
                break
    finally:
        container.close()

    wall_s = time.perf_counter() - started
    row: dict[str, object] = {
        "clip": str(clip),
        "model": weights,
        "device": device,
        "imgsz": imgsz,
        "frames": n,
        "wall_s": round(wall_s, 2),
        "fps": round(n / wall_s, 1) if wall_s > 0 else None,
        "latency_ms_p50": round(statistics.median(latencies_ms), 1) if latencies_ms else None,
        "latency_ms_p95": round(_p95(latencies_ms), 1) if latencies_ms else None,
    }
    if device.startswith("cuda"):
        try:
            import torch

            row["vram_peak_mb"] = round(torch.cuda.max_memory_allocated() / 2**20)
            row["gpu"] = torch.cuda.get_device_name(0)
        except Exception:
            pass
    return row


def _p95(values: list[float]) -> float:
    values = sorted(values)
    return values[min(len(values) - 1, int(len(values) * 0.95))]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--clip", type=Path, default=Path("assets/clips/worker_walking_aisle.mp4"))
    ap.add_argument("--model", default="yolo11n.pt")
    ap.add_argument("--device", default="cpu")
    ap.add_argument("--imgsz", type=int, default=640)
    ap.add_argument("--max-frames", type=int, default=300)
    ap.add_argument("--out", type=Path, default=Path("docs/spikes/spike-00-results.jsonl"))
    args = ap.parse_args()

    row = run_benchmark(args.clip, args.model, args.device, args.max_frames, args.imgsz)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row) + "\n")
    print(json.dumps(row, indent=2))


if __name__ == "__main__":
    main()
