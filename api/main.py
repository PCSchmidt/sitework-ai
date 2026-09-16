"""FastAPI delivery plane - M0 stub.

M0 scope: /healthz plus placeholder /api/v1 routes so the compose stack boots and
the smoke path is exercisable. Real REST + WS surface lands in M4 (docs/06 sections 4-5).
"""

from __future__ import annotations

from fastapi import FastAPI

app = FastAPI(title="SiteWatch AI API", version="0.1.0")


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/v1/cameras")
def cameras() -> list[dict[str, str]]:
    return []  # M4: backed by Postgres + config


@app.get("/api/v1/incidents")
def incidents() -> list[dict[str, str]]:
    return []  # M4: paged incident list
