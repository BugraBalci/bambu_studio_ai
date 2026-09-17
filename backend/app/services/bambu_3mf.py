"""Build a Bambu Studio–compatible project .3mf (geometry + settings).

Note: This is a project file you open in Bambu Studio and Slice — not a
pre-sliced .gcode.3mf. Settings are embedded in Metadata/project_settings.config.
Meshy color / sub-mesh hierarchy is preserved via MeshParser + ProjectPackager.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from app.config import ROOT_DIR
from app.schemas import PrintRecommendation
from app.services.filament_compat import studio_preset

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from slicer_pipeline.bambu_config import BambuConfigEngine  # noqa: E402
from slicer_pipeline.mesh_parser import MeshParser  # noqa: E402
from slicer_pipeline.project_packager import ProjectPackager  # noqa: E402
from slicer_pipeline.studio_profile import (  # noqa: E402
    clamp_layer_height,
    first_scalar,
    fmt_bool01,
    fmt_float,
    fmt_percent,
    generic_filament_settings_id,
    nozzle_variant,
    optional_hint,
    print_settings_id_for,
    printer_settings_id_for,
    retarget_to_p2s,
)
from slicer_pipeline.text_engine import TextSpec  # noqa: E402

TEMPLATE_PATH = ROOT_DIR / "profiles" / "bambu_project_settings_template.json"


def _as_int(value: Any, default: int) -> int:
    try:
        return int(round(float(first_scalar(value))))
    except (TypeError, ValueError):
        return default


# Studio has no `bed_temperature` option: bed heat is per plate surface, and the
# active surface comes from `curr_bed_type` (Textured PEI Plate for the P2S).
_PLATE_TEMP_KEYS: tuple[str, ...] = (
    "cool_plate_temp",
    "cool_plate_temp_initial_layer",
    "eng_plate_temp",
    "eng_plate_temp_initial_layer",
    "hot_plate_temp",
    "hot_plate_temp_initial_layer",
    "textured_plate_temp",
    "textured_plate_temp_initial_layer",
    "supertack_plate_temp",
    "supertack_plate_temp_initial_layer",
)


def _filament_column(
    filament_type: str,
    filament_ids: str,
    settings_id: str,
    nozzle_temp: str,
    bed_temp: str,
) -> dict[str, Any]:
    """Bambu stores per-filament keys as arrays; one slot → length-1 arrays."""
    column: dict[str, Any] = {
        "filament_type": [filament_type],
        "filament_ids": [filament_ids],
        "filament_settings_id": [settings_id],
        "default_filament_profile": [settings_id],
        "nozzle_temperature": [nozzle_temp],
        "nozzle_temperature_initial_layer": [nozzle_temp],
    }
    column.update({key: [bed_temp] for key in _PLATE_TEMP_KEYS})
    return column


def _filament_arrays(rec: PrintRecommendation, hints: dict[str, Any]) -> dict[str, Any]:
    if rec.filament_slots:
        slot = rec.filament_slots[0]
        return _filament_column(
            filament_type=str(optional_hint(hints, "filament_type", slot.studio_type)),
            filament_ids=str(slot.filament_ids),
            settings_id=retarget_to_p2s(
                slot.filament_settings_id or generic_filament_settings_id(slot.material)
            ),
            nozzle_temp=str(
                _as_int(
                    optional_hint(hints, "nozzle_temperature", slot.nozzle_temp_c),
                    slot.nozzle_temp_c,
                )
            ),
            bed_temp=str(
                _as_int(optional_hint(hints, "bed_temperature", slot.bed_temp_c), slot.bed_temp_c)
            ),
        )
    preset = studio_preset(rec.material)
    return _filament_column(
        filament_type=str(optional_hint(hints, "filament_type", preset["studio_type"])),
        filament_ids=str(preset["filament_ids"]),
        settings_id=retarget_to_p2s(preset["filament_settings_id"]),
        nozzle_temp=str(
            _as_int(
                optional_hint(hints, "nozzle_temperature", rec.nozzle_temp_c), rec.nozzle_temp_c
            )
        ),
        bed_temp=str(
            _as_int(optional_hint(hints, "bed_temperature", rec.bed_temp_c), rec.bed_temp_c)
        ),
    )


def recommendation_to_project_overrides(rec: PrintRecommendation) -> dict[str, Any]:
    """Map Rule Engine / slicer_hints onto Bambu Studio project_settings keys."""
    hints = rec.slicer_hints or {}
    nozzle = nozzle_variant(
        first_scalar(optional_hint(hints, "nozzle_diameter", rec.nozzle_mm)) or rec.nozzle_mm
    )
    layer = clamp_layer_height(
        first_scalar(optional_hint(hints, "layer_height", rec.layer_height_mm)), nozzle
    )
    walls = _as_int(optional_hint(hints, "wall_loops", rec.wall_loops), rec.wall_loops)
    density = fmt_percent(optional_hint(hints, "sparse_infill_density", rec.infill_percent))
    pattern = str(optional_hint(hints, "sparse_infill_pattern", rec.infill_pattern) or "grid")
    outer = _as_int(optional_hint(hints, "outer_wall_speed", rec.outer_wall_speed_mm_s or 80), 80)
    print_speed = _as_int(
        optional_hint(hints, "print_speed", rec.print_speed_mm_s or 150)
        or optional_hint(hints, "internal_solid_infill_speed", rec.print_speed_mm_s or 150),
        150,
    )
    sparse = _as_int(
        optional_hint(hints, "sparse_infill_speed", rec.sparse_infill_speed_mm_s or 180),
        180,
    )
    supports = optional_hint(hints, "enable_support", rec.supports)
    brim_hint = optional_hint(hints, "brim_type", rec.brim_type)
    if brim_hint is None:
        brim_type = "outer_only" if rec.brim else "no_brim"
    else:
        brim_type = str(brim_hint)
    brim_width = optional_hint(
        hints,
        "brim_width",
        rec.brim_width_mm if rec.brim_width_mm is not None else (5 if rec.brim else 0),
    )
    support_type = optional_hint(
        hints,
        "support_type",
        rec.support_type
        if rec.supports and rec.support_type and rec.support_type != "none"
        else ("tree(auto)" if rec.supports else "normal(auto)"),
    )
    initial_layer = _as_int(optional_hint(hints, "initial_layer_speed", 50), 50)
    layer_text = fmt_float(layer)
    process_name = print_settings_id_for(layer, nozzle)
    printer_name = printer_settings_id_for(nozzle)
    overrides: dict[str, Any] = {
        "printer_model": "Bambu Lab P2S",
        "printer_variant": nozzle,
        "printer_settings_id": printer_name,
        "print_settings_id": process_name,
        "default_print_profile": process_name,
        "print_compatible_printers": [printer_name],
        # The process preset the calculated values are a diff against. Bambu Studio
        # resolves this through inherits_group and resets any key that is not listed
        # in different_settings_to_system, so it has to name an installed preset.
        "inherits": process_name,
        "from": "project",
        "name": "project_settings",
        "nozzle_diameter": [nozzle],
        "layer_height": layer_text,
        # A calculated 0.28 mm project prints its first layer at 0.28 too; clamping
        # this to 0.2 is what made Studio look like it had loaded a 0.2 mm profile.
        "initial_layer_print_height": layer_text,
        "wall_loops": str(walls),
        "sparse_infill_density": density,
        "sparse_infill_pattern": pattern,
        "enable_support": fmt_bool01(supports),
        "support_type": str(support_type),
        "brim_width": str(_as_int(brim_width, 0)),
        "brim_type": brim_type,
        # Values are strings; merge_into_template wraps them into Studio arrays
        # when the A1-derived template stores the key as a length-1 list.
        "outer_wall_speed": str(outer),
        "inner_wall_speed": str(min(print_speed, outer + 40)),
        "sparse_infill_speed": str(sparse),
        "internal_solid_infill_speed": str(print_speed),
        "top_surface_speed": str(min(outer, 100)),
        "initial_layer_speed": str(initial_layer),
        "print_sequence": "by layer",
    }
    overrides.update(_filament_arrays(rec, hints))
    for key in (
        "wall_generator",
        "line_width",
        "outer_wall_line_width",
        "initial_layer_line_width",
        "fuzzy_skin",
        "fuzzy_skin_point_distance",
        "fuzzy_skin_thickness",
    ):
        value = optional_hint(hints, key, None)
        if value is None and key == "wall_generator":
            value = rec.wall_generator
        if value is None and key == "line_width" and rec.line_width_mm is not None:
            value = rec.line_width_mm
        if value is None and key == "outer_wall_line_width":
            value = rec.outer_wall_line_width_mm if rec.outer_wall_line_width_mm is not None else rec.line_width_mm
        if value is None:
            continue
        overrides[key] = str(first_scalar(value))
    return overrides


def build_project_settings(rec: PrintRecommendation) -> dict[str, Any]:
    engine = BambuConfigEngine(baseline=recommendation_to_project_overrides(rec))
    return engine.merge_into_template(template_path=TEMPLATE_PATH)


def write_bambu_3mf_bytes(
    model_path: Path,
    rec: PrintRecommendation,
    part_name: str = "model",
    text_spec: TextSpec | None = None,
    inventory: list[dict[str, Any]] | None = None,
) -> bytes:
    from app.services.text_custom import apply_text_volume, attach_text_to_recommendation

    assembly = MeshParser().parse(model_path)
    sidecar: dict[str, Any] = {
        "recommendation": rec.model_dump(),
        "printer": "Bambu Lab P2S Combo",
    }
    if text_spec is not None and text_spec.enabled:
        result = apply_text_volume(assembly, text_spec)
        row = None
        if inventory and result.spec.filament_id is not None:
            row = next(
                (item for item in inventory if int(item.get("id") or 0) == int(result.spec.filament_id)),
                None,
            )
        rec = attach_text_to_recommendation(
            rec,
            result.spec,
            wrap_applied=result.wrap_applied,
            letter_height_mm=result.letter_height_mm,
            inventory_row=row,
        )
        sidecar["text"] = {
            "content": result.spec.content,
            "style": result.spec.style,
            "subtype": result.spec.subtype,
            "wrap_applied": result.wrap_applied,
            "surface": result.surface.as_dict(),
            "extruder": result.spec.extruder,
            "letter_height_mm": result.letter_height_mm,
        }
        sidecar["recommendation"] = rec.model_dump()
    settings = build_project_settings(rec)
    engine = BambuConfigEngine()
    slot_profiles = [slot.model_dump() for slot in rec.filament_slots] if rec.filament_slots else None
    settings = engine.expand_filaments(settings, assembly.materials, slot_profiles=slot_profiles)
    return ProjectPackager().pack_bytes(
        assembly,
        settings,
        extra_meta=sidecar,
        part_name=part_name,
    )
