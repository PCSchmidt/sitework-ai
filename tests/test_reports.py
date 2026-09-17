from __future__ import annotations

from api.reports import render_shift_report_html
from pipelines.schemas import IncidentRecord, IncidentState, Severity


def _record(event_id: str, state: IncidentState, narrative: str = "") -> IncidentRecord:
    return IncidentRecord(
        event_id=event_id,
        camera_id="dock_north_01",
        trigger_ts=1000.0,
        severity=Severity.HIGH,
        state=state,
        narrative_md=narrative,
        recommended_actions=["pause_forklift_traffic"],
    )


def test_empty_window_renders_placeholder() -> None:
    html = render_shift_report_html([], from_ts=0.0, to_ts=100.0)
    assert "No incidents in this window" in html
    assert "<html>" in html


def test_incident_rows_render_narrative_and_actions() -> None:
    records = [
        _record("evt_1", IncidentState.CONFIRMED, narrative="Forklift near-miss."),
        _record("evt_2", IncidentState.NEEDS_REVIEW),
    ]
    html = render_shift_report_html(records, from_ts=0.0, to_ts=100.0)
    assert "evt_1" in html
    assert "Forklift near-miss." in html
    assert "pause_forklift_traffic" in html
    assert "evt_2" in html
    assert "2 incident(s)" in html


def test_narrative_is_html_escaped() -> None:
    records = [_record("evt_xss", IncidentState.CONFIRMED, narrative="<script>alert(1)</script>")]
    html = render_shift_report_html(records, from_ts=0.0, to_ts=100.0)
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html
