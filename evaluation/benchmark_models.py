"""Benchmark harness (docs/04 §5; drives spike-00, and the M5 benchmark matrix).

v1 (M1) measured a single decode+detect stream in-process. This adds the two
axes M5 actually needs (docs/12-roadmap.md M5 item 1): **precision**
(FP32 .pt vs FP16 TensorRT .engine, via `--model`/`--model-fp16`) and
**streams** (`--streams N`, one OS process per stream so each gets its own
CUDA context -- matches how the real fast path runs, one process per camera
in docker-compose, not a single-process asyncio fan-out that would share one
context and measure something the real deployment never does).

Usage (single stream, unchanged from v1):
    uv run python -m evaluation.benchmark_models \
        --clip assets/clips/worker_walking_aisle_1080p.mp4 \
        --model data/models/yolo11n.pt --device cuda:0 \
        --out docs/spikes/spike-00-results.jsonl

Usage (multi-stream matrix cell):
    uv run python -m evaluation.benchmark_models \
        --clip assets/clips/worker_walking_aisle_1080p.mp4 \
        --model data/models/yolo11s.engine --device cuda:0 --streams 3 \
        --out docs/benchmarks-m5.jsonl
"""

from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import time
from concurrent.futures import ProcessPoolExecutor
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

    thermal_before = _gpu_thermal_snapshot() if device.startswith("cuda") else None
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
        row["gpu_thermal_before"] = thermal_before
        row["gpu_thermal_after"] = _gpu_thermal_snapshot()
    return row


def _p95(values: list[float]) -> float:
    values = sorted(values)
    return values[min(len(values) - 1, int(len(values) * 0.95))]


def _stream_worker(args: tuple[str, str, str, int, int]) -> dict[str, object]:
    """Top-level (picklable) entry point for one `ProcessPoolExecutor` stream --
    each worker process gets its own CUDA context, same as one vision-worker
    container per camera in docker-compose (docs/07 §4)."""
    clip, weights, device, max_frames, imgsz = args
    return run_benchmark(Path(clip), weights, device, max_frames, imgsz)


def _gpu_thermal_snapshot() -> dict[str, object] | None:
    """docs/benchmarks.md's own M2 action item: FPS on this laptop GPU is
    meaningless without a thermal/power qualifier (spike-00 found ~2x
    clean-boot-vs-sustained-load throttling) -- record it alongside every
    multi-stream run rather than leaving it implicit."""
    try:
        out = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=temperature.gpu,power.draw,clocks.sm,utilization.gpu",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        )
        temp_c, power_w, clock_mhz, util_pct = (v.strip() for v in out.stdout.strip().split(","))
        return {
            "temp_c": float(temp_c),
            "power_w": float(power_w),
            "sm_clock_mhz": float(clock_mhz),
            "util_pct": float(util_pct),
        }
    except Exception:
        return None


def run_multi_stream(
    clips: list[Path],
    weights: str,
    device: str,
    max_frames: int,
    imgsz: int,
    streams: int,
) -> dict[str, object]:
    """Runs `streams` concurrent single-stream benchmarks (one clip per
    stream, cycling `clips` if fewer clips than streams were given) and
    reports both per-stream and aggregate throughput -- "3-stream FPS" means
    the aggregate across concurrently-contending streams, not 3x a
    since-measured single-stream number."""
    assigned = [clips[i % len(clips)] for i in range(streams)]
    args = [(str(c), weights, device, max_frames, imgsz) for c in assigned]

    thermal_before = _gpu_thermal_snapshot()
    started = time.perf_counter()
    with ProcessPoolExecutor(max_workers=streams) as pool:
        per_stream = list(pool.map(_stream_worker, args))
    wall_s = time.perf_counter() - started
    thermal_after = _gpu_thermal_snapshot()

    total_frames = sum(int(r["frames"]) for r in per_stream)
    fps_values = [float(r["fps"]) for r in per_stream if r["fps"] is not None]
    return {
        "streams": streams,
        "clips": [str(c) for c in assigned],
        "model": weights,
        "device": device,
        "imgsz": imgsz,
        "wall_s": round(wall_s, 2),
        "aggregate_fps": round(total_frames / wall_s, 1) if wall_s > 0 else None,
        "per_stream_fps": fps_values,
        "min_stream_fps": round(min(fps_values), 1) if fps_values else None,
        "per_stream_detail": per_stream,
        "gpu_thermal_before": thermal_before,
        "gpu_thermal_after": thermal_after,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--clip", type=Path, action="append", dest="clips")
    ap.add_argument("--model", default="data/models/yolo11n.pt")
    ap.add_argument("--device", default="cpu")
    ap.add_argument("--imgsz", type=int, default=640)
    ap.add_argument("--max-frames", type=int, default=300)
    ap.add_argument("--streams", type=int, default=1)
    ap.add_argument("--out", type=Path, default=Path("docs/spikes/spike-00-results.jsonl"))
    args = ap.parse_args()

    clips = args.clips or [Path("assets/clips/worker_walking_aisle_1080p.mp4")]
    args.out.parent.mkdir(parents=True, exist_ok=True)

    if args.streams == 1:
        row = run_benchmark(clips[0], args.model, args.device, args.max_frames, args.imgsz)
    else:
        row = run_multi_stream(
            clips, args.model, args.device, args.max_frames, args.imgsz, args.streams
        )

    with args.out.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row) + "\n")
    print(json.dumps(row, indent=2))


if __name__ == "__main__":
    main()
