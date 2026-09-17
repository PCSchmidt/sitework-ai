"""Fast-path pipeline: decode -> detect -> track -> TrackletFrame publisher (docs/02).

M1 scope: single stream, detector + Ultralytics ByteTrack, TrackletFrame
published to Redis Streams at ~10 Hz. M2 adds ground-plane projection: if a
calibration exists for the camera (`config/calibration/{camera_id}.json`,
written by `pipelines.geometry.calibrate`), each track's bottom-center pixel
is projected through the homography to `ground_point_m`, velocity is a
finite difference against the track's previous ground point, and `zone_ids`
comes from `pipelines.geometry.zones.ZoneEngine`. Without a valid
calibration, ground_point_m/velocity_mps stay null and zone_ids empty, per
schema (rules requiring metric distance degrade to zone-only, docs/04 §3).
"""

from __future__ import annotations

import time

import redis

from pipelines.config.loader import load_zones
from pipelines.geometry.calibration_store import Calibration, load_calibration
from pipelines.geometry.zones import ZoneEngine
from pipelines.ingestion.frame_source import FrameSource
from pipelines.schemas import CalibrationQuality, TrackletFrame
from pipelines.vision.detector import COCO_TO_SITEWATCH, Detector

PUBLISH_HZ = 10.0
STREAM_KEY_PREFIX = "tracklets"
STREAM_MAXLEN = 50_000  # ring retention; M2 hardens (consumer groups, replay)


def _bottom_center(bbox_px: tuple[float, float, float, float]) -> tuple[float, float]:
    x1, _y1, x2, y2 = bbox_px
    return ((x1 + x2) / 2, y2)


def run_stream(
    camera_id: str,
    url: str,
    detector: Detector,
    redis_url: str = "redis://localhost:6379",
    calibration: Calibration | None = None,
    zone_engine: ZoneEngine | None = None,
) -> None:
    r = redis.Redis.from_url(redis_url)
    publish_period = 1.0 / PUBLISH_HZ
    last_publish = 0.0
    # per-track previous ground point + timestamp, for finite-difference velocity
    prev_ground: dict[int, tuple[tuple[float, float], float]] = {}

    source = FrameSource(camera_id, url)
    for frame in source.frames():
        # Ultralytics ByteTrack: persist=True keeps IDs across calls.
        result = detector.model.track(
            frame.image,
            persist=True,
            tracker="bytetrack.yaml",
            device=detector.device,
            imgsz=detector.imgsz,
            verbose=False,
        )[0]

        now = time.time()
        if now - last_publish < publish_period:
            continue
        last_publish = now

        tracks = []
        if result.boxes is not None and result.boxes.id is not None:
            ids = result.boxes.id.cpu().numpy().astype(int)
            boxes = result.boxes.xyxy.cpu().numpy()
            confs = result.boxes.conf.cpu().numpy()
            clss = result.boxes.cls.cpu().numpy().astype(int)
            for tid, box, conf, cid in zip(ids, boxes, confs, clss, strict=True):
                cls = COCO_TO_SITEWATCH.get(result.names[cid])
                if cls is None or conf < detector.confidence_gate:
                    continue
                track_id = int(tid)
                bx1, by1, bx2, by2 = (float(v) for v in box)
                bbox_px: tuple[float, float, float, float] = (bx1, by1, bx2, by2)

                ground_point_m: tuple[float, float] | None = None
                velocity_mps: tuple[float, float] | None = None
                speed_mps: float | None = None
                zone_ids: list[str] = []
                if calibration is not None and calibration.quality.valid:
                    ground_point_m = calibration.homography.apply(_bottom_center(bbox_px))
                    if track_id in prev_ground:
                        (px, py), pt = prev_ground[track_id]
                        dt = now - pt
                        if dt > 0:
                            vx = (ground_point_m[0] - px) / dt
                            vy = (ground_point_m[1] - py) / dt
                            velocity_mps = (vx, vy)
                            speed_mps = (vx**2 + vy**2) ** 0.5
                    prev_ground[track_id] = (ground_point_m, now)
                    if zone_engine is not None:
                        zone_ids = zone_engine.zone_ids_containing(camera_id, ground_point_m)

                tracks.append(
                    {
                        "track_id": track_id,
                        "cls": cls,
                        "confidence": float(conf),
                        "bbox_px": list(bbox_px),
                        "ground_point_m": ground_point_m,
                        "velocity_mps": velocity_mps,
                        "speed_mps": speed_mps,
                        "state": {"cov_trace": 0.0, "age_frames": 0, "hits": 0},
                        "zone_ids": zone_ids,
                        "ppe": {"helmet": None, "vest": None},
                    }
                )

        # Absent/invalid calibration -> rules stay zone-only (docs/04 §3).
        # NOTE: finite sentinel (not inf) — Pydantic JSON-serializes inf as null,
        # which fails schema validation on read (caught by the M1 Redis gate).
        quality = (
            calibration.quality
            if calibration is not None
            else CalibrationQuality(rms_px=9999.0, valid=False)
        )

        msg = TrackletFrame(
            camera_id=camera_id,
            frame_ts=frame.ts,
            seq=frame.seq,
            calibration_quality=quality,
            tracks=tracks,  # type: ignore[arg-type]
        )
        r.xadd(
            f"{STREAM_KEY_PREFIX}:{camera_id}",
            {"payload": msg.model_dump_json()},
            maxlen=STREAM_MAXLEN,
            approximate=True,
        )


def main() -> None:
    import argparse
    import os

    ap = argparse.ArgumentParser(description="Fast-path vision worker (docs/02)")
    ap.add_argument("--camera-id", required=True)
    ap.add_argument("--url", required=True, help="RTSP URL or MP4 path")
    ap.add_argument("--weights", default=os.environ.get("YOLO_WEIGHTS", "yolo11s.pt"))
    ap.add_argument("--device", default="cuda:0")
    ap.add_argument("--redis", default=os.environ.get("REDIS_URL", "redis://localhost:6379"))
    ap.add_argument("--imgsz", type=int, default=640)
    ap.add_argument("--confidence-gate", type=float, default=0.4)
    args = ap.parse_args()

    detector = Detector(
        weights=args.weights,
        device=args.device,
        confidence_gate=args.confidence_gate,
        imgsz=args.imgsz,
    )
    calibration = load_calibration(args.camera_id)
    zone_engine = ZoneEngine(load_zones()) if calibration is not None else None
    run_stream(
        args.camera_id,
        args.url,
        detector,
        redis_url=args.redis,
        calibration=calibration,
        zone_engine=zone_engine,
    )


if __name__ == "__main__":
    main()
