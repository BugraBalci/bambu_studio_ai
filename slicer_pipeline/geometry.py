"""Load, repair, and extract quantitative features from a mesh assembly."""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, Union

import numpy as np
import trimesh
from scipy import integrate, spatial

from slicer_pipeline.constants import (
    BED_FLAT_ANGLE_DEG,
    COG_TALL_Z_RATIO,
    COG_XY_SKEW,
    COG_Z_TOP_HEAVY,
    HOLE_MAX_DIAMETER_MM,
    HOLE_MIN_CIRCULARITY,
    HOLE_MIN_DIAMETER_MM,
    HOLE_SLICE_FRACTIONS,
    NEG_Z,
    OVERHANG_ANGLE_DEG,
    P2S_BED_MM,
    TALL_ASPECT_RATIO,
    TOP_SECTION_Z_FRAC,
)
from slicer_pipeline.mesh_parser import MeshAssembly, MeshParser

LOGGER = logging.getLogger("auto_slicer")

SourceType = Union[Path, str, MeshAssembly, trimesh.Trimesh]


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
    fits_p2s_bed: bool
    center_of_mass: np.ndarray = field(default_factory=lambda: np.zeros(3))
    cog_z_ratio: float = 0.0  # 0=bed, 1=top
    cog_xy_offset_ratio: float = 0.0  # lateral skew vs bbox half-width
    tip_over_risk: bool = False
    hole_count: int = 0
    mechanical_hole_count: int = 0
    hole_diameters_mm: list[float] = field(default_factory=list)
    has_mechanical_holes: bool = False
    part_count: int = 1
    color_count: int = 1
    notes: list[str] = field(default_factory=list)
    support_required: bool = False
    recommended_support_type: str = "none"
    support_reason: str = ""
    overhang_cluster_count: int = 0
    planar_overhang_ratio: float = 0.0

    @property
    def fits_p1s_bed(self) -> bool:
        return self.fits_p2s_bed

    @property
    def bbox_volume_mm3(self) -> float:
        return float(np.prod(self.extents_mm))


class GeometryAnalyzer:
    """
    Load, validate/repair, and extract quantitative features from a triangle mesh.

    All heavy math uses numpy vectorization; cross-sections use trimesh plane cuts;
    spatial adjacency for normal variance uses scipy.spatial when helpful.

    Analysis always runs on the *combined* assembly so overhang / CoM / density
    reflect the printable object, while MeshAssembly keeps sub-meshes intact.
    """

    def __init__(self, source: SourceType) -> None:
        self.assembly: Optional[MeshAssembly] = None
        self.mesh: Optional[trimesh.Trimesh] = None
        self.was_repaired = False
        self._support_analysis = None
        if isinstance(source, MeshAssembly):
            self.assembly = source
            self.path = Path(source.source_path)
        elif isinstance(source, trimesh.Trimesh):
            self.path = Path("mesh")
            self.mesh = source
        else:
            self.path = Path(source)

    def load_and_validate(self) -> trimesh.Trimesh:
        if self.mesh is not None:
            return self.mesh
        LOGGER.info("Loading mesh: %s", self.path)
        if self.assembly is None:
            if not self.path.exists():
                raise FileNotFoundError(f"Model not found: {self.path}")
            self.assembly = MeshParser().parse(self.path)
        self.mesh = self.assembly.combined_mesh()
        LOGGER.debug(
            "Loaded %d faces, %d vertices, %d parts; watertight=%s",
            len(self.mesh.faces),
            len(self.mesh.vertices),
            len(self.assembly.parts) if self.assembly else 1,
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
        volume = self._volume_mm3(mesh)
        extents = mesh.extents.astype(np.float64)
        bounds = mesh.bounds.astype(np.float64)
        dx, dy, dz = extents
        aspect = float(dz / max(dx, dy, 1e-9))

        overhang_area, overhang_ratio = self._overhang_metrics()
        support = self._support_analysis
        top_area = self._top_cross_section_area()
        flat_bottom = self._flat_bottom_area()
        vertex_density = float(len(mesh.vertices) / max(surface_area, 1e-9))
        normal_var = self._adjacent_normal_variance()
        cog, cog_z_ratio, cog_xy_offset, tip_over = self._center_of_mass_analysis()
        hole_metrics = self._detect_cylindrical_holes()

        fits = bool(
            max(extents) <= max(P2S_BED_MM) + 0.05
            and all(
                sorted(extents, reverse=True)[i] <= sorted(P2S_BED_MM, reverse=True)[i] + 0.05
                for i in range(3)
            )
        )

        part_count = len(self.assembly.parts) if self.assembly else 1
        color_count = len(self.assembly.materials) if self.assembly else 1

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
            fits_p2s_bed=fits,
            center_of_mass=cog,
            cog_z_ratio=cog_z_ratio,
            cog_xy_offset_ratio=cog_xy_offset,
            tip_over_risk=tip_over,
            hole_count=hole_metrics["hole_count"],
            mechanical_hole_count=hole_metrics["mechanical_hole_count"],
            hole_diameters_mm=hole_metrics["hole_diameters_mm"],
            has_mechanical_holes=hole_metrics["has_mechanical_holes"],
            part_count=part_count,
            color_count=color_count,
            support_required=bool(support.support_required) if support else False,
            recommended_support_type=(
                support.recommended_support_type if support else "none"
            ),
            support_reason=support.support_reason if support else "",
            overhang_cluster_count=support.cluster_count if support else 0,
            planar_overhang_ratio=support.planar_area_ratio if support else 0.0,
        )
        self._log_metrics(metrics)
        return metrics

    def _volume_mm3(self, mesh: trimesh.Trimesh) -> float:
        if self.assembly and len(self.assembly.parts) > 1:
            total = 0.0
            any_ok = False
            for part in self.assembly.parts:
                m = part.world_mesh()
                try:
                    if m.is_watertight:
                        total += float(abs(m.volume))
                        any_ok = True
                    elif len(m.faces) > 0:
                        total += float(abs(m.convex_hull.volume))
                        any_ok = True
                except Exception:  # noqa: BLE001
                    continue
            if any_ok and total > 0.0:
                return total
        if mesh.is_watertight:
            return float(abs(mesh.volume))
        LOGGER.warning("Using convex-hull volume (mesh still non-watertight)")
        return float(abs(mesh.convex_hull.volume))

    def _overhang_metrics(self) -> tuple[float, float]:
        """45° overhang test + tree vs normal(auto) classification."""
        from slicer_pipeline.support import analyze_overhang_support

        assert self.mesh is not None
        analysis = analyze_overhang_support(self.mesh)
        self._support_analysis = analysis
        LOGGER.debug(
            "Overhang area=%.2f mm² (%.1f%%) clusters=%d planar=%.0f%% type=%s",
            analysis.overhang_area_mm2,
            analysis.overhang_area_ratio * 100.0,
            analysis.cluster_count,
            analysis.planar_area_ratio * 100.0,
            analysis.recommended_support_type,
        )
        return analysis.overhang_area_mm2, analysis.overhang_area_ratio

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
                pts = np.vstack(lines).reshape(-1, 3)[:, :2]
                if len(pts) < 3:
                    return 0.0
                hull = spatial.ConvexHull(pts)
                return float(hull.volume)
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
            adj = mesh.face_adjacency
            if adj is None or len(adj) == 0:
                return 0.0
            n = np.asarray(mesh.face_normals, dtype=np.float64)
            dots = np.abs(np.sum(n[adj[:, 0]] * n[adj[:, 1]], axis=1))
            dots = np.clip(dots, 0.0, 1.0)
            return float(np.mean(1.0 - dots))
        except Exception as exc:  # noqa: BLE001
            LOGGER.debug("Normal variance fallback: %s", exc)
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

        mass_per_slice = areas
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
            "area: %.1f mm² | aspect Z: %.2f | parts: %d | colors: %d",
            m.extents_mm[0],
            m.extents_mm[1],
            m.extents_mm[2],
            m.volume_cm3,
            m.surface_area_mm2,
            m.aspect_ratio_z,
            m.part_count,
            m.color_count,
        )
        LOGGER.info(
            "Overhang area: %.1f%% | top section: %.2f mm² | "
            "flat bottom: %.1f mm² | vertex density: %.3f /mm² | "
            "normal variance: %.3f | P2S fit: %s",
            m.overhang_area_ratio * 100.0,
            m.top_cross_section_mm2,
            m.flat_bottom_area_mm2,
            m.vertex_density,
            m.normal_variance,
            m.fits_p2s_bed,
        )
        LOGGER.info(
            "Support: required=%s type=%s clusters=%d reason=%s",
            m.support_required,
            m.recommended_support_type,
            m.overhang_cluster_count,
            m.support_reason,
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
