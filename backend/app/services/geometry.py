"""STL geometry analysis via trimesh."""

from __future__ import annotations

import uuid
from pathlib import Path

import numpy as np
import trimesh

from app.schemas import P2S_BED_MM, GeometryMetrics


def analyze_stl(path: Path, original_filename: str, file_id: str | None = None) -> GeometryMetrics:
    mesh = trimesh.load(path, force="mesh")
    if isinstance(mesh, trimesh.Scene):
        mesh = trimesh.util.concatenate(tuple(mesh.geometry.values()))

    if not isinstance(mesh, trimesh.Trimesh):
        raise ValueError("Could not parse STL as a triangle mesh")

    extents = mesh.extents.astype(float)  # mm if STL is in mm
    volume = float(mesh.volume) if mesh.is_volume else float(abs(mesh.volume))
    volume_cm3 = abs(volume) / 1000.0
    surface_cm2 = float(mesh.area) / 100.0

    sorted_ext = sorted(extents.tolist())
    aspect = (sorted_ext[-1] / sorted_ext[0]) if sorted_ext[0] > 1e-6 else 1.0

    min_dim = float(sorted_ext[0])
    thin = min_dim < 2.0 or (aspect > 8 and min_dim < 4.0)
    thin_note = ""
    if thin:
        thin_note = (
            f"En ince boyut ~{min_dim:.1f} mm; ince duvarlar için 0.4 mm nozzle "
            "veya daha fazla duvar önerilir."
        )

    overhang_risk = False
    overhang_note = ""
    if len(mesh.faces) > 0:
        normals = mesh.face_normals
        areas = mesh.area_faces
        angled_down = (normals[:, 2] < -0.35) & (normals[:, 2] > -0.98)
        down_area = float(areas[angled_down].sum()) if np.any(angled_down) else 0.0
        total = float(areas.sum()) or 1.0
        ratio = down_area / total
        if ratio > 0.05:
            overhang_risk = True
            overhang_note = (
                f"Eğimli alt yüzey oranı ~%{ratio * 100:.0f}; support gerekebilir."
            )

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

    return GeometryMetrics(
        filename=original_filename,
        file_id=file_id or uuid.uuid4().hex,
        triangle_count=int(len(mesh.faces)),
        bounding_box_mm=[round(float(x), 2) for x in extents],
        volume_cm3=round(volume_cm3, 3),
        surface_area_cm2=round(surface_cm2, 3),
        is_watertight=bool(mesh.is_watertight),
        aspect_ratio=round(float(aspect), 2),
        thin_feature_hint=thin,
        thin_feature_note=thin_note,
        overhang_risk_hint=overhang_risk,
        overhang_note=overhang_note,
        fits_p2s_bed=fits,
        bed_fit_note=bed_fit_note,
        printer_bed_mm=bed,
    )
