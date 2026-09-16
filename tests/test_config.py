"""Fail-fast config validation tests (docs/06 §7)."""

from __future__ import annotations

import pytest
from pipelines.config.loader import load_cameras, load_rules, load_shifts, load_zones


def test_cameras_load() -> None:
    cfg = load_cameras()
    assert len(cfg.cameras) >= 3


def test_zones_load() -> None:
    cfg = load_zones()
    assert all(len(z.polygon_m) >= 3 for z in cfg.zones)


def test_rules_reference_known_zones() -> None:
    zone_ids = {z.id for z in load_zones().zones}
    for rule in load_rules().rules:
        unknown = set(rule.zone_ids) - zone_ids
        assert not unknown, f"rule {rule.id} references unknown zones: {unknown}"


def test_rule_params_match_kind() -> None:
    # loader raises on a proximity rule missing radius/duration
    with pytest.raises(ValueError, match="missing params"):
        load_rules("test_bad_rule.yaml")


def test_shifts_load() -> None:
    cfg = load_shifts()
    assert len(cfg.shifts) == 3
