"""Map PrintRecommendation.slicer_hints → CLI profile overlays (Phase B)."""

from __future__ import annotations

from typing import Any

from app.schemas import PrintRecommendation


def recommendation_to_cli_overlay(rec: PrintRecommendation) -> dict[str, Any]:
    """
    Produce a structure ready for Bambu Studio / OrcaSlicer:
      --load-settings "machine.json;process.json"
      --load-filaments "filament.json"

    Full JSON presets still come from `profiles/`; this overlays the AI fields.
    """
    hints = rec.slicer_hints or {}
    process_overlay = {
        "layer_height": hints.get("layer_height", rec.layer_height_mm),
        "wall_loops": hints.get("wall_loops", rec.wall_loops),
        "sparse_infill_density": hints.get("sparse_infill_density", rec.infill_percent),
        "sparse_infill_pattern": hints.get("sparse_infill_pattern", rec.infill_pattern),
        "enable_support": hints.get("enable_support", rec.supports),
        "support_type": hints.get(
            "support_type",
            rec.support_type or ("tree(auto)" if rec.supports else "normal(auto)"),
        ),
        "brim_width": hints.get("brim_width", 5 if rec.brim else 0),
        "outer_wall_speed": hints.get("outer_wall_speed", rec.outer_wall_speed_mm_s),
        "sparse_infill_speed": hints.get("sparse_infill_speed", rec.sparse_infill_speed_mm_s),
        "print_speed": hints.get("print_speed", rec.print_speed_mm_s),
    }
    filament_overlay = {
        "filament_type": hints.get("filament_type", rec.material),
        "nozzle_temperature": hints.get("nozzle_temperature", rec.nozzle_temp_c),
        "bed_temperature": hints.get("bed_temperature", rec.bed_temp_c),
    }
    if rec.filament_slots:
        filament_overlay["filament_type"] = [slot.studio_type for slot in rec.filament_slots]
        filament_overlay["nozzle_temperature"] = [slot.nozzle_temp_c for slot in rec.filament_slots]
        filament_overlay["bed_temperature"] = [slot.bed_temp_c for slot in rec.filament_slots]
        filament_overlay["filament_slots"] = [slot.model_dump() for slot in rec.filament_slots]
    machine_overlay = {
        "nozzle_diameter": hints.get("nozzle_diameter", rec.nozzle_mm),
        "printer_model": hints.get("printer_model", "Bambu Lab P2S Combo"),
    }
    return {
        "schema_version": rec.schema_version,
        "process": process_overlay,
        "filament": filament_overlay,
        "machine": machine_overlay,
        "cli_example": (
            'orca-slicer --slice 0 --orient --arrange 1 '
            '--load-settings "profiles/machine.json;profiles/process.json" '
            '--load-filaments "profiles/filament.json" '
            '--export-3mf output.gcode.3mf model.glb'
        ),
    }
