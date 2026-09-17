"""Mesh geometry analysis via trimesh (STL / OBJ / GLB / GLTF / 3MF).

Meshy `.3mf` exports keep native color and multi-body separation. This module
loads the assembly without flattening; analysis runs on the combined mesh.
"""

from __future__ import annotations

import logging
import sys
import uuid
from collections import Counter
from pathlib import Path

import numpy as np

from app.schemas import P2S_BED_MM, DetailTier, DetectedColor, GeometryMetrics
from app.services.filament_compat import detected_colors_from_hexes

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from slicer_pipeline.constants import SUPPORTED_MESH_SUFFIXES  # noqa: E402
from slicer_pipeline.defects import (  # noqa: E402
    FINE_TEXT_EXPLANATION_TR,
    HULL_LINE_EXPLANATION_TR,
    miniature_brim_width_mm,
    miniature_explanation_tr,
)
from slicer_pipeline.geometry import GeometryAnalyzer  # noqa: E402
from slicer_pipeline.mesh_parser import MeshParser  # noqa: E402
from slicer_pipeline.text_engine import analyze_target_surface  # noqa: E402

LOGGER = logging.getLogger(__name__)

# triangles per cm² of surface — heuristic mesh density bands
DETAIL_LOW_MAX = 80.0
DETAIL_MEDIUM_MAX = 250.0


def colors_from_assembly(assembly) -> list[DetectedColor]:
    palette = list(assembly.materials or [])
    counts: Counter[str] = Counter()
    for part in assembly.parts:
        hex_color = getattr(part, "color_hex", None)
        if not hex_color:
            continue
        counts[hex_color] += 1
        if hex_color not in palette:
            palette.append(hex_color)
    return detected_colors_from_hexes(palette, dict(counts))


def extract_detected_colors(path: Path) -> list[DetectedColor]:
    assembly = MeshParser().parse(path)
    return colors_from_assembly(assembly)


def _detail_tier(triangles_per_cm2: float, thin: bool) -> tuple[DetailTier, str]:
    if triangles_per_cm2 < DETAIL_LOW_MAX:
        tier = DetailTier.low
        note = (
            f"Yüzey sade (~{triangles_per_cm2:.1f} üçgen/cm²) — detay az, daha hızlı basılabilir."
        )
    elif triangles_per_cm2 < DETAIL_MEDIUM_MAX:
        tier = DetailTier.medium
        note = (
            f"Orta detay (~{triangles_per_cm2:.1f} üçgen/cm²) — dengeli hız önerilir."
        )
    else:
        tier = DetailTier.high
        note = (
            f"Yoğun mesh (~{triangles_per_cm2:.1f} üçgen/cm²) — ince katman ve daha yavaş dış duvar."
        )

    if thin and tier == DetailTier.low:
        tier = DetailTier.medium
        note += " İnce bölgeler var; hız orta banda çekildi."
    return tier, note


def analyze_mesh(path: Path, original_filename: str, file_id: str | None = None) -> GeometryMetrics:
    assembly = MeshParser().parse(path)
    analyzer = GeometryAnalyzer(assembly)
    full = analyzer.analyze()
    mesh = analyzer.mesh
    assert mesh is not None

    extents = np.asarray(full.extents_mm, dtype=float)
    volume_cm3 = abs(full.volume_cm3)
    surface_cm2 = float(mesh.area) / 100.0

    sorted_ext = sorted(extents.tolist())
    aspect = (sorted_ext[-1] / sorted_ext[0]) if sorted_ext[0] > 1e-6 else 1.0

    min_dim = float(sorted_ext[0])
    thin = min_dim < 2.0 or (aspect > 8 and min_dim < 4.0)
    if full.hull_line_risk and full.hull_line_shell_thickness_mm < 2.0:
        thin = True
    thin_note = ""
    if thin:
        thin_note = (
            f"En ince boyut ~{min_dim:.1f} mm; ince duvarlar için 0.4 mm nozzle "
            "veya daha fazla duvar önerilir."
        )
    if full.hull_line_risk:
        thin_note = (
            f"{thin_note} " if thin_note else ""
        ) + (
            f"Hull Line: iç taban-duvar birleşiminde kabuk "
            f"~{full.hull_line_shell_thickness_mm:.1f} mm."
        ).strip()

    from slicer_pipeline.support import analyze_overhang_support

    support = analyzer._support_analysis or analyze_overhang_support(mesh)
    overhang_risk = support.support_required
    overhang_note = support.overhang_note

    bed = list(P2S_BED_MM)
    fits = max(extents) <= max(bed) + 0.05 and all(
        sorted(extents, reverse=True)[i] <= sorted(bed, reverse=True)[i] + 0.05 for i in range(3)
    )
    if fits:
        bed_fit_note = (
            f"Model P2S Combo tablasına sığar (tabla {bed[0]:.0f}×{bed[1]:.0f}×{bed[2]:.0f} mm)."
        )
    else:
        bed_fit_note = (
            f"Dikkat: model {extents[0]:.1f}×{extents[1]:.1f}×{extents[2]:.1f} mm; "
            f"P2S Combo tabla limiti {bed[0]:.0f}×{bed[1]:.0f}×{bed[2]:.0f} mm — "
            "bölmen veya küçültmen gerekebilir."
        )

    triangle_count = int(len(mesh.faces))
    vertex_count = int(len(mesh.vertices))
    triangles_per_cm2 = triangle_count / surface_cm2 if surface_cm2 > 1e-6 else float(triangle_count)
    detail_tier, detail_note = _detail_tier(triangles_per_cm2, thin)

    colors = colors_from_assembly(assembly)
    extra_note = ""
    if len(assembly.parts) > 1 or len(colors) > 1:
        extra_note = (
            f" {len(assembly.parts)} gövde / {len(colors)} renk korundu."
        )

    try:
        surface = analyze_target_surface(mesh)
        surface_kind = surface.kind
        wrap_recommended = bool(surface.wrap_recommended)
        surface_note = surface.note
        cylinder_radius = float(surface.cylinder_radius)
    except Exception as exc:  # noqa: BLE001
        surface_kind = "planar"
        wrap_recommended = False
        surface_note = ""
        cylinder_radius = 0.0
        LOGGER.debug("Surface classification skipped: %s", exc)

    return GeometryMetrics(
        filename=original_filename,
        file_id=file_id or uuid.uuid4().hex,
        triangle_count=triangle_count,
        vertex_count=vertex_count,
        bounding_box_mm=[round(float(x), 2) for x in extents],
        volume_cm3=round(volume_cm3, 3),
        surface_area_cm2=round(surface_cm2, 3),
        is_watertight=bool(mesh.is_watertight),
        aspect_ratio=round(float(aspect), 2),
        thin_feature_hint=thin,
        thin_feature_note=thin_note,
        overhang_risk_hint=overhang_risk,
        overhang_note=overhang_note,
        support_required=support.support_required,
        recommended_support_type=support.recommended_support_type,
        support_reason=support.support_reason,
        overhang_area_ratio=support.overhang_area_ratio,
        fits_p2s_bed=fits,
        bed_fit_note=bed_fit_note + extra_note,
        printer_bed_mm=bed,
        triangles_per_cm2=round(triangles_per_cm2, 1),
        detail_tier=detail_tier,
        detail_note=detail_note,
        part_count=len(assembly.parts),
        color_count=max(len(colors), 1),
        colors=colors,
        hull_line_risk=bool(full.hull_line_risk),
        hull_line_shell_thickness_mm=round(full.hull_line_shell_thickness_mm, 3),
        hull_line_z_mm=[round(z, 2) for z in full.hull_line_z_mm],
        hull_line_note=full.hull_line_note,
        hull_line_explanation=HULL_LINE_EXPLANATION_TR if full.hull_line_risk else "",
        fine_text_detected=bool(full.fine_text_detected),
        fine_stroke_width_mm=round(full.fine_stroke_width_mm, 3),
        fine_text_on_skin=bool(full.fine_text_on_skin),
        fine_text_note=full.fine_text_note,
        fine_text_explanation=FINE_TEXT_EXPLANATION_TR if full.fine_text_detected else "",
        is_miniature=bool(full.is_miniature),
        obb_extents_mm=[round(float(x), 2) for x in full.obb_extents_mm],
        miniature_explanation=(
            miniature_explanation_tr(miniature_brim_width_mm(extents))
            if full.is_miniature
            else ""
        ),
        target_surface_kind=surface_kind,
        wrap_recommended=wrap_recommended,
        target_surface_note=surface_note,
        cylinder_radius_mm=round(cylinder_radius, 2),
    )
