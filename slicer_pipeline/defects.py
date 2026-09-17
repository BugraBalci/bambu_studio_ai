"""Print-defect detectors and the Bambu Studio keys they inject.

Two geometry-driven mitigations:

* Hull Line — a visible bulge where an internal solid floor meets a thin outer
  shell. Thermal shrinkage / layer-time / extrusion volume all jump at that Z.
* Fine text / micro-detail — letter strokes thinner than a classic 0.42 mm line
  get dropped unless Arachne (variable line width) is used.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

import numpy as np

from slicer_pipeline.constants import (
    FINE_STROKE_LIMIT_MM,
    HIGH_NORMAL_VARIANCE,
    HIGH_VERTEX_DENSITY,
    HULL_LINE_THICKNESS_LIMIT_MM,
    MINIATURE_BBOX_VOLUME_MM3,
    MINIATURE_BRIM_TYPE,
    MINIATURE_BRIM_WIDTH_MM,
    MINIATURE_LAYER_HEIGHT_MM,
    MINIATURE_MAX_EXTENT_MM,
    MINIATURE_OUTER_WALL_LINE_WIDTH_MM,
    MINIATURE_OUTER_WALL_SPEED_MM_S,
    MINIATURE_VOLUME_MAX_EXTENT_MM,
)

LoopsAtZ = Callable[[float], list[dict[str, Any]]]

HULL_LINE_EXPLANATION_TR = (
    "Hull Line riski tespit edildi: Taban-duvar birleşimi ince kaldığı için "
    "duvar sayısı artırıldı veya Fuzzy Skin önerildi."
)
FINE_TEXT_EXPLANATION_TR = (
    "İnce yazı veya mikro detay tespit edildi: Harf kırılmalarını önlemek için "
    "Arachne duvar motoru ve 0.3 mm hat genişliği aktif edildi."
)
MINIATURE_EXPLANATION_TR = (
    "Minyatür Model Optimizasyonu Devrede: Model boyutu küçük olduğu için "
    "katman 0.12 mm'ye, dış duvar genişliği 0.35 mm'ye ve hızı 35 mm/s'ye çekildi; "
    "alt yüzey tahribatını önlemek için destekler kapatıldı ve tabladan kalkmayı "
    "önlemek için 7 mm iç/dış kenar (brim) eklendi."
)

# Studio fuzzy-skin camouflage (Option B) — recommended, not always applied.
FUZZY_SKIN_RECOMMENDED = {
    "fuzzy_skin": "contour",
    "fuzzy_skin_point_distance": "0.8",
    "fuzzy_skin_thickness": "0.1",
}

DEFAULT_LINE_WIDTH_MM = 0.42
FINE_TEXT_LINE_WIDTH_MM = 0.3
FINE_TEXT_LAYER_HEIGHT_MM = 0.12
TARGET_SHELL_THICKNESS_MM = 2.0


@dataclass
class HullLineReport:
    risk: bool = False
    shell_thickness_mm: float = 0.0
    junction_z_mm: list[float] = field(default_factory=list)
    floor_area_mm2: float = 0.0
    notes: str = ""


@dataclass
class FineTextReport:
    detected: bool = False
    min_stroke_width_mm: float = 0.0
    stroke_count: int = 0
    on_first_or_top_layer: bool = False
    notes: str = ""


def walls_for_shell_thickness(
    line_width_mm: float = DEFAULT_LINE_WIDTH_MM,
    target_mm: float = TARGET_SHELL_THICKNESS_MM,
) -> int:
    """Smallest wall_loops whose extruded width exceeds `target_mm` (clamped 4–8)."""
    width = max(float(line_width_mm), 0.12)
    needed = int(math.ceil(target_mm / width - 1e-9))
    return max(4, min(8, needed))


def hull_line_profile_updates(
    line_width_mm: float = DEFAULT_LINE_WIDTH_MM,
    apply_fuzzy_skin: bool = False,
) -> dict[str, Any]:
    """Option A (walls) always; Option B (fuzzy skin) only when selected."""
    updates: dict[str, Any] = {
        "wall_loops": str(walls_for_shell_thickness(line_width_mm)),
    }
    if apply_fuzzy_skin:
        updates.update(FUZZY_SKIN_RECOMMENDED)
    return updates


def is_miniature_extents(extents_mm: Any) -> bool:
    """True when the oriented bbox is a micro/miniature print.

    Primary: longest side ≤ 35 mm. Fallback: bbox volume ≤ 35³ mm³ and the
    longest side still ≤ 38 mm (catches slightly elongated figurines without
    flagging 50 mm+ plates or long rods).
    """
    dims = np.abs(np.asarray(extents_mm, dtype=np.float64).reshape(-1))
    if dims.size == 0 or not np.all(np.isfinite(dims)):
        return False
    longest = float(np.max(dims))
    volume = float(np.prod(dims))
    return longest <= MINIATURE_MAX_EXTENT_MM or (
        volume <= MINIATURE_BBOX_VOLUME_MM3 and longest <= MINIATURE_VOLUME_MAX_EXTENT_MM
    )


def miniature_brim_width_mm(extents_mm: Any) -> int:
    """5–10 mm brim from as-placed XY footprint; default 7 mm for typical miniatures."""
    dims = np.abs(np.asarray(extents_mm, dtype=np.float64).reshape(-1))
    if dims.size < 2 or not np.all(np.isfinite(dims)):
        return MINIATURE_BRIM_WIDTH_MM
    xy = dims[:2] if dims.size >= 3 else dims
    span = float(np.min(xy))
    if span <= 10.0:
        return 10
    if span >= 32.0:
        return 5
    return MINIATURE_BRIM_WIDTH_MM


def miniature_explanation_tr(brim_width_mm: int = MINIATURE_BRIM_WIDTH_MM) -> str:
    if int(brim_width_mm) == MINIATURE_BRIM_WIDTH_MM:
        return MINIATURE_EXPLANATION_TR
    return MINIATURE_EXPLANATION_TR.replace(
        f"{MINIATURE_BRIM_WIDTH_MM} mm iç/dış kenar",
        f"{int(brim_width_mm)} mm iç/dış kenar",
    )


def miniature_profile_updates(extents_mm: Any = None) -> dict[str, Any]:
    brim = miniature_brim_width_mm(extents_mm) if extents_mm is not None else MINIATURE_BRIM_WIDTH_MM
    return {
        "layer_height": f"{MINIATURE_LAYER_HEIGHT_MM:.2f}",
        "outer_wall_line_width": f"{MINIATURE_OUTER_WALL_LINE_WIDTH_MM:.2f}",
        "outer_wall_speed": str(MINIATURE_OUTER_WALL_SPEED_MM_S),
        "enable_support": "0",
        "brim_type": MINIATURE_BRIM_TYPE,
        "brim_width": str(brim),
        "_explanation_tr": miniature_explanation_tr(brim),
    }


def fine_text_profile_updates(on_first_or_top_layer: bool = True) -> dict[str, Any]:
    width = f"{FINE_TEXT_LINE_WIDTH_MM:.1f}"
    updates: dict[str, Any] = {
        "wall_generator": "arachne",
        "layer_height": f"{FINE_TEXT_LAYER_HEIGHT_MM:.2f}",
        "line_width": width,
        "outer_wall_line_width": width,
    }
    if on_first_or_top_layer:
        updates["initial_layer_line_width"] = width
    return updates


def detect_hull_line(mesh, loops_at_z: LoopsAtZ) -> HullLineReport:
    """Flag a floor→thin-shell junction whose outer wall is under 2.0 mm."""
    bounds = np.asarray(mesh.bounds, dtype=np.float64)
    z_min, z_max = float(bounds[0][2]), float(bounds[1][2])
    height = z_max - z_min
    if height < 3.0:
        return HullLineReport(notes="too short for an internal floor")

    floors = _internal_horizontal_surfaces(mesh)
    candidates: list[tuple[float, float, float]] = []  # z, thickness, floor_area

    for z_floor, floor_area in floors[:8]:
        thickness = _thinnest_shell_around(loops_at_z, z_floor, z_min, z_max)
        if thickness is None:
            continue
        if 0.25 <= thickness < HULL_LINE_THICKNESS_LIMIT_MM:
            candidates.append((z_floor, thickness, floor_area))

    if not candidates:
        jump = _area_jump_thin_shell(loops_at_z, z_min, z_max, height)
        if jump is not None:
            candidates.append(jump)

    if not candidates:
        return HullLineReport(notes="no thin floor-wall junction")

    candidates.sort(key=lambda item: item[1])
    z_hit, thickness, floor_area = candidates[0]
    zs = sorted({round(z, 2) for z, _, _ in candidates})
    return HullLineReport(
        risk=True,
        shell_thickness_mm=float(thickness),
        junction_z_mm=zs,
        floor_area_mm2=float(floor_area),
        notes=(
            f"internal floor {floor_area:.0f} mm² at z≈{z_hit:.1f} mm, "
            f"shell {thickness:.2f} mm (<{HULL_LINE_THICKNESS_LIMIT_MM:.1f} mm)"
        ),
    )


def detect_fine_text(
    mesh,
    vertex_density: float = 0.0,
    normal_variance: float = 0.0,
) -> FineTextReport:
    """Detect letter-like strokes / micro ridges narrower than ~0.45 mm."""
    widths: list[float] = []
    widths.extend(_thin_component_extents(mesh))
    island_widths, on_skin = _embossed_island_widths(mesh)
    widths.extend(island_widths)
    widths.extend(_ribbon_widths_from_small_faces(mesh))

    short_ratio = _short_edge_ratio(mesh)
    dense = vertex_density > HIGH_VERTEX_DENSITY
    noisy = normal_variance > HIGH_NORMAL_VARIANCE

    fine = [w for w in widths if 0.08 <= w < FINE_STROKE_LIMIT_MM]
    # A noisy high-poly surface with a large share of sub-nozzle edges is also
    # a micro-detail case even if island clustering did not fire.
    heuristic = short_ratio >= 0.18 and (dense or noisy) and len(mesh.faces) >= 400

    if not fine and not heuristic:
        return FineTextReport(
            notes=(
                f"no sub-{FINE_STROKE_LIMIT_MM:.2f} mm strokes "
                f"(short-edge ratio={short_ratio:.2f})"
            )
        )

    min_w = float(min(fine)) if fine else FINE_STROKE_LIMIT_MM * 0.7
    count = len(fine) if fine else max(1, int(short_ratio * 10))
    return FineTextReport(
        detected=True,
        min_stroke_width_mm=min_w,
        stroke_count=count,
        on_first_or_top_layer=on_skin,
        notes=(
            f"min stroke {min_w:.2f} mm, {count} island(s), "
            f"short-edge ratio={short_ratio:.2f}"
        ),
    )


def _internal_horizontal_surfaces(mesh) -> list[tuple[float, float]]:
    """Cluster near-horizontal faces that are not the bed or the very top skin."""
    normals = np.asarray(mesh.face_normals, dtype=np.float64)
    areas = np.asarray(mesh.area_faces, dtype=np.float64)
    centroids = np.asarray(mesh.triangles_center, dtype=np.float64)
    if len(areas) == 0:
        return []

    z = centroids[:, 2]
    z_min, z_max = float(mesh.bounds[0][2]), float(mesh.bounds[1][2])
    height = max(z_max - z_min, 1e-9)
    margin = max(0.8, min(2.2, height * 0.04))

    horiz = np.abs(normals[:, 2]) >= math.cos(math.radians(12.0))
    internal = horiz & (z > z_min + margin) & (z < z_max - 0.35)
    if not np.any(internal):
        return []

    bins = np.round(z[internal] / 0.4) * 0.4
    clusters: dict[float, float] = {}
    for b, area in zip(bins, areas[internal]):
        key = float(b)
        clusters[key] = clusters.get(key, 0.0) + float(area)

    xy_area = float(mesh.extents[0] * mesh.extents[1])
    min_area = max(35.0, 0.05 * xy_area)
    floors = [(z_lvl, area) for z_lvl, area in clusters.items() if area >= min_area]
    floors.sort(key=lambda item: item[1], reverse=True)
    return floors


def _thinnest_shell_around(
    loops_at_z: LoopsAtZ,
    z_floor: float,
    z_min: float,
    z_max: float,
) -> Optional[float]:
    samples = []
    for delta in (-0.8, -0.45, 0.45, 0.8, 1.2):
        z = z_floor + delta
        if z <= z_min + 0.15 or z >= z_max - 0.15:
            continue
        thickness = shell_thickness_from_loops(loops_at_z(z))
        if thickness is not None:
            samples.append(thickness)
    if not samples:
        return None
    return float(min(samples))


def _area_jump_thin_shell(
    loops_at_z: LoopsAtZ,
    z_min: float,
    z_max: float,
    height: float,
) -> Optional[tuple[float, float, float]]:
    """Fallback: sudden cross-section fill change next to a thin ring."""
    n = int(min(28, max(10, height / 1.1)))
    zs = np.linspace(z_min + height * 0.08, z_max - height * 0.06, n)
    prev_area = None
    prev_z = None
    best: Optional[tuple[float, float, float]] = None
    for z in zs:
        loops = loops_at_z(float(z))
        area = float(sum(loop["area"] for loop in loops)) if loops else 0.0
        thickness = shell_thickness_from_loops(loops)
        if (
            prev_area is not None
            and prev_area > 20.0
            and area > 20.0
            and max(area, prev_area) / max(min(area, prev_area), 1e-9) >= 1.7
            and thickness is not None
            and 0.25 <= thickness < HULL_LINE_THICKNESS_LIMIT_MM
        ):
            floor_area = max(area, prev_area)
            z_hit = float(z if area > prev_area else prev_z)
            cand = (z_hit, float(thickness), float(floor_area))
            if best is None or cand[1] < best[1]:
                best = cand
        prev_area, prev_z = area, float(z)
    return best


def shell_thickness_from_loops(loops: list[dict[str, Any]]) -> Optional[float]:
    """Estimate outer-wall thickness (mm) from a horizontal section's loops.

    Prefer radial ray sampling from the section centroid: a hollow shell yields
    two hits per ray (inner then outer). Trimesh `section.discrete` without
    shapely often returns broken/duplicated contours, so area-based pairing of
    "outer vs inner" loops is only a fallback.
    """
    if not loops:
        return None

    radial = _radial_shell_thickness(loops)
    if radial is not None:
        return radial
    if len(loops) == 1:
        return None

    ordered = sorted(loops, key=lambda loop: loop["area"], reverse=True)
    outer, inner = ordered[0], ordered[1]
    if inner["area"] > 0.12 * outer["area"] and outer["area"] - inner["area"] > 8.0:
        wall_area = outer["area"] - inner["area"]
        mid_perim = 0.5 * (outer["perimeter"] + inner["perimeter"])
        thickness = float(wall_area / max(mid_perim, 1e-9))
        return thickness if thickness >= 0.2 else None

    widths = []
    for loop in loops:
        perim = float(loop["perimeter"])
        if perim < 1e-6:
            continue
        widths.append(2.0 * float(loop["area"]) / perim)
    if not widths:
        return None
    thickness = float(min(widths))
    return thickness if 0.2 <= thickness < 12.0 else None


def _radial_shell_thickness(loops: list[dict[str, Any]], rays: int = 48) -> Optional[float]:
    segments: list[tuple[np.ndarray, np.ndarray]] = []
    points: list[np.ndarray] = []
    for loop in loops:
        raw = loop.get("points")
        if raw is None:
            continue
        pts = np.asarray(raw, dtype=np.float64)
        if pts.ndim != 2 or len(pts) < 2:
            continue
        pts2 = pts[:, :2]
        points.append(pts2)
        for i in range(len(pts2) - 1):
            if np.linalg.norm(pts2[i + 1] - pts2[i]) < 1e-6:
                continue
            segments.append((pts2[i], pts2[i + 1]))
        if not np.allclose(pts2[0], pts2[-1], atol=0.05):
            segments.append((pts2[-1], pts2[0]))
    if len(segments) < 3 or not points:
        return None

    cloud = np.vstack(points)
    center = 0.5 * (cloud.min(axis=0) + cloud.max(axis=0))
    widths: list[float] = []
    multi = 0
    for k in range(rays):
        ang = (2.0 * math.pi * k) / rays
        direction = np.array([math.cos(ang), math.sin(ang)], dtype=np.float64)
        hits = _ray_segment_hits(center, direction, segments)
        if len(hits) >= 2:
            multi += 1
            width = hits[1] - hits[0]
            if 0.15 <= width <= 12.0:
                widths.append(width)
    if multi < max(6, rays // 6) or not widths:
        return None
    return float(np.median(widths))


def _ray_segment_hits(
    origin: np.ndarray,
    direction: np.ndarray,
    segments: list[tuple[np.ndarray, np.ndarray]],
) -> list[float]:
    hits: list[float] = []
    for a, b in segments:
        delta = b - a
        denom = direction[0] * delta[1] - direction[1] * delta[0]
        if abs(denom) < 1e-12:
            continue
        rel = a - origin
        t = (rel[0] * delta[1] - rel[1] * delta[0]) / denom
        u = (rel[0] * direction[1] - rel[1] * direction[0]) / denom
        if t > 1e-4 and -1e-6 <= u <= 1.0 + 1e-6:
            hits.append(float(t))
    if not hits:
        return []
    hits.sort()
    merged = [hits[0]]
    for dist in hits[1:]:
        if dist - merged[-1] >= 0.12:
            merged.append(dist)
    return merged


def _thin_component_extents(mesh) -> list[float]:
    """Min AABB edge of disconnected bodies — catches concatenated letter strokes."""
    widths: list[float] = []
    try:
        parts = mesh.split(only_watertight=False)
    except Exception:  # noqa: BLE001
        parts = [mesh]
    if len(parts) <= 1:
        return widths
    for part in parts:
        if len(part.faces) < 4:
            continue
        min_e = float(np.min(part.extents))
        if 0.08 <= min_e < FINE_STROKE_LIMIT_MM and float(part.area) >= 0.8:
            widths.append(min_e)
    return widths


def _embossed_island_widths(mesh) -> tuple[list[float], bool]:
    """Raised/recessed islands on +Z/−Z skins (typical embossed/engraved text)."""
    normals = np.asarray(mesh.face_normals, dtype=np.float64)
    areas = np.asarray(mesh.area_faces, dtype=np.float64)
    centroids = np.asarray(mesh.triangles_center, dtype=np.float64)
    if len(areas) == 0:
        return [], False

    z_min, z_max = float(mesh.bounds[0][2]), float(mesh.bounds[1][2])
    height = max(z_max - z_min, 1e-9)
    widths: list[float] = []
    on_skin = False

    for sign in (1.0, -1.0):
        align = (sign * normals[:, 2]) >= 0.92
        if int(np.count_nonzero(align)) < 8:
            continue
        zs = centroids[align, 2]
        z_med = float(np.median(zs))
        high = zs > (z_med + 0.12)
        low = zs < (z_med - 0.12)
        align_idx = np.where(align)[0]
        for mask in (high, low):
            if int(np.count_nonzero(mask)) < 3:
                continue
            face_idx = align_idx[mask]
            island_area = float(areas[face_idx].sum())
            if island_area < 0.4 or island_area > 0.45 * float(areas[align].sum() + 1e-9):
                continue
            for component in _connected_face_groups(mesh, face_idx):
                width = _component_ribbon_width(mesh, component)
                if width is None:
                    continue
                if 0.08 <= width < 3.0:
                    widths.append(width)
                z_c = float(np.mean(centroids[component, 2]))
                if z_c <= z_min + 0.35 * height or z_c >= z_max - 0.35 * height:
                    on_skin = True

    return widths, on_skin


def _ribbon_widths_from_small_faces(mesh) -> list[float]:
    areas = np.asarray(mesh.area_faces, dtype=np.float64)
    if len(areas) < 20:
        return []
    small = np.where(areas < 0.35)[0]
    if len(small) < 12:
        return []
    widths: list[float] = []
    for component in _connected_face_groups(mesh, small):
        if len(component) < 6:
            continue
        area = float(areas[component].sum())
        if area < 0.5 or area > 80.0:
            continue
        width = _component_ribbon_width(mesh, component)
        if width is not None and 0.08 <= width < FINE_STROKE_LIMIT_MM:
            widths.append(width)
    return widths


def _short_edge_ratio(mesh) -> float:
    try:
        lengths = np.asarray(mesh.edges_unique_length, dtype=np.float64)
    except Exception:  # noqa: BLE001
        return 0.0
    if len(lengths) == 0:
        return 0.0
    return float(np.mean((lengths >= 0.10) & (lengths < FINE_STROKE_LIMIT_MM)))


def _connected_face_groups(mesh, face_indices: np.ndarray) -> list[list[int]]:
    wanted = {int(i) for i in np.asarray(face_indices).tolist()}
    if not wanted:
        return []
    parent = {i: i for i in wanted}

    def find(a: int) -> int:
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    try:
        adj = mesh.face_adjacency
    except Exception:  # noqa: BLE001
        adj = np.empty((0, 2), dtype=np.int64)
    for a, b in adj:
        ia, ib = int(a), int(b)
        if ia in wanted and ib in wanted:
            pa, pb = find(ia), find(ib)
            if pa != pb:
                parent[pa] = pb

    groups: dict[int, list[int]] = {}
    for i in wanted:
        groups.setdefault(find(i), []).append(i)
    return list(groups.values())


def _component_ribbon_width(mesh, faces: list[int]) -> Optional[float]:
    if not faces:
        return None
    area = float(np.asarray(mesh.area_faces)[faces].sum())
    tri = np.asarray(mesh.faces)[faces]
    edges = np.sort(tri[:, [[0, 1], [1, 2], [2, 0]]].reshape(-1, 2), axis=1)
    uniq, counts = np.unique(edges, axis=0, return_counts=True)
    border = uniq[counts == 1]
    if len(border) == 0:
        return None
    verts = np.asarray(mesh.vertices, dtype=np.float64)
    peri = float(np.linalg.norm(verts[border[:, 0]] - verts[border[:, 1]], axis=1).sum())
    if peri < 1e-6:
        return None
    return 2.0 * area / peri
