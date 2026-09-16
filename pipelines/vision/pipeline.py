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
        quality = (
            CalibrationQuality.from_rms(calibration_rms_px)
            if calibration_rms_px is not None
            else CalibrationQuality(rms_px=float("inf"), valid=False)
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
