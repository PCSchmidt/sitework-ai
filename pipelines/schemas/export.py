"""Export Pydantic models as JSON Schema into schemas/ for the TS dashboard (docs/06).

Run: `make schema-export` (or `uv run python -m pipelines.schemas.export`).
CI fails if the exported files drift from the models.
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel

from pipelines.schemas.models import (
    IncidentRecord,
    KinematicsVerdict,
    TrackletFrame,
    TriggerEvent,
)

OUT_DIR = Path(__file__).resolve().parents[2] / "schemas"

MODELS: dict[str, type[BaseModel]] = {
    "tracklet_frame": TrackletFrame,
    "trigger_event": TriggerEvent,
    "kinematics_verdict": KinematicsVerdict,
    "incident_record": IncidentRecord,
}


def export() -> list[Path]:
    OUT_DIR.mkdir(exist_ok=True)
    written: list[Path] = []
    for name, model in MODELS.items():
        path = OUT_DIR / f"{name}.schema.json"
        path.write_text(json.dumps(model.model_json_schema(), indent=2) + "\n")
        written.append(path)
    return written


if __name__ == "__main__":
    for p in export():
        print(f"wrote {p.relative_to(OUT_DIR.parent)}")
