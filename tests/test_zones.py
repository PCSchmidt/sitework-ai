from __future__ import annotations

from pipelines.config.loader import Zone, ZonesConfig, load_zones
from pipelines.geometry.zones import ZoneEngine

SQUARE_M = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]
SQUARE = Zone(id="square", camera_id="cam1", polygon_m=SQUARE_M)
INACTIVE_SQUARE = Zone(
    id="inactive_square",
    camera_id="cam1",
    active=False,
    polygon_m=[(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)],
)


def test_point_inside_zone_is_detected() -> None:
    engine = ZoneEngine(ZonesConfig(zones=[SQUARE]))
    assert engine.zone_ids_containing("cam1", (5.0, 5.0)) == ["square"]


def test_point_outside_zone_is_not_detected() -> None:
    engine = ZoneEngine(ZonesConfig(zones=[SQUARE]))
    assert engine.zone_ids_containing("cam1", (20.0, 20.0)) == []


def test_inactive_zone_never_matches() -> None:
    engine = ZoneEngine(ZonesConfig(zones=[INACTIVE_SQUARE]))
    assert engine.zone_ids_containing("cam1", (5.0, 5.0)) == []


def test_zone_lookup_is_scoped_per_camera() -> None:
    other_cam = Zone(id="other", camera_id="cam2", polygon_m=SQUARE.polygon_m)
    engine = ZoneEngine(ZonesConfig(zones=[SQUARE, other_cam]))
    assert engine.zone_ids_containing("cam2", (5.0, 5.0)) == ["other"]
    assert "square" not in engine.zone_ids_containing("cam2", (5.0, 5.0))


def test_point_can_be_in_multiple_overlapping_zones() -> None:
    overlap_m = [(4.0, 4.0), (14.0, 4.0), (14.0, 14.0), (4.0, 14.0)]
    overlap = Zone(id="overlap", camera_id="cam1", polygon_m=overlap_m)
    engine = ZoneEngine(ZonesConfig(zones=[SQUARE, overlap]))
    assert set(engine.zone_ids_containing("cam1", (5.0, 5.0))) == {"square", "overlap"}


def test_real_zones_config_loads_and_compiles() -> None:
    zones_config = load_zones()
    engine = ZoneEngine(zones_config)
    # dock_north polygon_m spans x in [0, 20], y in [0, 12] on dock_north_01
    assert "dock_north" in engine.zone_ids_containing("dock_north_01", (10.0, 6.0))
