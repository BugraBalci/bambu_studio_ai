"""Build a Bambu Studio–compatible project .3mf (geometry + settings).

Note: This is a project file you open in Bambu Studio and Slice — not a
pre-sliced .gcode.3mf. Settings are embedded in Metadata/project_settings.config.
Meshy color / sub-mesh hierarchy is preserved via MeshParser + ProjectPackager.
"""

from __future__ import annotations

import sys
from pathlib import Path

from app.config import ROOT_DIR
from app.schemas import PrintRecommendation
from app.services.filament_compat import studio_preset

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from slicer_pipeline.bambu_config import BambuConfigEngine  # noqa: E402
from slicer_pipeline.mesh_parser import MeshParser  # noqa: E402
from slicer_pipeline.project_packager import ProjectPackager  # noqa: E402

TEMPLATE_PATH = ROOT_DIR / "profiles" / "bambu_project_settings_template.json"


def _filament_arrays(rec: PrintRecommendation) -> dict:
    """Bambu stores many filament keys as length-1 arrays of strings."""
    if rec.filament_slots:
        slot = rec.filament_slots[0]
        preset = studio_preset(slot.material)
        nozzle = str(int(slot.nozzle_temp_c))
        bed = str(int(slot.bed_temp_c))
        return {
            "filament_type": [slot.studio_type],
            "filament_ids": [slot.filament_ids],
            "filament_settings_id": [slot.filament_settings_id],
            "nozzle_temperature": [nozzle],
            "nozzle_temperature_initial_layer": [nozzle],
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
    nozzle = str(int(rec.nozzle_temp_c))
    bed = str(int(rec.bed_temp_c))
    return {
        "filament_type": [preset["studio_type"]],
        "filament_ids": [preset["filament_ids"]],
        "filament_settings_id": [preset["filament_settings_id"]],
        "nozzle_temperature": [nozzle],
        "nozzle_temperature_initial_layer": [nozzle],
        "cool_plate_temp": [bed],
        "cool_plate_temp_initial_layer": [bed],
        "eng_plate_temp": [bed],
        "eng_plate_temp_initial_layer": [bed],
        "hot_plate_temp": [bed],
        "hot_plate_temp_initial_layer": [bed],
        "textured_plate_temp": [bed],
        "textured_plate_temp_initial_layer": [bed],
    }


def recommendation_to_project_overrides(rec: PrintRecommendation) -> dict:
    nozzle = rec.nozzle_mm
    outer = rec.outer_wall_speed_mm_s or 80
    sparse = rec.sparse_infill_speed_mm_s or 180
    print_speed = rec.print_speed_mm_s or 150
    density = f"{int(rec.infill_percent)}%"
    overrides: dict = {
        "printer_model": "Bambu Lab P2S",
        "printer_variant": "0.4",
        "nozzle_diameter": [str(nozzle)],
        "layer_height": str(rec.layer_height_mm),
        "initial_layer_print_height": str(min(rec.layer_height_mm, 0.2)),
        "wall_loops": str(rec.wall_loops),
        "sparse_infill_density": density,
        "sparse_infill_pattern": rec.infill_pattern,
        "enable_support": "1" if rec.supports else "0",
        "support_type": (
            rec.support_type
            if rec.supports and rec.support_type and rec.support_type != "none"
            else ("tree(auto)" if rec.supports else "normal(auto)")
        ),
        "brim_width": "5" if rec.brim else "0",
        "brim_type": "outer_only" if rec.brim else "no_brim",
        "outer_wall_speed": [str(outer)],
        "inner_wall_speed": [str(min(print_speed, outer + 40))],
        "sparse_infill_speed": [str(sparse)],
        "internal_solid_infill_speed": [str(max(60, sparse - 40))],
        "top_surface_speed": [str(min(outer, 100))],
        "print_sequence": "by layer",
    }
    overrides.update(_filament_arrays(rec))
    return overrides


def build_project_settings(rec: PrintRecommendation) -> dict:
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
