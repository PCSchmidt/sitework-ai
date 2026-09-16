"""Fast-path frame source: MP4 files (local/dev) and RTSP streams (docs/02 §1).

Decode backend is PyAV. MP4 sources loop forever to simulate live feeds;
RTSP sources reconnect with backoff. Frames are optionally downscaled at
decode time (the demo clips are 4K; inference runs at 1280x720).
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from dataclasses import dataclass

import av
import numpy as np


@dataclass(frozen=True)
class DecodedFrame:
    camera_id: str
    seq: int
    ts: float          # wall-clock capture time (epoch seconds)
    image: np.ndarray  # HxWx3 uint8 BGR (OpenCV convention)


class FrameSource:
    """Decode frames from an MP4 (looping) or RTSP URL at a target rate."""

    def __init__(
        self,
        camera_id: str,
        url: str,
        target_fps: float = 30.0,
        width: int | None = None,
        height: int | None = None,
        loop: bool = True,
    ) -> None:
        self.camera_id = camera_id
        self.url = url
        self.target_fps = target_fps
        self.size = (width, height) if width and height else None
        self.loop = loop

    def frames(self) -> Iterator[DecodedFrame]:
        seq = 0
        frame_period = 1.0 / self.target_fps
        while True:
            try:
                container = av.open(self.url)
            except Exception as exc:
                if self.url.startswith("rtsp://"):
                    time.sleep(2.0)
                    continue
                raise RuntimeError(f"cannot open {self.url}: {exc}") from exc

            with container:
                stream = container.streams.video[0]
                last_emit = 0.0
                for packet in container.demux(stream):
                    for frame in packet.decode():
                        now = time.time()
                        if now - last_emit < frame_period:
                            continue  # rate-limit to target_fps
                        last_emit = now
                        img = frame.to_ndarray(format="bgr24")
                        if self.size:
                            img = np.ascontiguousarray(
                                av.VideoFrame.from_ndarray(img, format="bgr24")
                                .reformat(width=self.size[0], height=self.size[1])
                                .to_ndarray(format="bgr24")
                            )
                        yield DecodedFrame(self.camera_id, seq, now, img)
                        seq += 1

            if not self.loop:
                return


def probe(url: str) -> dict[str, object]:
    """Return basic stream metadata (used by spike-00 and ingestion health checks)."""
    with av.open(url) as container:
        stream = container.streams.video[0]
        return {
            "codec": stream.codec_context.name,
            "width": stream.codec_context.width,
            "height": stream.codec_context.height,
            "fps": float(stream.average_rate or 0),
            "frames": stream.frames,
            "duration_s": float(container.duration / av.time_base) if container.duration else None,
        }
