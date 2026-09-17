"""Evidence window capture for TriggerEvents (docs/12 M2, docs/06 §6 `track_frames`).

When a TriggerEvent fires, downstream consumers (the Band-3 recomputation
gate, the incident UI) need the telemetry and footage around it, not just
the event pointer. This module keeps short rolling buffers of recently
published TrackletFrames and the images they were built from, and on a
trigger, captures `[trigger_ts - pre_window_s, trigger_ts + post_window_s]`
to `incidents/{event_id}/tracks.jsonl` + `clip.mp4` -- the exact paths
`RuleEngine` already stamps onto `track_window_ref`/`clip_ref`.

Buffers/clips are built from the same ~10 Hz cadence the vision pipeline
publishes TrackletFrames at (not full decode-rate); that's a deliberate
memory/simplicity tradeoff for a demo-scale system, not full-fidelity
evidence video.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

import av
import numpy as np

from pipelines.schemas import TrackletFrame, TriggerEvent

DEFAULT_PRE_WINDOW_S = 5.0
DEFAULT_POST_WINDOW_S = 5.0
EVIDENCE_DIR = Path("incidents")


@dataclass
class _BufferedFrame:
    ts: float
    image: np.ndarray
    tracklet: TrackletFrame


@dataclass
class _OpenWindow:
    event_id: str
    camera_id: str
    end_ts: float
    buffered: list[_BufferedFrame] = field(default_factory=list)


class EvidenceCapture:
    """Call `on_frame` for every published TrackletFrame, `on_trigger` when RuleEngine fires."""

    def __init__(
        self,
        out_dir: Path = EVIDENCE_DIR,
        pre_window_s: float = DEFAULT_PRE_WINDOW_S,
        post_window_s: float = DEFAULT_POST_WINDOW_S,
        buffer_retention_s: float | None = None,
    ) -> None:
        self.out_dir = out_dir
        self.pre_window_s = pre_window_s
        self.post_window_s = post_window_s
        # how far back the rolling buffer keeps frames even with no trigger yet
        self._retention_s = buffer_retention_s if buffer_retention_s is not None else pre_window_s
        self._recent: dict[str, deque[_BufferedFrame]] = {}
        self._open_windows: dict[str, _OpenWindow] = {}

    def on_frame(self, camera_id: str, image: np.ndarray, tracklet: TrackletFrame) -> list[Path]:
        """Buffer this frame, extend/finalize any open windows. Returns paths written, if any."""
        buffered = _BufferedFrame(ts=tracklet.frame_ts, image=image, tracklet=tracklet)

        recent = self._recent.setdefault(camera_id, deque())
        recent.append(buffered)
        cutoff = tracklet.frame_ts - self._retention_s
        while recent and recent[0].ts < cutoff:
            recent.popleft()

        for window in self._open_windows.values():
            if window.camera_id == camera_id and buffered.ts <= window.end_ts:
                window.buffered.append(buffered)

        return self._finalize_expired(tracklet.frame_ts)

    def on_trigger(
        self, camera_id: str, image: np.ndarray, tracklet: TrackletFrame, events: list[TriggerEvent]
    ) -> None:
        """Open a capture window per fired event, seeded with the buffered pre-trigger frames."""
        for event in events:
            if event.event_id in self._open_windows:
                continue  # cooldown makes this unlikely, but stay idempotent
            pre_cutoff = event.trigger_ts - self.pre_window_s
            seed = [f for f in self._recent.get(camera_id, ()) if f.ts >= pre_cutoff]
            self._open_windows[event.event_id] = _OpenWindow(
                event_id=event.event_id,
                camera_id=camera_id,
                end_ts=event.trigger_ts + self.post_window_s,
                buffered=list(seed),
            )

    def flush_all(self) -> list[Path]:
        """Finalize every still-open window (e.g. on shutdown), regardless of end_ts."""
        written = []
        for event_id in list(self._open_windows):
            written.extend(self._finalize(event_id))
        return written

    def _finalize_expired(self, now_ts: float) -> list[Path]:
        written = []
        expired = [eid for eid, w in self._open_windows.items() if now_ts >= w.end_ts]
        for event_id in expired:
            written.extend(self._finalize(event_id))
        return written

    def _finalize(self, event_id: str) -> list[Path]:
        window = self._open_windows.pop(event_id)
        window.buffered.sort(key=lambda f: f.ts)
        event_dir = self.out_dir / event_id
        event_dir.mkdir(parents=True, exist_ok=True)

        tracks_path = event_dir / "tracks.jsonl"
        with tracks_path.open("w", encoding="utf-8") as fh:
            for buffered in window.buffered:
                fh.write(buffered.tracklet.model_dump_json() + "\n")

        clip_path = event_dir / "clip.mp4"
        _write_clip(clip_path, [f.image for f in window.buffered])

        return [tracks_path, clip_path]


def _write_clip(path: Path, images: list[np.ndarray], fps: float = 10.0) -> None:
    if not images:
        return
    height, width = images[0].shape[:2]
    container = av.open(str(path), mode="w")
    try:
        stream = container.add_stream("h264", rate=round(fps))
        stream.width = width
        stream.height = height
        stream.pix_fmt = "yuv420p"
        for image in images:
            frame = av.VideoFrame.from_ndarray(image, format="bgr24")
            for packet in stream.encode(frame):
                container.mux(packet)
        for packet in stream.encode():
            container.mux(packet)
    finally:
        container.close()
