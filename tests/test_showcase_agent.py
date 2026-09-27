"""scripts/showcase_agent.py: published transcripts must not carry local paths."""

from __future__ import annotations

import json

import pytest
from scripts.showcase_agent import redact_workspace


@pytest.mark.parametrize(
    "path",
    [
        "C:/Users/someone/AppData/Local/Temp/showcase-agent-273s3ei3",
        r"C:\Users\someone\AppData\Local\Temp\showcase-agent-ab12",
        "/tmp/showcase-agent-xyz_9",
    ],
)
def test_workspace_paths_are_replaced(path: str) -> None:
    text = f"os.chdir(r'{path}/incidents/evt_1')"
    out = redact_workspace(text)
    assert "someone" not in out and "tmp" not in out
    assert out == "os.chdir(r'<workspace>/incidents/evt_1')"


def test_json_escaped_windows_paths_are_replaced() -> None:
    encoded = json.dumps({"code": r"open('C:\Users\someone\Temp\showcase-agent-q1\x.json')"})
    assert "someone" not in redact_workspace(encoded)


def test_other_text_is_untouched() -> None:
    text = "tracks.jsonl has 67 frames in cross_aisle_west"
    assert redact_workspace(text) == text
