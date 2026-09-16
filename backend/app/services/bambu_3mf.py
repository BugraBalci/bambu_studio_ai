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
    PRINTER_VARIANT_DIAMETER,
    first_scalar,
    fmt_bool01,
    fmt_float,
    fmt_percent,
    generic_filament_settings_id,
    optional_hint,
    print_settings_id_for,
)

TEMPLATE_PATH = ROOT_DIR / "profiles" / "bambu_project_settings_template.json"


def _as_int(value: Any, default: int) -> int:
    try:
        return int(round(float(first_scalar(value))))
    except (TypeError, ValueError):
        return default


def _filament_arrays(rec: PrintRecommendation, hints: dict[str, Any]) -> dict[str, Any]:
    """Bambu stores many filament keys as length-1 arrays of strings."""
    if rec.filament_slots:
        slot = rec.filament_slots[0]
        nozzle = str(_as_int(optional_hint(hints, "nozzle_temperature", slot.nozzle_temp_c), slot.nozzle_temp_c))
        bed = str(_as_int(optional_hint(hints, "bed_temperature", slot.bed_temp_c), slot.bed_temp_c))
        filament_type = str(optional_hint(hints, "filament_type", slot.studio_type))
        settings_id = slot.filament_settings_id or generic_filament_settings_id(slot.material)
        return {
            "filament_type": [filament_type],
            "filament_ids": [slot.filament_ids],
            "filament_settings_id": [settings_id],
            "default_filament_profile": [settings_id],
            "nozzle_temperature": [nozzle],
            "nozzle_temperature_initial_layer": [nozzle],
            "bed_temperature": [bed],
            "cool_plate_temp": [bed],
            "cool_plate_temp_initial_layer": [bed],
            "eng_plate_temp": [bed],
            "eng_plate_temp_initial_layer": [bed],
            "hot_plate_temp": [bed],
            "hot_plate_temp_initial_layer": [bed],
            "textured_plate_temp": [bed],
            "textured_plate_temp_initial_layer": [bed],
        }
    preset = studio_preset(rec.material)
    nozzle = str(_as_int(optional_hint(hints, "nozzle_temperature", rec.nozzle_temp_c), rec.nozzle_temp_c))
    bed = str(_as_int(optional_hint(hints, "bed_temperature", rec.bed_temp_c), rec.bed_temp_c))
    filament_type = str(optional_hint(hints, "filament_type", preset["studio_type"]))
    settings_id = str(preset["filament_settings_id"])
    return {
        "filament_type": [filament_type],
        "filament_ids": [preset["filament_ids"]],
        "filament_settings_id": [settings_id],
        "default_filament_profile": [settings_id],
        "nozzle_temperature": [nozzle],
        "nozzle_temperature_initial_layer": [nozzle],
        "bed_temperature": [bed],
        "cool_plate_temp": [bed],
        "cool_plate_temp_initial_layer": [bed],
        "eng_plate_temp": [bed],
        "eng_plate_temp_initial_layer": [bed],
        "hot_plate_temp": [bed],
        "hot_plate_temp_initial_layer": [bed],
        "textured_plate_temp": [bed],
        "textured_plate_temp_initial_layer": [bed],
    }


def recommendation_to_project_overrides(rec: PrintRecommendation) -> dict[str, Any]:
    """Map Rule Engine / slicer_hints onto Bambu Studio project_settings keys."""
    hints = rec.slicer_hints or {}
    nozzle = first_scalar(optional_hint(hints, "nozzle_diameter", rec.nozzle_mm)) or rec.nozzle_mm
    layer = first_scalar(optional_hint(hints, "layer_height", rec.layer_height_mm))
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
    brim_hint = optional_hint(hints, "brim_type", None)
    if brim_hint is None:
        brim_type = "outer_only" if rec.brim else "no_brim"
    else:
        brim_type = str(brim_hint)
    brim_width = optional_hint(hints, "brim_width", 5 if rec.brim else 0)
    support_type = optional_hint(
        hints,
        "support_type",
        rec.support_type
        if rec.supports and rec.support_type and rec.support_type != "none"
        else ("tree(auto)" if rec.supports else "normal(auto)"),
    )
    layer_text = fmt_float(layer)
    process_name = print_settings_id_for(layer, nozzle)
    overrides: dict[str, Any] = {
        "printer_model": "Bambu Lab P2S",
        "printer_variant": PRINTER_VARIANT_DIAMETER,
        "printer_settings_id": "Bambu Lab P2S 0.4 nozzle",
        "print_settings_id": process_name,
        "default_print_profile": process_name,
        "print_compatible_printers": ["Bambu Lab P2S 0.4 nozzle"],
        "from": "project",
        "name": "project_settings",
        "nozzle_diameter": [fmt_float(nozzle)],
        "layer_height": layer_text,
        "initial_layer_print_height": fmt_float(min(float(layer), 0.2)),
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
        "print_sequence": "by layer",
    }
    overrides.update(_filament_arrays(rec, hints))
    return overrides


def build_project_settings(rec: PrintRecommendation) -> dict[str, Any]:
    engine = BambuConfigEngine(baseline=recommendation_to_project_overrides(rec))
    return engine.merge_into_template(template_path=TEMPLATE_PATH)


def write_bambu_3mf_bytes(
    model_path: Path,
    rec: PrintRecommendation,
    part_name: str = "model",
) -> bytes:
    assembly = MeshParser().parse(model_path)
    settings = build_project_settings(rec)
    engine = BambuConfigEngine()
    slot_profiles = [slot.model_dump() for slot in rec.filament_slots] if rec.filament_slots else None
    settings = engine.expand_filaments(settings, assembly.materials, slot_profiles=slot_profiles)
    sidecar = {
        "recommendation": rec.model_dump(),
        "printer": "Bambu Lab P2S Combo",
    }
    return ProjectPackager().pack_bytes(
        assembly,
        settings,
        extra_meta=sidecar,
        part_name=part_name,
    )
