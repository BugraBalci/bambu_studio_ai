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
        "brim_width": hints.get("brim_width", 5 if rec.brim else 0),
    }
    filament_overlay = {
        "filament_type": hints.get("filament_type", rec.material),
        "nozzle_temperature": hints.get("nozzle_temperature", rec.nozzle_temp_c),
        "bed_temperature": hints.get("bed_temperature", rec.bed_temp_c),
    }
    machine_overlay = {
        "nozzle_diameter": hints.get("nozzle_diameter", rec.nozzle_mm),
        "printer_model": hints.get("printer_model", "Bambu Lab P2S"),
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
            '--export-3mf output.gcode.3mf model.stl'
        ),
    }
