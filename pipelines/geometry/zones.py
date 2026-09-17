"""Zone polygon engine (docs/04 §4, docs/12 M2): ground-plane containment.

Zone polygons are defined once in meters (config/zones.yaml, loaded via
pipelines.config.loader) and precomputed as Shapely polygons at construction;
per-track membership is a point-in-polygon test against a track's projected
ground point.
"""

from __future__ import annotations

from dataclasses import dataclass

from shapely.geometry import Point as ShapelyPoint
from shapely.geometry import Polygon

from pipelines.config.loader import Zone, ZonesConfig


@dataclass(frozen=True)
class _CompiledZone:
    zone: Zone
    polygon: Polygon


class ZoneEngine:
    """Precomputed per-camera zone polygons for fast containment checks."""

    def __init__(self, zones_config: ZonesConfig) -> None:
        self._by_camera: dict[str, list[_CompiledZone]] = {}
        for zone in zones_config.zones:
            polygon = Polygon(zone.polygon_m)
            self._by_camera.setdefault(zone.camera_id, []).append(_CompiledZone(zone, polygon))

    def zones_for_camera(self, camera_id: str) -> list[Zone]:
        return [cz.zone for cz in self._by_camera.get(camera_id, [])]

    def zone_ids_containing(self, camera_id: str, ground_point_m: tuple[float, float]) -> list[str]:
        """Zone ids (active only) whose polygon contains the given ground point."""
        point = ShapelyPoint(ground_point_m)
        return [
            cz.zone.id
            for cz in self._by_camera.get(camera_id, [])
            if cz.zone.active and cz.polygon.contains(point)
        ]
