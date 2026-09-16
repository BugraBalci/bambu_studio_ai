"""Overhang area, clustering, and Bambu support-type classification.

A face is an overhang when its normal is within OVERHANG_ANGLE_DEG of -Z,
excluding near-horizontal bed contact (θ < BED_FLAT_ANGLE_DEG).

    cos(θ) = n · (-Z) = -n_z

Physically: n_z < -cos(45°)  ⇔  n · (-Z) > cos(45°).
Bed-flat faces (n ≈ -Z) are not printable overhangs.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import trimesh

from slicer_pipeline.constants import (
    BED_FLAT_ANGLE_DEG,
    NEG_Z,
    OVERHANG_ANGLE_DEG,
    PLANAR_OVERHANG_ANGLE_DEG,
    SUPPORT_AREA_RATIO,
    SUPPORT_CLUSTER_CELL_MM,
    SUPPORT_TYPE_NONE,
    SUPPORT_TYPE_NORMAL,
    SUPPORT_TYPE_TREE,
)


@dataclass(frozen=True)
class OverhangSupportAnalysis:
    overhang_area_mm2: float
    overhang_area_ratio: float
    overhang_face_count: int
    cluster_count: int
    planar_area_ratio: float
    support_required: bool
    recommended_support_type: str
    support_reason: str
    overhang_note: str


def _face_centroids(mesh: trimesh.Trimesh) -> np.ndarray:
    centers = getattr(mesh, "triangles_center", None)
    if centers is not None and len(centers) == len(mesh.faces):
        return np.asarray(centers, dtype=np.float64)
    tris = np.asarray(mesh.triangles, dtype=np.float64)
    return tris.mean(axis=1)


def _count_spatial_clusters(centroids: np.ndarray, cell_mm: float) -> int:
    """Connected components of occupied voxel cells (26-neighborhood)."""
    if centroids.size == 0:
        return 0
    keys = np.floor(centroids / max(cell_mm, 1e-6)).astype(np.int64)
    occupied = {tuple(int(v) for v in row) for row in keys}
    seen: set[tuple[int, int, int]] = set()
    clusters = 0
    neighbors = [
        (dx, dy, dz)
        for dx in (-1, 0, 1)
        for dy in (-1, 0, 1)
        for dz in (-1, 0, 1)
        if not (dx == 0 and dy == 0 and dz == 0)
    ]
    for start in occupied:
        if start in seen:
            continue
        clusters += 1
        stack = [start]
        seen.add(start)
        while stack:
            x, y, z = stack.pop()
            for dx, dy, dz in neighbors:
                nxt = (x + dx, y + dy, z + dz)
                if nxt in occupied and nxt not in seen:
                    seen.add(nxt)
                    stack.append(nxt)
    return clusters


def _classify_support_type(
    *,
    support_required: bool,
    ratio: float,
    cluster_count: int,
    planar_frac: float,
) -> tuple[str, str]:
    pct = ratio * 100.0
    if not support_required:
        return (
            SUPPORT_TYPE_NONE,
            (
                f"Support kapalı: 45° altı overhang alanı %{pct:.1f} "
                f"(eşik %{SUPPORT_AREA_RATIO * 100:.0f}). Tabla teması sayılmadı; "
                f"köprüler soğutma ile tutulabilir."
            ),
        )

    # Isolated / organic patches (limbs, chins) → tree. Wide planar undersides → grid/normal.
    organic = cluster_count >= 4 or planar_frac < 0.40
    if not organic and planar_frac >= 0.50 and cluster_count <= 3:
        return (
            SUPPORT_TYPE_NORMAL,
            (
                f"Support açık (%{pct:.1f} overhang): {cluster_count} geniş küme, "
                f"düz/köprü alt yüzey oranı %{planar_frac * 100:.0f}. "
                f"Bambu Studio tipi: grid / normal(auto)."
            ),
        )
    return (
        SUPPORT_TYPE_TREE,
        (
            f"Support açık (%{pct:.1f} overhang): {cluster_count} dağınık/organik küme, "
            f"düz alt yüzey %{planar_frac * 100:.0f}. "
            f"Bambu Studio tipi: tree(auto) — ince uzantılara daha az iz bırakır."
        ),
    )


def analyze_overhang_support(
    mesh: trimesh.Trimesh,
    *,
    area_ratio_threshold: float = SUPPORT_AREA_RATIO,
) -> OverhangSupportAnalysis:
    """Vectorized overhang test + tree vs normal(auto) recommendation."""
    empty = OverhangSupportAnalysis(
        overhang_area_mm2=0.0,
        overhang_area_ratio=0.0,
        overhang_face_count=0,
        cluster_count=0,
        planar_area_ratio=0.0,
        support_required=False,
        recommended_support_type=SUPPORT_TYPE_NONE,
        support_reason=(
            "Support kapalı: ölçülebilir alt yüzey yok (boş veya geçersiz mesh)."
        ),
        overhang_note="",
    )
    if mesh is None or len(getattr(mesh, "faces", [])) == 0:
        return empty

    normals = np.asarray(mesh.face_normals, dtype=np.float64)
    areas = np.asarray(mesh.area_faces, dtype=np.float64)
    if normals.size == 0 or areas.size == 0:
        return empty

    dots = normals @ NEG_Z
    cos_overhang = math.cos(math.radians(OVERHANG_ANGLE_DEG))
    cos_bed = math.cos(math.radians(BED_FLAT_ANGLE_DEG))
    cos_planar = math.cos(math.radians(PLANAR_OVERHANG_ANGLE_DEG))
    # θ from -Z in (bed_flat, overhang_angle] → printable overhang, not bed.
    mask = (dots > cos_overhang) & (dots < cos_bed)
    overhang_area = float(areas[mask].sum()) if np.any(mask) else 0.0
    total = float(areas.sum()) or 1.0
    ratio = overhang_area / total
    face_count = int(np.count_nonzero(mask))

    planar_mask = mask & (dots >= cos_planar)
    planar_area = float(areas[planar_mask].sum()) if np.any(planar_mask) else 0.0
    planar_frac = (planar_area / overhang_area) if overhang_area > 1e-9 else 0.0

    cluster_count = 0
    if face_count:
        centers = _face_centroids(mesh)[mask]
        cluster_count = _count_spatial_clusters(centers, SUPPORT_CLUSTER_CELL_MM)

    support_required = ratio > area_ratio_threshold and face_count > 0
    support_type, support_reason = _classify_support_type(
        support_required=support_required,
        ratio=ratio,
        cluster_count=cluster_count,
        planar_frac=planar_frac,
    )

    overhang_note = ""
    if support_required:
        overhang_note = (
            f"Eğimli alt yüzey (45°) oranı ~%{ratio * 100:.0f}; "
            f"{support_type} support önerilir."
        )
    elif ratio > 0.01:
        overhang_note = (
            f"Hafif overhang (~%{ratio * 100:.0f}) eşiğin altında; support kapalı."
        )

    return OverhangSupportAnalysis(
        overhang_area_mm2=round(overhang_area, 2),
        overhang_area_ratio=round(ratio, 4),
        overhang_face_count=face_count,
        cluster_count=cluster_count,
        planar_area_ratio=round(planar_frac, 3),
        support_required=support_required,
        recommended_support_type=support_type,
        support_reason=support_reason,
        overhang_note=overhang_note,
    )
