"""Resolve user text controls onto a TextSpec and recommendation extras."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Optional

from app.schemas import PrintRecommendation, TextCustomization, TextPreviewResponse
from app.services.filament_compat import (
    display_hex,
    hex_from_color_name,
    text_filament_slot,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from slicer_pipeline.defects import FINE_TEXT_LINE_WIDTH_MM  # noqa: E402
from slicer_pipeline.mesh_parser import MeshParser  # noqa: E402
from slicer_pipeline.text_engine import (  # noqa: E402
    DEFAULT_TEXT_COLOR,
    EMBOSS_EXPLANATION_TR,
    FLUSH_EXPLANATION_TR,
    PLANAR_EXPLANATION_TR,
    WRAP_EXPLANATION_TR,
    TextSpec,
    analyze_target_surface,
    apply_text_to_assembly,
    build_text_volume,
    mesh_to_preview_payload,
    sanitize_text,
    spec_from_mapping,
)


def _inventory_row(inventory: list[dict[str, Any]] | None, filament_id: Optional[int]) -> dict[str, Any] | None:
    if filament_id is None:
        return None
    for row in inventory or []:
        if int(row.get("id") or 0) == int(filament_id):
            return row
    return None


def resolve_text_spec(
    text: TextCustomization | dict[str, Any] | None,
    inventory: list[dict[str, Any]] | None = None,
    fallback_material: str = "PLA",
) -> Optional[TextSpec]:
    if text is None:
        return None
    if isinstance(text, TextCustomization):
        data = text.model_dump(mode="json")
    else:
        data = dict(text)
    if not data.get("enabled", True):
        return None
    content = sanitize_text(str(data.get("content") or ""))
    if not content:
        return None
    row = _inventory_row(inventory, data.get("filament_id"))
    color = data.get("color_hex") or (hex_from_color_name(row.get("color")) if row else DEFAULT_TEXT_COLOR)
    spec = spec_from_mapping({**data, "content": content, "color_hex": color, "enabled": True})
    if spec is None:
        return None
    if data.get("extruder"):
        spec.extruder = int(data["extruder"])
    spec.filament_id = data.get("filament_id")
    _ = fallback_material
    return spec


def _surface_blurb(wrap: bool, surface_note: str) -> str:
    if wrap:
        return WRAP_EXPLANATION_TR
    return surface_note or PLANAR_EXPLANATION_TR


def _explanations_for(spec: TextSpec, wrap: bool, surface_note: str) -> dict[str, str]:
    active = (
        FLUSH_EXPLANATION_TR
        if spec.style == "flush"
        else EMBOSS_EXPLANATION_TR.format(height=spec.height_mm)
    )
    return {
        "flush": FLUSH_EXPLANATION_TR,
        "embossed": EMBOSS_EXPLANATION_TR.format(height=spec.height_mm),
        "active": active,
        "surface": _surface_blurb(wrap, surface_note),
        "wrap": WRAP_EXPLANATION_TR,
        "planar": PLANAR_EXPLANATION_TR,
    }


def attach_text_to_recommendation(
    rec: PrintRecommendation,
    spec: TextSpec,
    *,
    wrap_applied: bool,
    letter_height_mm: float,
    inventory_row: dict[str, Any] | None = None,
) -> PrintRecommendation:
    rec.text_applied = True
    rec.text_style = spec.style
    rec.text_surface_mode = spec.surface_mode
    rec.text_wrap_applied = bool(wrap_applied)
    rec.text_content = spec.content
    rec.text_extruder = spec.extruder
    rec.text_letter_height_mm = round(float(letter_height_mm), 2)
    rec.text_explanation = (
        FLUSH_EXPLANATION_TR
        if spec.style == "flush"
        else EMBOSS_EXPLANATION_TR.format(height=spec.height_mm)
    )
    if wrap_applied:
        rec.text_explanation = f"{rec.text_explanation} {_surface_blurb(True, '')}"
    if spec.style == "embossed":
        rec.wall_generator = "arachne"
        rec.fine_detail_optimization = True
        reasons = dict(rec.setting_reasons or {})
        reasons["wall_generator"] = (
            "Kabartmalı yazı perimetreleri için Arachne duvar motoru açıldı; "
            "ince harf duvarları Classic generator'da kaybolmaz."
        )
        rec.setting_reasons = reasons
        if rec.line_width_mm is None:
            rec.line_width_mm = FINE_TEXT_LINE_WIDTH_MM
        hints = dict(rec.slicer_hints or {})
        hints["wall_generator"] = "arachne"
        hints["line_width"] = rec.line_width_mm
        hints["outer_wall_line_width"] = rec.outer_wall_line_width_mm or rec.line_width_mm
        rec.slicer_hints = hints

    slot = text_filament_slot(
        extruder=spec.extruder,
        color_hex=spec.color_hex,
        inventory_row=inventory_row,
        fallback_material=rec.material,
    )
    slots = list(rec.filament_slots or [])
    while len(slots) < spec.extruder:
        filler = slots[-1] if slots else slot
        extra = filler.model_copy(deep=True)
        extra.extruder = len(slots) + 1
        slots.append(extra)
    slots[spec.extruder - 1] = slot
    rec.filament_slots = slots
    return rec


def preview_text_on_model(
    model_path: Path,
    spec: TextSpec,
) -> TextPreviewResponse:
    assembly = MeshParser().parse(model_path)
    host = assembly.combined_mesh()
    surface = analyze_target_surface(host)
    built = build_text_volume(host, spec, surface)
    payload = mesh_to_preview_payload(built.mesh)
    bounds = built.host_bounds
    return TextPreviewResponse(
        enabled=True,
        surface_kind=surface.kind,
        wrap_applied=built.wrap_applied,
        wrap_recommended=surface.wrap_recommended,
        style=spec.style,
        surface_mode=spec.surface_mode,
        letter_height_mm=round(built.letter_height_mm, 2),
        height_mm=spec.height_mm,
        inlay_depth_mm=spec.inlay_depth_mm,
        extruder=spec.extruder,
        color_hex=display_hex(spec.color_hex),
        subtype=spec.subtype,
        explanations=_explanations_for(spec, built.wrap_applied, surface.note),
        surface_note=surface.note,
        host_bounds_min=[round(float(v), 4) for v in bounds[0]],
        host_bounds_max=[round(float(v), 4) for v in bounds[1]],
        vertices=payload["vertices"],
        faces=payload["faces"],
        triangle_count=payload["triangle_count"],
        vertex_count=payload["vertex_count"],
    )


def apply_text_volume(
    assembly,
    spec: TextSpec,
):
    return apply_text_to_assembly(assembly, spec)
