"""Shift report rendering (docs/01 §5, M4).

Renders the incidents in a time window to a single styled HTML page. This is
the per-incident `narrative_md` each `IncidentRecord` already carries,
stitched into one page -- not a new T3-synthesized cross-incident narrative
(docs/05 mentions that as a future scheduled-agent capability; building it
means a new agent prompt/eval pair, out of scope for the delivery-plane
pass this belongs to). No PDF export yet either -- that's a headless-browser
or wkhtmltopdf dependency to add later if wanted; a browser's own "Print to
PDF" on this HTML is the interim path.

Pure function, no I/O -- kept separate from api/main.py so it's unit
testable without a live Postgres.
"""

from __future__ import annotations

import html
from datetime import UTC, datetime

from pipelines.schemas import IncidentRecord

_STYLE = """
<style>
  body { font-family: -apple-system, Segoe UI, sans-serif; background:#0f172a; color:#e2e8f0;
         margin:0; padding:2rem; }
  h1 { font-size:1.5rem; margin-bottom:0.25rem; }
  .meta { color:#94a3b8; margin-bottom:1.5rem; }
  .kpis { display:flex; gap:1rem; margin-bottom:2rem; flex-wrap:wrap; }
  .kpi { background:#1e293b; border-radius:8px; padding:0.75rem 1rem; min-width:120px; }
  .kpi .n { font-size:1.5rem; font-weight:700; }
  .kpi .label { color:#94a3b8; font-size:0.8rem; }
  .incident { background:#1e293b; border-radius:8px; padding:1rem 1.25rem; margin-bottom:1rem;
              border-left:4px solid #475569; }
  .incident.confirmed { border-left-color:#f87171; }
  .incident.needs_review { border-left-color:#fbbf24; }
  .incident h2 { font-size:1rem; margin:0 0 0.25rem 0; font-family:monospace; }
  .incident .row { color:#94a3b8; font-size:0.85rem; margin-bottom:0.5rem; }
  .incident p { margin:0.5rem 0; white-space:pre-wrap; }
  .badge { display:inline-block; padding:0.1rem 0.5rem; border-radius:999px; font-size:0.75rem;
           background:#334155; margin-right:0.35rem; }
</style>
"""


def _fmt_ts(ts: float) -> str:
    # from_ts/to_ts are caller-supplied query params (api/main.py's shift_report
    # route) with no range validation -- a huge value (e.g. a typo'd extra digit)
    # would otherwise crash datetime.fromtimestamp with an unhandled 500 instead
    # of just rendering an out-of-range placeholder. Real bug caught by CI's
    # integration test (tests/test_api.py), not by local runs -- this repo's own
    # dev environment never had a reachable Postgres to run that test against.
    try:
        return datetime.fromtimestamp(ts, tz=UTC).strftime("%Y-%m-%d %H:%M UTC")
    except (ValueError, OverflowError, OSError):
        return f"(out of range: {ts})"


def render_shift_report_html(
    records: list[IncidentRecord], from_ts: float, to_ts: float
) -> str:
    by_state: dict[str, int] = {}
    for r in records:
        key = str(r.state)
        by_state[key] = by_state.get(key, 0) + 1

    total_card = (
        f'<div class="kpi"><div class="n">{len(records)}</div><div class="label">total</div></div>'
    )
    kpi_cards = [total_card] + [
        f'<div class="kpi"><div class="n">{n}</div>'
        f'<div class="label">{html.escape(state)}</div></div>'
        for state, n in sorted(by_state.items())
    ]

    rows = []
    for r in records:
        state = str(r.state)
        narrative = (
            html.escape(r.narrative_md)
            if r.narrative_md
            else "(no narrative -- see rejection reason)"
        )
        rejection = (
            f"<p><strong>Rejection reason:</strong> {html.escape(r.rejection_reason)}</p>"
            if r.rejection_reason
            else ""
        )
        actions = "".join(
            f'<span class="badge">{html.escape(a)}</span>' for a in r.recommended_actions
        )
        classification = html.escape(str(r.classification)) if r.classification else "-"
        severity = html.escape(str(r.severity))
        rows.append(
            f'<div class="incident {html.escape(state)}">'
            f"<h2>{html.escape(r.event_id)} &middot; {html.escape(r.camera_id)}</h2>"
            f'<div class="row">{_fmt_ts(r.trigger_ts)} &middot; severity={severity} '
            f"&middot; state={html.escape(state)} &middot; classification={classification}</div>"
            f"<p>{narrative}</p>"
            f"{rejection}{actions}"
            f"</div>"
        )

    body = "".join(rows) if rows else '<p style="color:#94a3b8">No incidents in this window.</p>'
    meta = (
        f'<div class="meta">{_fmt_ts(from_ts)} &rarr; {_fmt_ts(to_ts)} '
        f"&middot; {len(records)} incident(s)</div>"
    )
    return (
        "<!doctype html><html><head><meta charset='utf-8'><title>Shift report</title>"
        f"{_STYLE}</head><body>"
        "<h1>SiteWatch AI &mdash; shift report</h1>"
        f"{meta}"
        f'<div class="kpis">{"".join(kpi_cards)}</div>'
        f"{body}"
        "</body></html>"
    )
