"""Offline showcase recorder: run the fast path over one MP4, save what it saw.

The public demo (GitHub Pages) can't run a GPU, so the dashboard's camera
player replays *recorded* fast-path output instead: this module runs the same
detect -> track -> ground-project -> zones -> RuleEngine path as the live
`pipelines.vision.pipeline.run_stream` (via the shared `build_tracks`), over
every frame of a clip, and writes

    {out_dir}/{camera_id}/video.mp4      web-playable H.264 copy of the clip
    {out_dir}/{camera_id}/showcase.json  per-frame tracks, zones (px + m),
                                         calibration, rules, and every
                                         TriggerEvent RuleEngine emitted

Differences from the live loop, all deliberate:
- timestamps are clip-relative seconds (from the decoded frame's pts), not
  wall-clock, so the browser can sync the overlay to `video.currentTime`;
- every frame is decoded and tracked (no wall-clock rate limiting), and every
  frame's boxes are recorded for a smooth overlay, but velocity and the rule
  engine still run at the live loop's PUBLISH_HZ, so rule behavior matches;
- nothing is published to Redis.

For a panning camera (calibration with a `reference_image`), each frame's
calibration is motion-compensated exactly as in the live loop, and the frame's
reference -> frame pixel homography is saved as `cam`, so the player can warp
zone outlines (stored in reference-frame pixels) to follow the camera.

Usage:
    uv run python -m pipelines.vision.record \\
        --camera-id dock_north_01 \\
        --clip assets/clips/forklift_workers_interaction_1080p.mp4 \\
        --out-dir ui/public/showcase
"""

from __future__ import annotations

import argparse
import json
import subprocess
import time
from pathlib import Path
from typing import Any

import av
import numpy as np

from pipelines.config.loader import load_cameras, load_rules, load_zones
from pipelines.geometry.calibration_store import CALIBRATION_DIR, Calibration, load_calibration
from pipelines.geometry.zones import ZoneEngine
from pipelines.schemas import CalibrationQuality, TrackletFrame
from pipelines.vision.detector import Detector
from pipelines.vision.evidence import EvidenceCapture
from pipelines.vision.pipeline import (
    PUBLISH_HZ,
    GroundHistory,
    build_tracks,
    motion_compensator_for,
)
from pipelines.vision.rules import RuleEngine

# Densify zone edges before projecting to pixels so long ground-plane edges
# bend correctly under perspective (and points behind the camera can be dropped).
_ZONE_EDGE_SAMPLES = 24


def zone_polygon_px(
    polygon_m: list[tuple[float, float]],
    calibration: Calibration,
    reference_px: tuple[float, float],
) -> list[tuple[float, float]]:
    """Project a ground-plane polygon (meters) into image pixels.

    Edges are densified, then each point is mapped through H^-1; points whose
    homogeneous w has the opposite sign to `reference_px` (a pixel known to
    be on the visible ground, e.g. bottom-center of the frame) lie behind the
    camera and are dropped.
    """
    h_inv = np.linalg.inv(calibration.homography.matrix)
    gx, gy = calibration.homography.apply(reference_px)
    ref_sign = np.sign((h_inv @ np.array([gx, gy, 1.0]))[2])

    out: list[tuple[float, float]] = []
    n = len(polygon_m)
    for i in range(n):
        (x0, y0), (x1, y1) = polygon_m[i], polygon_m[(i + 1) % n]
        for k in range(_ZONE_EDGE_SAMPLES):
            s = k / _ZONE_EDGE_SAMPLES
            vec = h_inv @ np.array([x0 + s * (x1 - x0), y0 + s * (y1 - y0), 1.0])
            if np.sign(vec[2]) != ref_sign or abs(vec[2]) < 1e-12:
                continue
            out.append((round(float(vec[0] / vec[2]), 1), round(float(vec[1] / vec[2]), 1)))
    return out


def _compact_track(t: dict[str, Any]) -> dict[str, Any]:
    g = t["ground_point_m"]
    return {
        "id": t["track_id"],
        "cls": t["cls"],
        "conf": round(t["confidence"], 3),
        "bbox": [round(v, 1) for v in t["bbox_px"]],
        "g": [round(g[0], 3), round(g[1], 3)] if g is not None else None,
        "speed": round(t["speed_mps"], 3) if t["speed_mps"] is not None else None,
        "zones": t["zone_ids"],
    }


def record(
    camera_id: str,
    clip: Path,
    out_dir: Path,
    detector: Detector,
    note: str | None = None,
    transcode: bool = True,
    evidence_dir: Path | None = None,
    base_ts: float | None = None,
) -> dict[str, Any]:
    """Record one clip. With `evidence_dir`, every TriggerEvent also gets the
    live pipeline's evidence folder (`EvidenceCapture`: tracks.jsonl + clip.mp4)
    plus its `event.json`, ready for the slow plane (`scripts/showcase_agent.py`).
    TrackletFrame/TriggerEvent timestamps are `base_ts + clip time` (default: now),
    so incidents carry real dates; the showcase frames keep clip-relative `t`.
    """
    calibration = load_calibration(camera_id)
    zones_cfg = load_zones()
    rules_cfg = load_rules()
    zone_engine = ZoneEngine(zones_cfg) if calibration is not None else None
    rule_engine = RuleEngine(rules_cfg)
    motion = motion_compensator_for(calibration)
    evidence = EvidenceCapture(out_dir=evidence_dir) if evidence_dir is not None else None
    base_ts = float(int(time.time())) if base_ts is None else base_ts
    quality = (
        calibration.quality
        if calibration is not None
        else CalibrationQuality(rms_px=9999.0, valid=False)
    )

    frames: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    prev_ground: dict[int, GroundHistory] = {}
    publish_period = 1.0 / PUBLISH_HZ
    last_publish = -1e9
    seq = 0

    with av.open(str(clip)) as container:
        stream = container.streams.video[0]
        fps = float(stream.average_rate or 25)
        width, height = stream.codec_context.width, stream.codec_context.height
        time_base = float(stream.time_base) if stream.time_base else 1.0 / fps
        for frame in container.decode(stream):
            t = float(frame.pts * time_base) if frame.pts is not None else seq / fps
            image = frame.to_ndarray(format="bgr24")
            result = detector.model.track(
                image,
                persist=True,
                tracker="bytetrack.yaml",
                device=detector.device,
                imgsz=detector.imgsz,
                verbose=False,
            )[0]

            frame_calibration = calibration
            cam: list[float] | None = None
            if calibration is not None and motion is not None:
                frame_to_ref = motion.frame_to_reference(image)
                frame_calibration = calibration.for_frame(frame_to_ref)
                ref_to_frame = np.linalg.inv(frame_to_ref)
                ref_to_frame /= ref_to_frame[2, 2]
                cam = [round(float(v), 7) for v in ref_to_frame.ravel()[:8]]

            publish = t - last_publish >= publish_period - 1e-6
            tracks = build_tracks(
                result,
                detector,
                camera_id,
                t,
                frame_calibration,
                zone_engine,
                prev_ground,
                update_kinematics=publish,
            )
            record_frame: dict[str, Any] = {
                "t": round(t, 4),
                "tracks": [_compact_track(tr) for tr in tracks],
            }
            if cam is not None:
                record_frame["cam"] = cam
            frames.append(record_frame)

            if publish:
                last_publish = t
                msg = TrackletFrame(
                    camera_id=camera_id,
                    frame_ts=base_ts + t,
                    seq=seq,
                    calibration_quality=quality,
                    tracks=tracks,  # type: ignore[arg-type]
                )
                if evidence is not None:
                    evidence.on_frame(camera_id, image, msg)
                fired = rule_engine.process(msg)
                if evidence is not None and fired:
                    evidence.on_trigger(camera_id, image, msg, fired)
                    for event in fired:
                        event_dir = evidence.out_dir / event.event_id
                        event_dir.mkdir(parents=True, exist_ok=True)
                        (event_dir / "event.json").write_text(
                            event.model_dump_json(indent=2), encoding="utf-8"
                        )
                for event in fired:
                    rule = next(r for r in rules_cfg.rules if r.id == event.rule_id)
                    events.append(
                        {
                            "t": round(t, 4),
                            "trigger_ts": event.trigger_ts,
                            "event_id": event.event_id,
                            "rule_id": event.rule_id,
                            "kind": str(rule.kind),
                            "description": rule.description,
                            "citation": rule.citation,
                            "severity": str(event.severity_hint),
                            "track_ids": event.involved_track_ids,
                            "metrics": event.metrics.model_dump(exclude_none=True),
                        }
                    )
            seq += 1
    if evidence is not None:
        evidence.flush_all()

    zones_out: list[dict[str, Any]] = []
    if calibration is not None:
        for z in zones_cfg.zones:
            if z.camera_id != camera_id or not z.active:
                continue
            poly_m = [(float(x), float(y)) for x, y in z.polygon_m]
            zones_out.append(
                {
                    "id": z.id,
                    "kind": str(z.kind),
                    "polygon_m": poly_m,
                    "polygon_px": zone_polygon_px(poly_m, calibration, (width / 2, height - 1)),
                }
            )

    camera = next((c for c in load_cameras().cameras if c.id == camera_id), None)
    rule_ids = {e["rule_id"] for e in events} | {
        r.id for r in rules_cfg.rules if any(z["id"] in (r.zone_ids or []) for z in zones_out)
    }
    showcase = {
        "camera_id": camera_id,
        "name": camera.name if camera is not None else camera_id,
        "video": "video.mp4",
        "source_clip": clip.name,
        "fps": round(fps, 3),
        "width": width,
        "height": height,
        "duration_s": round(frames[-1]["t"] + 1.0 / fps, 3) if frames else 0.0,
        "detector": {
            "weights": Path(str(detector.model.ckpt_path or "")).name,
            "imgsz": detector.imgsz,
            "confidence_gate": detector.confidence_gate,
        },
        "publish_hz": PUBLISH_HZ,
        "note": note,
        "calibration": _calibration_summary(camera_id) if calibration is not None else None,
        "zones": zones_out,
        "rules": [
            {
                "id": r.id,
                "kind": str(r.kind),
                "description": r.description,
                "citation": r.citation,
                "zone_ids": r.zone_ids,
                "radius_m": r.radius_m,
                "duration_s": r.duration_s,
                "dwell_s": r.dwell_s,
                "limit_mps": r.limit_mps,
            }
            for r in rules_cfg.rules
            if r.id in rule_ids
        ],
        "events": events,
        "frames": frames,
    }

    cam_dir = out_dir / camera_id
    cam_dir.mkdir(parents=True, exist_ok=True)
    (cam_dir / "showcase.json").write_text(
        json.dumps(showcase, separators=(",", ":")), encoding="utf-8"
    )
    if transcode:
        # 720p H.264, no audio, moov atom up front so browsers can start playback
        # (and seek) before the whole file arrives.
        subprocess.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-y",
                "-i",
                str(clip),
                "-vf",
                "scale=1280:-2",
                "-c:v",
                "libx264",
                "-preset",
                "slow",
                "-crf",
                "27",
                "-pix_fmt",
                "yuv420p",
                "-an",
                "-movflags",
                "+faststart",
                str(cam_dir / "video.mp4"),
            ],
            check=True,
        )
    write_index(out_dir)
    return showcase


def _calibration_summary(camera_id: str) -> dict[str, Any]:
    """The calibration file as recorded (method, quality, stated assumptions), minus the matrix."""
    data = json.loads((CALIBRATION_DIR / f"{camera_id}.json").read_text(encoding="utf-8"))
    return {k: v for k, v in data.items() if k not in {"homography_px_to_m", "points", "camera_id"}}


def write_index(out_dir: Path) -> None:
    """`{out_dir}/index.json`: one summary row per recorded camera, cameras with events first."""
    rows = []
    for path in sorted(out_dir.glob("*/showcase.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        rows.append(
            {
                "camera_id": data["camera_id"],
                "name": data["name"],
                "note": data.get("note"),
                "duration_s": data["duration_s"],
                "events": len(data["events"]),
                "calibration": None
                if data["calibration"] is None
                else {
                    "method": data["calibration"].get("method"),
                    "valid": data["calibration"].get("valid"),
                },
            }
        )
    rows.sort(key=lambda r: (-r["events"], r["camera_id"]))
    (out_dir / "index.json").write_text(json.dumps(rows, indent=1), encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description="Record fast-path output for the showcase player")
    ap.add_argument("--camera-id", required=True)
    ap.add_argument("--clip", required=True, type=Path)
    ap.add_argument("--out-dir", type=Path, default=Path("ui/public/showcase"))
    ap.add_argument("--weights", default="yolo11s.pt")
    ap.add_argument("--device", default="cuda:0")
    ap.add_argument("--imgsz", type=int, default=640)
    ap.add_argument("--confidence-gate", type=float, default=0.4)
    ap.add_argument("--note", default=None, help="caption shown on the camera's showcase card")
    ap.add_argument("--no-transcode", action="store_true")
    ap.add_argument(
        "--evidence-dir",
        type=Path,
        default=None,
        help="also write each TriggerEvent's evidence folder here (event.json, tracks.jsonl, "
        "clip.mp4) for scripts/showcase_agent.py",
    )
    args = ap.parse_args()

    detector = Detector(
        weights=args.weights,
        device=args.device,
        confidence_gate=args.confidence_gate,
        imgsz=args.imgsz,
    )
    showcase = record(
        args.camera_id,
        args.clip,
        args.out_dir,
        detector,
        note=args.note,
        transcode=not args.no_transcode,
        evidence_dir=args.evidence_dir,
    )
    n_tracks = len({t["id"] for f in showcase["frames"] for t in f["tracks"]})
    print(
        f"{args.camera_id}: {len(showcase['frames'])} frames, {n_tracks} tracks, "
        f"{len(showcase['events'])} events -> {args.out_dir / args.camera_id}"
    )
    for e in showcase["events"]:
        print(f"  t={e['t']:.2f}s {e['rule_id']} tracks={e['track_ids']} {e['metrics']}")


if __name__ == "__main__":
    main()
