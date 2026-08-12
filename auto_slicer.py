#!/usr/bin/env python3
"""
auto_slicer.py — Geometry-driven Bambu Lab P1S Combo profile generator.

Analyzes an STL/OBJ mesh with trimesh/numpy/scipy and writes an optimized
Bambu Studio–style JSON profile (`optimized_p1s_profile.json` by default).

Usage:
    python auto_slicer.py input_model.stl
    python auto_slicer.py input_model.obj -o my_profile.json -v
    python auto_slicer.py --watch                    # daemon on ./auto_print_queue/
    python auto_slicer.py --watch --queue-dir ./inbox -v
"""

from __future__ import annotations

import argparse
import copy
import json
import logging
import math
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import numpy as np
import trimesh
from scipy import integrate, spatial

LOGGER = logging.getLogger("auto_slicer")

# ---------------------------------------------------------------------------
# Constants / thresholds
# ---------------------------------------------------------------------------

NEG_Z = np.array([0.0, 0.0, -1.0], dtype=np.float64)
OVERHANG_ANGLE_DEG = 45.0  # θ from -Z
BED_FLAT_ANGLE_DEG = 15.0  # exclude near-horizontal bed contact from "overhang"
OVERHANG_AREA_RATIO = 0.10
TALL_ASPECT_RATIO = 4.0
TOP_SECTION_Z_FRAC = 0.80  # analyze plane at 80% of Z height (top 20%)
NARROW_TOP_AREA_MM2 = 25.0  # "extremely narrow" top cross-section
LARGE_VOLUME_CM3 = 1500.0
LARGE_FLAT_BOTTOM_MM2 = 5000.0
HIGH_VERTEX_DENSITY = 8.0  # vertices per mm² of surface
HIGH_NORMAL_VARIANCE = 0.35  # mean adjacent normal disagreement (1 - |n_i·n_j|)

# Center-of-mass / tip-over stability
COG_Z_TOP_HEAVY = 0.68  # CoG above this fraction of height → top-heavy
COG_XY_SKEW = 0.28  # CoG XY offset / half-width → lateral imbalance
COG_TALL_Z_RATIO = 0.58  # lower threshold when aspect_ratio_z is high

# Mechanical hole detection (cross-section loops)
HOLE_SLICE_FRACTIONS = (0.25, 0.50, 0.75)
HOLE_MIN_DIAMETER_MM = 1.5
HOLE_MAX_DIAMETER_MM = 45.0
HOLE_MIN_CIRCULARITY = 0.55  # 4πA/P² ≈ 1 for a perfect circle
HOLE_COMPENSATION_MM = "0.15"

DEFAULT_QUEUE_DIR = Path("auto_print_queue")
SUPPORTED_MESH_SUFFIXES = {".stl", ".obj"}

P1S_BED_MM = (256.0, 256.0, 256.0)


# ---------------------------------------------------------------------------
# Data containers
# ---------------------------------------------------------------------------

@dataclass
class GeometryMetrics:
    """Extracted geometric features used by the rule engine."""

    filename: str
    is_watertight: bool
    was_repaired: bool
    triangle_count: int
    vertex_count: int
    surface_area_mm2: float
    volume_mm3: float
    volume_cm3: float
    bbox_min: np.ndarray
    bbox_max: np.ndarray
    extents_mm: np.ndarray  # [dx, dy, dz]
    aspect_ratio_z: float
    overhang_area_ratio: float
    overhang_area_mm2: float
    top_cross_section_mm2: float
    flat_bottom_area_mm2: float
    vertex_density: float  # vertices / mm²
    normal_variance: float
    fits_p1s_bed: bool
    center_of_mass: np.ndarray = field(default_factory=lambda: np.zeros(3))
    cog_z_ratio: float = 0.0  # 0=bed, 1=top
    cog_xy_offset_ratio: float = 0.0  # lateral skew vs bbox half-width
    tip_over_risk: bool = False
    hole_count: int = 0
    mechanical_hole_count: int = 0
    hole_diameters_mm: list[float] = field(default_factory=list)
    has_mechanical_holes: bool = False
    notes: list[str] = field(default_factory=list)

    @property
    def bbox_volume_mm3(self) -> float:
        return float(np.prod(self.extents_mm))


@dataclass
class RuleResult:
    name: str
    triggered: bool
    reason: str
    updates: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# GeometryAnalyzer
# ---------------------------------------------------------------------------

class GeometryAnalyzer:
    """
    Load, validate/repair, and extract quantitative features from a triangle mesh.

    All heavy math uses numpy vectorization; cross-sections use trimesh plane cuts;
    spatial adjacency for normal variance uses scipy.spatial when helpful.
    """

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.mesh: Optional[trimesh.Trimesh] = None
        self.was_repaired = False

    def load_and_validate(self) -> trimesh.Trimesh:
        LOGGER.info("Loading mesh: %s", self.path)
        if not self.path.exists():
            raise FileNotFoundError(f"Model not found: {self.path}")

        loaded = trimesh.load(self.path, force="mesh")
        if isinstance(loaded, trimesh.Scene):
            geoms = list(loaded.geometry.values())
            if not geoms:
                raise ValueError("Scene contains no geometry")
            loaded = trimesh.util.concatenate(geoms)

        if not isinstance(loaded, trimesh.Trimesh):
            raise ValueError(f"Unsupported mesh type: {type(loaded)}")

        self.mesh = loaded
        LOGGER.debug(
            "Loaded %d faces, %d vertices; watertight=%s",
            len(self.mesh.faces),
            len(self.mesh.vertices),
            self.mesh.is_watertight,
        )

        if not self.mesh.is_watertight:
            LOGGER.warning("Mesh is not watertight — attempting repair")
            self._repair()
        return self.mesh

    def _repair(self) -> None:
        assert self.mesh is not None
        before = self.mesh.is_watertight
        try:
            trimesh.repair.fix_normals(self.mesh)
            trimesh.repair.fill_holes(self.mesh)
            self.mesh.remove_duplicate_faces()
            self.mesh.remove_degenerate_faces()
            self.mesh.remove_unreferenced_vertices()
            self.mesh.process(validate=True)
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("Repair partially failed: %s", exc)

        self.was_repaired = True
        LOGGER.info(
            "Repair finished: watertight %s → %s",
            before,
            self.mesh.is_watertight,
        )

    def analyze(self) -> GeometryMetrics:
        if self.mesh is None:
            self.load_and_validate()
        assert self.mesh is not None
        mesh = self.mesh

        surface_area = float(mesh.area)
        # Prefer signed volume when watertight; else absolute convex approx fallback
        if mesh.is_watertight:
            volume = float(abs(mesh.volume))
        else:
            volume = float(abs(mesh.convex_hull.volume))
            LOGGER.warning("Using convex-hull volume (mesh still non-watertight)")

        extents = mesh.extents.astype(np.float64)
        bounds = mesh.bounds.astype(np.float64)
        dx, dy, dz = extents
        aspect = float(dz / max(dx, dy, 1e-9))

        overhang_area, overhang_ratio = self._overhang_metrics()
        top_area = self._top_cross_section_area()
        flat_bottom = self._flat_bottom_area()
        vertex_density = float(len(mesh.vertices) / max(surface_area, 1e-9))
        normal_var = self._adjacent_normal_variance()
        cog, cog_z_ratio, cog_xy_offset, tip_over = self._center_of_mass_analysis()
        hole_metrics = self._detect_cylindrical_holes()

        fits = bool(
            max(extents) <= max(P1S_BED_MM) + 0.05
            and all(
                sorted(extents, reverse=True)[i] <= sorted(P1S_BED_MM, reverse=True)[i] + 0.05
                for i in range(3)
            )
        )

        metrics = GeometryMetrics(
            filename=self.path.name,
            is_watertight=bool(mesh.is_watertight),
            was_repaired=self.was_repaired,
            triangle_count=int(len(mesh.faces)),
            vertex_count=int(len(mesh.vertices)),
            surface_area_mm2=surface_area,
            volume_mm3=volume,
            volume_cm3=volume / 1000.0,
            bbox_min=bounds[0],
            bbox_max=bounds[1],
            extents_mm=extents,
            aspect_ratio_z=aspect,
            overhang_area_ratio=overhang_ratio,
            overhang_area_mm2=overhang_area,
            top_cross_section_mm2=top_area,
            flat_bottom_area_mm2=flat_bottom,
            vertex_density=vertex_density,
            normal_variance=normal_var,
            fits_p1s_bed=fits,
            center_of_mass=cog,
            cog_z_ratio=cog_z_ratio,
            cog_xy_offset_ratio=cog_xy_offset,
            tip_over_risk=tip_over,
            hole_count=hole_metrics["hole_count"],
            mechanical_hole_count=hole_metrics["mechanical_hole_count"],
            hole_diameters_mm=hole_metrics["hole_diameters_mm"],
            has_mechanical_holes=hole_metrics["has_mechanical_holes"],
        )
        self._log_metrics(metrics)
        return metrics

    def _overhang_metrics(self) -> tuple[float, float]:
        """
        Overhang faces: angle θ between face normal and -Z satisfies
        BED_FLAT < θ < OVERHANG_ANGLE (default 15°–45°).

        Flat bed contact (θ ≈ 0°) is excluded so tables/cubes do not
        always trip the support rule. cos(θ) = n · (-Z).
        """
        assert self.mesh is not None
        normals = np.asarray(self.mesh.face_normals, dtype=np.float64)
        areas = np.asarray(self.mesh.area_faces, dtype=np.float64)
        dots = normals @ NEG_Z  # cos(θ)
        cos_overhang = math.cos(math.radians(OVERHANG_ANGLE_DEG))
        cos_bed = math.cos(math.radians(BED_FLAT_ANGLE_DEG))
        # θ < 45° ⇒ dots > cos45; θ > 15° ⇒ dots < cos15
        mask = (dots > cos_overhang) & (dots < cos_bed)
        overhang_area = float(areas[mask].sum()) if np.any(mask) else 0.0
        total = float(areas.sum()) or 1.0
        ratio = overhang_area / total
        LOGGER.debug(
            "Overhang faces=%d / %d, area=%.2f mm² (%.1f%%) "
            "[excluding bed-flat θ<%.0f°]",
            int(mask.sum()),
            len(mask),
            overhang_area,
            ratio * 100.0,
            BED_FLAT_ANGLE_DEG,
        )
        return overhang_area, ratio

    def _top_cross_section_area(self) -> float:
        """Intersect mesh with a horizontal plane in the top 20% of Z."""
        assert self.mesh is not None
        mesh = self.mesh
        z0, z1 = float(mesh.bounds[0][2]), float(mesh.bounds[1][2])
        height = z1 - z0
        if height < 1e-6:
            return 0.0
        z_plane = z0 + TOP_SECTION_Z_FRAC * height
        try:
            section = mesh.section(
                plane_origin=[0.0, 0.0, z_plane],
                plane_normal=[0.0, 0.0, 1.0],
            )
        except Exception as exc:  # noqa: BLE001
            LOGGER.debug("section() failed (%s); trying mesh_plane", exc)
            section = None

        if section is None:
            try:
                lines = trimesh.intersections.mesh_plane(
                    mesh,
                    plane_normal=np.array([0.0, 0.0, 1.0]),
                    plane_origin=np.array([0.0, 0.0, z_plane]),
                )
                if lines is None or len(lines) == 0:
                    return 0.0
                # Approximate area from 2D convex hull of intersection points
                pts = np.vstack(lines).reshape(-1, 3)[:, :2]
                if len(pts) < 3:
                    return 0.0
                hull = spatial.ConvexHull(pts)
                return float(hull.volume)  # 2D hull "volume" == area
            except Exception as exc:  # noqa: BLE001
                LOGGER.warning("Top cross-section failed: %s", exc)
                return 0.0

        try:
            planar, _ = section.to_planar()
            polys = planar.polygons_full
            if not polys:
                return 0.0
            return float(sum(p.area for p in polys))
        except Exception as exc:  # noqa: BLE001
            LOGGER.debug("to_planar failed (%s); using convex hull of path vertices", exc)
            try:
                pts = np.asarray(section.vertices)[:, :2]
                if len(pts) < 3:
                    return 0.0
                hull = spatial.ConvexHull(pts)
                return float(hull.volume)
            except Exception as exc2:  # noqa: BLE001
                LOGGER.warning("Top cross-section failed: %s", exc2)
                return 0.0

    def _flat_bottom_area(self) -> float:
        """Area of faces nearly aligned with -Z (print bed contact)."""
        assert self.mesh is not None
        normals = np.asarray(self.mesh.face_normals, dtype=np.float64)
        areas = np.asarray(self.mesh.area_faces, dtype=np.float64)
        # Flat bottom: n · -Z > cos(15°)
        mask = (normals @ NEG_Z) > math.cos(math.radians(15.0))
        return float(areas[mask].sum()) if np.any(mask) else 0.0

    def _adjacent_normal_variance(self) -> float:
        """
        Mean (1 - |n_i · n_j|) over mesh edges shared by two faces.
        High values ⇒ noisy / highly detailed surface micro-geometry.
        """
        assert self.mesh is not None
        mesh = self.mesh
        if len(mesh.faces) < 2:
            return 0.0
        try:
            # face adjacency edges: (n_faces, 2) pairs
            adj = mesh.face_adjacency
            if adj is None or len(adj) == 0:
                return 0.0
            n = np.asarray(mesh.face_normals, dtype=np.float64)
            dots = np.abs(np.sum(n[adj[:, 0]] * n[adj[:, 1]], axis=1))
            dots = np.clip(dots, 0.0, 1.0)
            return float(np.mean(1.0 - dots))
        except Exception as exc:  # noqa: BLE001
            LOGGER.debug("Normal variance fallback: %s", exc)
            # Fallback: sample random face pairs via KDTree on face centroids
            centroids = mesh.triangles_center
            tree = spatial.cKDTree(centroids)
            _, idx = tree.query(centroids, k=min(4, len(centroids)))
            n = np.asarray(mesh.face_normals, dtype=np.float64)
            pairs = []
            for i, neighbors in enumerate(idx):
                for j in neighbors[1:]:
                    pairs.append(1.0 - abs(float(np.dot(n[i], n[j]))))
            return float(np.mean(pairs)) if pairs else 0.0

    def _center_of_mass_analysis(self) -> tuple[np.ndarray, float, float, bool]:
        """
        Compute exact center of mass (CoG) via trimesh; validate Z distribution
        with scipy.integrate on horizontal slice areas. Flag tip-over risk when
        the CoG is top-heavy or skewed on the X/Y plane.
        """
        assert self.mesh is not None
        mesh = self.mesh
        bounds = mesh.bounds.astype(np.float64)
        z_min, z_max = float(bounds[0][2]), float(bounds[1][2])
        height = max(z_max - z_min, 1e-9)

        if mesh.is_watertight and mesh.volume > 1e-9:
            cog = np.asarray(mesh.center_mass, dtype=np.float64)
        else:
            cog = np.asarray(mesh.centroid, dtype=np.float64)
            LOGGER.warning("CoG from mesh centroid (non-watertight / zero volume)")

        cog_z_integrated = self._cog_z_from_slice_integration(bounds)
        if cog_z_integrated is not None:
            # Blend integrated Z with mesh CoG for robustness on noisy meshes
            cog[2] = 0.65 * float(cog[2]) + 0.35 * cog_z_integrated

        bbox_center = (bounds[0] + bounds[1]) * 0.5
        half_xy = max(float(mesh.extents[0]), float(mesh.extents[1])) * 0.5
        half_xy = max(half_xy, 1e-9)

        cog_z_ratio = float((cog[2] - z_min) / height)
        xy_delta = cog[:2] - bbox_center[:2]
        cog_xy_offset = float(np.linalg.norm(xy_delta) / half_xy)

        aspect = float(mesh.extents[2] / max(mesh.extents[0], mesh.extents[1], 1e-9))
        z_threshold = COG_TALL_Z_RATIO if aspect > TALL_ASPECT_RATIO else COG_Z_TOP_HEAVY
        top_heavy = cog_z_ratio > z_threshold
        xy_skewed = cog_xy_offset > COG_XY_SKEW
        tip_over = top_heavy or xy_skewed or (aspect > 3.0 and cog_z_ratio > 0.55)

        LOGGER.debug(
            "CoG=%s z_ratio=%.3f xy_offset=%.3f tip_over=%s",
            np.round(cog, 3),
            cog_z_ratio,
            cog_xy_offset,
            tip_over,
        )
        return cog, cog_z_ratio, cog_xy_offset, tip_over

    def _cog_z_from_slice_integration(self, bounds: np.ndarray) -> Optional[float]:
        """
        Estimate CoG Z by integrating cross-section area along height
        (uniform density assumption) using scipy.integrate.simpson.
        """
        assert self.mesh is not None
        mesh = self.mesh
        z_min, z_max = float(bounds[0][2]), float(bounds[1][2])
        height = z_max - z_min
        if height < 1e-6:
            return None

        n_slices = 25
        z_samples = np.linspace(z_min + height * 0.02, z_max - height * 0.02, n_slices)
        areas = np.zeros(n_slices, dtype=np.float64)
        for i, z_plane in enumerate(z_samples):
            areas[i] = self._section_area_at_z(z_plane)

        if float(np.sum(areas)) < 1e-9:
            return None

        mass_per_slice = areas  # uniform density ⇒ mass ∝ area
        cog_z = float(
            integrate.simpson(z_samples * mass_per_slice, x=z_samples)
            / integrate.simpson(mass_per_slice, x=z_samples)
        )
        return cog_z

    def _section_area_at_z(self, z_plane: float) -> float:
        """Total cross-section area at a horizontal plane (mm²)."""
        assert self.mesh is not None
        mesh = self.mesh
        try:
            section = mesh.section(
                plane_origin=[0.0, 0.0, z_plane],
                plane_normal=[0.0, 0.0, 1.0],
            )
        except Exception:  # noqa: BLE001
            section = None

        if section is None:
            return 0.0

        try:
            planar, _ = section.to_planar()
            polys = planar.polygons_full
            return float(sum(p.area for p in polys)) if polys else 0.0
        except Exception:  # noqa: BLE001
            try:
                pts = np.asarray(section.vertices)[:, :2]
                if len(pts) < 3:
                    return 0.0
                hull = spatial.ConvexHull(pts)
                return float(hull.volume)
            except Exception:  # noqa: BLE001
                return 0.0

    def _detect_cylindrical_holes(self) -> dict[str, Any]:
        """
        Detect cylindrical negative spaces (mechanical holes) by analyzing
        closed loops in horizontal mesh cross-sections at multiple Z heights.
        """
        assert self.mesh is not None
        mesh = self.mesh
        z_min, z_max = float(mesh.bounds[0][2]), float(mesh.bounds[1][2])
        height = z_max - z_min
        if height < 1e-6:
            return {
                "hole_count": 0,
                "mechanical_hole_count": 0,
                "hole_diameters_mm": [],
                "has_mechanical_holes": False,
            }

        all_holes: list[dict[str, float]] = []
        for frac in HOLE_SLICE_FRACTIONS:
            z_plane = z_min + frac * height
            loops = self._closed_loops_at_z(z_plane)
            if len(loops) <= 1:
                continue
            areas = [loop["area"] for loop in loops]
            outer_idx = int(np.argmax(areas))
            for idx, loop in enumerate(loops):
                if idx == outer_idx:
                    continue
                if not self._is_cylindrical_hole(loop):
                    continue
                all_holes.append(loop)

        # De-duplicate similar diameters across slices (same hole seen twice)
        diameters: list[float] = []
        for hole in all_holes:
            d = hole["diameter"]
            if not any(abs(d - existing) < 1.0 for existing in diameters):
                diameters.append(d)

        mechanical_count = len(diameters)
        LOGGER.debug(
            "Hole scan: %d loop hits, %d unique mechanical holes (d=%s)",
            len(all_holes),
            mechanical_count,
            [round(d, 2) for d in diameters],
        )
        return {
            "hole_count": len(all_holes),
            "mechanical_hole_count": mechanical_count,
            "hole_diameters_mm": diameters,
            "has_mechanical_holes": mechanical_count >= 1,
        }

    def _closed_loops_at_z(self, z_plane: float) -> list[dict[str, Any]]:
        """Return closed 2D loops from a horizontal section with area/perimeter."""
        assert self.mesh is not None
        mesh = self.mesh
        try:
            section = mesh.section(
                plane_origin=[0.0, 0.0, z_plane],
                plane_normal=[0.0, 0.0, 1.0],
            )
        except Exception:  # noqa: BLE001
            return []

        if section is None:
            return []

        loops: list[dict[str, Any]] = []
        try:
            paths = section.discrete
        except Exception:  # noqa: BLE001
            paths = []

        for path in paths:
            if len(path) < 4:
                continue
            pts2d = np.asarray(path)[:, :2]
            if not np.allclose(pts2d[0], pts2d[-1], atol=0.05):
                pts2d = np.vstack([pts2d, pts2d[0]])
            area = abs(self._polygon_area_2d(pts2d))
            perimeter = float(self._polyline_length_2d(pts2d))
            if area < 1e-3 or perimeter < 1e-3:
                continue
            loops.append(
                {
                    "area": area,
                    "perimeter": perimeter,
                    "diameter": perimeter / math.pi,
                }
            )
        return loops

    @staticmethod
    def _polygon_area_2d(pts: np.ndarray) -> float:
        x = pts[:, 0]
        y = pts[:, 1]
        return 0.5 * float(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1)))

    @staticmethod
    def _polyline_length_2d(pts: np.ndarray) -> float:
        seg = np.diff(pts, axis=0)
        return float(np.linalg.norm(seg, axis=1).sum())

    @staticmethod
    def _is_cylindrical_hole(loop: dict[str, Any]) -> bool:
        area = loop["area"]
        perimeter = loop["perimeter"]
        circularity = (4.0 * math.pi * area) / max(perimeter * perimeter, 1e-9)
        diameter = perimeter / math.pi
        return (
            circularity >= HOLE_MIN_CIRCULARITY
            and HOLE_MIN_DIAMETER_MM <= diameter <= HOLE_MAX_DIAMETER_MM
        )

    @staticmethod
    def _log_metrics(m: GeometryMetrics) -> None:
        LOGGER.info(
            "BBox extents: %.2f × %.2f × %.2f mm | volume: %.2f cm³ | "
            "area: %.1f mm² | aspect Z: %.2f",
            m.extents_mm[0],
            m.extents_mm[1],
            m.extents_mm[2],
            m.volume_cm3,
            m.surface_area_mm2,
            m.aspect_ratio_z,
        )
        LOGGER.info(
            "Overhang area: %.1f%% | top section: %.2f mm² | "
            "flat bottom: %.1f mm² | vertex density: %.3f /mm² | "
            "normal variance: %.3f | P1S fit: %s",
            m.overhang_area_ratio * 100.0,
            m.top_cross_section_mm2,
            m.flat_bottom_area_mm2,
            m.vertex_density,
            m.normal_variance,
            m.fits_p1s_bed,
        )
        LOGGER.info(
            "CoG z-ratio: %.3f | XY offset: %.3f | tip-over risk: %s | "
            "mechanical holes: %d (d=%s)",
            m.cog_z_ratio,
            m.cog_xy_offset_ratio,
            m.tip_over_risk,
            m.mechanical_hole_count,
            [round(d, 2) for d in m.hole_diameters_mm],
        )


# ---------------------------------------------------------------------------
# Rule engine
# ---------------------------------------------------------------------------

class RuleEngine:
    """Evaluate geometry metrics and produce Bambu Studio JSON key updates."""

    def evaluate(self, metrics: GeometryMetrics) -> list[RuleResult]:
        results = [
            self.rule_overhang(metrics),
            self.rule_thin_tall(metrics),
            self.rule_large_flat(metrics),
            self.rule_dense_detail(metrics),
            self.rule_stability(metrics),
            self.rule_hole_tolerance(metrics),
        ]
        for r in results:
            level = logging.INFO if r.triggered else logging.DEBUG
            LOGGER.log(level, "%s", r.reason)
        return results

    def rule_overhang(self, m: GeometryMetrics) -> RuleResult:
        triggered = m.overhang_area_ratio > OVERHANG_AREA_RATIO
        reason = (
            f"Overhang area calculated as {m.overhang_area_ratio * 100:.1f}% "
            f"(threshold {OVERHANG_AREA_RATIO * 100:.0f}%)"
        )
        if triggered:
            reason += " -> Triggering Overhang Rule"
            updates = {
                "cooling_fan_speed_max": "100",
                "fan_max_speed": ["100"],
                "outer_wall_speed": ["40"],
                "outer_wall_line_width": "0.45",
                "support_top_z_distance": "0.2",
                "support_type": "tree(auto)",
                "enable_support": "1",
            }
        else:
            reason += " -> Overhang Rule skipped"
            updates = {}
        return RuleResult("overhang_bridge", triggered, reason, updates)

    def rule_thin_tall(self, m: GeometryMetrics) -> RuleResult:
        narrow = m.top_cross_section_mm2 < NARROW_TOP_AREA_MM2
        triggered = m.aspect_ratio_z > TALL_ASPECT_RATIO and narrow
        reason = (
            f"Tall aspect ratio={m.aspect_ratio_z:.2f} "
            f"(need >{TALL_ASPECT_RATIO}), top cross-section="
            f"{m.top_cross_section_mm2:.2f} mm² (narrow <{NARROW_TOP_AREA_MM2})"
        )
        if triggered:
            reason += " -> Triggering Thin/Tall (Sword/Tower) Rule"
            updates = {
                "layer_height": "0.08",
                "fan_cooling_layer_time": ["8"],
                "default_acceleration": "2500",
                "outer_wall_acceleration": ["1000"],
            }
        else:
            reason += " -> Thin/Tall Rule skipped"
            updates = {}
        return RuleResult("thin_tall", triggered, reason, updates)

    def rule_large_flat(self, m: GeometryMetrics) -> RuleResult:
        triggered = (
            m.volume_cm3 > LARGE_VOLUME_CM3
            and m.flat_bottom_area_mm2 > LARGE_FLAT_BOTTOM_MM2
        )
        reason = (
            f"Volume={m.volume_cm3:.1f} cm³ (need >{LARGE_VOLUME_CM3}), "
            f"flat bottom={m.flat_bottom_area_mm2:.0f} mm² "
            f"(need >{LARGE_FLAT_BOTTOM_MM2})"
        )
        if triggered:
            reason += " -> Triggering Large/Flat Structural Rule"
            updates = {
                "layer_height": "0.28",
                "wall_loops": "5",
                "sparse_infill_pattern": "gyroid",
                "sparse_infill_density": "20%",
                "initial_layer_speed": "50",
                "outer_wall_speed": ["300"],
            }
        else:
            reason += " -> Large/Flat Rule skipped"
            updates = {}
        return RuleResult("large_flat", triggered, reason, updates)

    def rule_dense_detail(self, m: GeometryMetrics) -> RuleResult:
        # Primary signal is vertex density (fine embossing/text). Orthogonal
        # walls on coarse meshes inflate normal variance, so variance alone
        # must not trigger this rule.
        density_hit = m.vertex_density > HIGH_VERTEX_DENSITY
        variance_hit = m.normal_variance > HIGH_NORMAL_VARIANCE
        triggered = density_hit
        reason = (
            f"Vertex density={m.vertex_density:.3f}/mm² "
            f"(high >{HIGH_VERTEX_DENSITY}), "
            f"normal variance={m.normal_variance:.3f} "
            f"(info; high >{HIGH_NORMAL_VARIANCE})"
        )
        if variance_hit and density_hit:
            reason += " [variance also elevated]"
        if triggered:
            reason += " -> Triggering Dense Surface Detail Rule"
            updates = {
                "wall_generator": "arachne",
                "elephant_foot_compensation": "0.15",
                "bottom_surface_pattern": "monotonic line",
            }
        else:
            reason += " -> Dense Detail Rule skipped"
            updates = {}
        return RuleResult("dense_detail", triggered, reason, updates)

    def rule_stability(self, m: GeometryMetrics) -> RuleResult:
        triggered = m.tip_over_risk
        reason = (
            f"CoG z-ratio={m.cog_z_ratio:.3f} "
            f"(top-heavy >{COG_Z_TOP_HEAVY}), "
            f"XY offset={m.cog_xy_offset_ratio:.3f} "
            f"(skew >{COG_XY_SKEW}), aspect Z={m.aspect_ratio_z:.2f}"
        )
        if triggered:
            reason += " -> Triggering Center-of-Mass Stability Rule"
            updates = {
                "bottom_shell_layers": "8",
                "bottom_shell_thickness": "2.5",
            }
        else:
            reason += " -> Stability Rule skipped"
            updates = {}
        return RuleResult("center_of_mass_stability", triggered, reason, updates)

    def rule_hole_tolerance(self, m: GeometryMetrics) -> RuleResult:
        triggered = m.has_mechanical_holes
        diameters = ", ".join(f"{d:.1f}" for d in m.hole_diameters_mm[:6])
        if m.mechanical_hole_count > 6:
            diameters += ", ..."
        reason = (
            f"Mechanical holes detected: {m.mechanical_hole_count} "
            f"(loop hits={m.hole_count}"
            + (f", diameters mm: {diameters}" if diameters else "")
            + ")"
        )
        if triggered:
            reason += " -> Triggering Hole & Tolerance Compensation Rule"
            updates = {"xy_hole_compensation": HOLE_COMPENSATION_MM}
        else:
            reason += " -> Hole Tolerance Rule skipped"
            updates = {}
        return RuleResult("hole_tolerance", triggered, reason, updates)


# ---------------------------------------------------------------------------
# BambuProfileGenerator
# ---------------------------------------------------------------------------

class BambuProfileGenerator:
    """
    Maintain a baseline Bambu Studio process/filament JSON dict and apply
    rule-driven overrides. Values follow Studio's string / string-array style.
    """

    def __init__(self, baseline: Optional[dict[str, Any]] = None) -> None:
        self.profile: dict[str, Any] = copy.deepcopy(baseline or self.default_baseline())

    @staticmethod
    def default_baseline() -> dict[str, Any]:
        """Conservative P1S Combo starting profile (single filament)."""
        return {
            "printer_model": "Bambu Lab P1S",
            "printer_variant": "0.4 nozzle",
            "nozzle_diameter": ["0.4"],
            "layer_height": "0.20",
            "initial_layer_print_height": "0.20",
            "wall_loops": "3",
            "top_shell_layers": "5",
            "bottom_shell_layers": "3",
            "bottom_shell_thickness": "0.8",
            "xy_hole_compensation": "0",
            "sparse_infill_density": "15%",
            "sparse_infill_pattern": "grid",
            "wall_generator": "classic",
            "enable_support": "0",
            "support_type": "normal(auto)",
            "support_top_z_distance": "0.2",
            "brim_type": "auto_brim",
            "brim_width": "5",
            "elephant_foot_compensation": "0.1",
            "bottom_surface_pattern": "monotonic",
            "outer_wall_line_width": "0.42",
            "outer_wall_speed": ["150"],
            "inner_wall_speed": ["200"],
            "sparse_infill_speed": ["200"],
            "initial_layer_speed": "50",
            "default_acceleration": "5000",
            "outer_wall_acceleration": ["3000"],
            "fan_max_speed": ["80"],
            "fan_min_speed": ["60"],
            "fan_cooling_layer_time": ["10"],
            "cooling_fan_speed_max": "80",
            "nozzle_temperature": ["220"],
            "nozzle_temperature_initial_layer": ["220"],
            "filament_type": ["PLA"],
            "bed_temperature": ["60"],
            "textured_plate_temp": ["60"],
            "textured_plate_temp_initial_layer": ["60"],
            "from": "auto_slicer",
            "printer_notes": "Generated for Bambu Lab P1S Combo by auto_slicer.py",
        }

    def apply_rules(self, results: list[RuleResult]) -> dict[str, Any]:
        triggered = [r for r in results if r.triggered]
        LOGGER.info("%d / %d rules triggered", len(triggered), len(results))
        for r in triggered:
            LOGGER.info("Applying updates from rule '%s': %s", r.name, list(r.updates))
            self.profile.update(r.updates)
        # Conflict policy: if both thin-tall (0.08) and large-flat (0.28) somehow
        # fire, prefer the more conservative (thinner) layer for safety.
        layers = [
            r.updates.get("layer_height")
            for r in triggered
            if "layer_height" in r.updates
        ]
        if layers:
            try:
                chosen = min(float(x) for x in layers if x is not None)
                self.profile["layer_height"] = f"{chosen:.2f}"
            except ValueError:
                pass
        return self.profile

    def attach_metadata(self, metrics: GeometryMetrics, results: list[RuleResult]) -> None:
        self.profile["_auto_slicer_meta"] = {
            "source_file": metrics.filename,
            "is_watertight": metrics.is_watertight,
            "was_repaired": metrics.was_repaired,
            "volume_cm3": round(metrics.volume_cm3, 3),
            "extents_mm": [round(float(x), 3) for x in metrics.extents_mm],
            "overhang_area_percent": round(metrics.overhang_area_ratio * 100.0, 2),
            "aspect_ratio_z": round(metrics.aspect_ratio_z, 3),
            "top_cross_section_mm2": round(metrics.top_cross_section_mm2, 3),
            "vertex_density": round(metrics.vertex_density, 4),
            "normal_variance": round(metrics.normal_variance, 4),
            "fits_p1s_bed": metrics.fits_p1s_bed,
            "center_of_mass_mm": [round(float(x), 3) for x in metrics.center_of_mass],
            "cog_z_ratio": round(metrics.cog_z_ratio, 4),
            "cog_xy_offset_ratio": round(metrics.cog_xy_offset_ratio, 4),
            "tip_over_risk": metrics.tip_over_risk,
            "mechanical_hole_count": metrics.mechanical_hole_count,
            "hole_diameters_mm": [round(d, 2) for d in metrics.hole_diameters_mm],
            "triggered_rules": [r.name for r in results if r.triggered],
        }

    def save(self, path: Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.profile, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        LOGGER.info("Wrote profile: %s", path.resolve())
        return path


# ---------------------------------------------------------------------------
# Background queue watchdog
# ---------------------------------------------------------------------------

class AutoPrintQueueWatcher:
    """
    Monitor a directory for new STL/OBJ drops and run the full analysis
    pipeline automatically (no manual CLI invocation per file).
    """

    def __init__(
        self,
        queue_dir: Path,
        output_dir: Optional[Path] = None,
        baseline_path: Optional[Path] = None,
        settle_seconds: float = 1.5,
    ) -> None:
        self.queue_dir = Path(queue_dir)
        self.output_dir = Path(output_dir) if output_dir else self.queue_dir
        self.baseline_path = baseline_path
        self.settle_seconds = settle_seconds
        self._observer: Any = None
        self._processing: set[str] = set()

    def ensure_queue_dir(self) -> Path:
        self.queue_dir.mkdir(parents=True, exist_ok=True)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        return self.queue_dir

    def process_file(self, model_path: Path) -> Optional[Path]:
        """Run GeometryAnalyzer + RuleEngine + profile export for one model."""
        model_path = Path(model_path)
        key = str(model_path.resolve())
        if key in self._processing:
            LOGGER.debug("Already processing: %s", model_path.name)
            return None

        suffix = model_path.suffix.lower()
        if suffix not in SUPPORTED_MESH_SUFFIXES:
            LOGGER.debug("Ignoring non-mesh file: %s", model_path.name)
            return None

        if not model_path.is_file():
            return None

        self._processing.add(key)
        try:
            time.sleep(self.settle_seconds)
            if not model_path.is_file():
                return None

            out_name = f"{model_path.stem}_optimized_p1s_profile.json"
            output_path = self.output_dir / out_name
            LOGGER.info("Queue: processing %s → %s", model_path.name, output_path.name)
            return generate_profile(model_path, output_path, self.baseline_path)
        except Exception as exc:  # noqa: BLE001
            LOGGER.exception("Queue failed for %s: %s", model_path.name, exc)
            return None
        finally:
            self._processing.discard(key)

    def scan_existing(self) -> list[Path]:
        """Process any mesh files already present in the queue directory."""
        written: list[Path] = []
        for pattern in ("*.stl", "*.STL", "*.obj", "*.OBJ"):
            for path in sorted(self.queue_dir.glob(pattern)):
                result = self.process_file(path)
                if result is not None:
                    written.append(result)
        return written

    def start(self, block: bool = True) -> None:
        try:
            from watchdog.events import FileSystemEventHandler
            from watchdog.observers import Observer
        except ImportError as exc:
            raise ImportError(
                "watchdog is required for --watch mode. "
                "Install with: pip install watchdog"
            ) from exc

        self.ensure_queue_dir()
        watcher = self

        class _QueueHandler(FileSystemEventHandler):
            def on_created(self, event: Any) -> None:
                if getattr(event, "is_directory", False):
                    return
                watcher.process_file(Path(event.src_path))

            def on_moved(self, event: Any) -> None:
                if getattr(event, "is_directory", False):
                    return
                dest = getattr(event, "dest_path", None)
                if dest:
                    watcher.process_file(Path(dest))

        handler = _QueueHandler()
        self._observer = Observer()
        self._observer.schedule(handler, str(self.queue_dir.resolve()), recursive=False)
        self._observer.start()
        LOGGER.info("Watching %s for new .stl / .obj files", self.queue_dir.resolve())

        existing = self.scan_existing()
        if existing:
            LOGGER.info("Processed %d existing queue file(s)", len(existing))

        if block:
            try:
                while True:
                    time.sleep(1.0)
            except KeyboardInterrupt:
                LOGGER.info("Watchdog stopped by user")
                self.stop()

    def stop(self) -> None:
        if self._observer is not None:
            self._observer.stop()
            self._observer.join(timeout=5.0)
            self._observer = None


# ---------------------------------------------------------------------------
# Orchestration + CLI
# ---------------------------------------------------------------------------

def generate_profile(model_path: Path, output_path: Path, baseline_path: Optional[Path] = None) -> Path:
    analyzer = GeometryAnalyzer(model_path)
    analyzer.load_and_validate()
    metrics = analyzer.analyze()

    if not metrics.fits_p1s_bed:
        LOGGER.warning(
            "Model may not fit P1S bed %s mm (extents %s)",
            P1S_BED_MM,
            tuple(np.round(metrics.extents_mm, 2)),
        )

    engine = RuleEngine()
    results = engine.evaluate(metrics)

    baseline = None
    if baseline_path:
        baseline = json.loads(Path(baseline_path).read_text(encoding="utf-8"))
        LOGGER.info("Loaded baseline profile: %s", baseline_path)

    generator = BambuProfileGenerator(baseline=baseline)
    generator.apply_rules(results)
    generator.attach_metadata(metrics, results)
    return generator.save(output_path)


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=(
            "Analyze an STL/OBJ and generate an optimized Bambu Lab P1S Combo "
            "Studio JSON profile via geometric rule engine."
        )
    )
    p.add_argument(
        "model",
        type=Path,
        nargs="?",
        default=None,
        help="Input .stl or .obj mesh (omit when using --watch)",
    )
    p.add_argument(
        "-o",
        "--output",
        type=Path,
        default=Path("optimized_p1s_profile.json"),
        help="Output JSON path (default: optimized_p1s_profile.json)",
    )
    p.add_argument(
        "-b",
        "--baseline",
        type=Path,
        default=None,
        help="Optional baseline Bambu Studio JSON to patch instead of built-in defaults",
    )
    p.add_argument(
        "--watch",
        action="store_true",
        help="Run background daemon watching for new meshes in --queue-dir",
    )
    p.add_argument(
        "--queue-dir",
        type=Path,
        default=DEFAULT_QUEUE_DIR,
        help=f"Directory to watch for auto-processing (default: {DEFAULT_QUEUE_DIR})",
    )
    p.add_argument(
        "--queue-output",
        type=Path,
        default=None,
        help="Output directory for profiles in --watch mode (default: same as --queue-dir)",
    )
    p.add_argument("-v", "--verbose", action="store_true", help="DEBUG logging")
    return p


def main(argv: Optional[list[str]] = None) -> int:
    args = build_arg_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s | %(levelname)-7s | %(message)s",
        datefmt="%H:%M:%S",
    )

    if args.watch:
        watcher = AutoPrintQueueWatcher(
            queue_dir=args.queue_dir,
            output_dir=args.queue_output,
            baseline_path=args.baseline,
        )
        try:
            watcher.start(block=True)
        except ImportError as exc:
            LOGGER.error("%s", exc)
            return 2
        except Exception as exc:  # noqa: BLE001
            LOGGER.exception("Watchdog failed: %s", exc)
            return 1
        return 0

    if args.model is None:
        LOGGER.error("Provide a model path or use --watch for daemon mode")
        return 2

    suffix = args.model.suffix.lower()
    if suffix not in SUPPORTED_MESH_SUFFIXES:
        LOGGER.error("Only .stl / .obj supported (got %s)", suffix)
        return 2

    try:
        out = generate_profile(args.model, args.output, args.baseline)
    except Exception as exc:  # noqa: BLE001
        LOGGER.exception("Failed: %s", exc)
        return 1

    print(f"OK → {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
