"""Fast-path pipeline: decode -> detect -> track -> TrackletFrame publisher (docs/02).

M1 scope: single stream, detector + Ultralytics ByteTrack, TrackletFrame
published to Redis Streams at ~10 Hz. Geometry (homography -> metric
ground points) lands in M2; until then ground_point_m/velocity_mps stay
null and zone_ids empty, per schema.
"""

from __future__ import annotations

import time

import redis

from pipelines.ingestion.frame_source import FrameSource
from pipelines.schemas import CalibrationQuality, TrackletFrame
from pipelines.vision.detector import COCO_TO_SITEWATCH, Detector

PUBLISH_HZ = 10.0
STREAM_KEY_PREFIX = "tracklets"
STREAM_MAXLEN = 50_000  # ring retention; M2 hardens (consumer groups, replay)


def run_stream(
    camera_id: str,
    url: str,
    detector: Detector,
    redis_url: str = "redis://localhost:6379",
    calibration_rms_px: float | None = None,
) -> None:
    r = redis.Redis.from_url(redis_url)
    publish_period = 1.0 / PUBLISH_HZ
    last_publish = 0.0

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
                tracks.append(
                    {
                        "track_id": int(tid),
                        "cls": cls,
                        "confidence": float(conf),
                        "bbox_px": [float(v) for v in box],
                        "state": {"cov_trace": 0.0, "age_frames": 0, "hits": 0},
                        "zone_ids": [],
                        "ppe": {"helmet": None, "vest": None},
                    }
                )

        # Calibration is an M2 artifact; absent config -> invalid, rules stay zone-only.
        # NOTE: finite sentinel (not inf) — Pydantic JSON-serializes inf as null,
        # which fails schema validation on read (caught by the M1 Redis gate).
        quality = (
            CalibrationQuality.from_rms(calibration_rms_px)
            if calibration_rms_px is not None
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
    run_stream(args.camera_id, args.url, detector, redis_url=args.redis)


if __name__ == "__main__":
    main()
