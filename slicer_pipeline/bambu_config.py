"""Map rule-engine outcomes onto Bambu Studio project_settings keys (P2S Combo)."""

from __future__ import annotations

import copy
import json
import logging
from pathlib import Path
from typing import Any, Optional

from slicer_pipeline.constants import (
    PRINTER_MODEL,
    PRINTER_NAME,
    PRINTER_SETTINGS_ID,
    PRINTER_VARIANT,
    TEMPLATE_PATH,
)
from slicer_pipeline.geometry import GeometryMetrics
from slicer_pipeline.rules import RuleResult

LOGGER = logging.getLogger("auto_slicer")

# Studio uses the historical misspelling `elefant_foot_compensation`.
KEY_ALIASES = {
    "elephant_foot_compensation": "elefant_foot_compensation",
    "cooling_fan_speed_max": "fan_max_speed",
}

P2S_IDENTITY = {
    "printer_model": PRINTER_MODEL,
    "printer_variant": "0.4",
    "printer_settings_id": PRINTER_SETTINGS_ID,
    "printer_notes": f"Generated for {PRINTER_NAME} by auto_slicer.py",
    "from": "auto_slicer",
}


class BambuConfigEngine:
    """
    Maintain a baseline Bambu Studio process/filament JSON dict and apply
    rule-driven overrides. Values follow Studio's string / string-array style.
    """

    def __init__(self, baseline: Optional[dict[str, Any]] = None) -> None:
        self.profile: dict[str, Any] = copy.deepcopy(baseline or self.default_baseline())

    @staticmethod
    def default_baseline() -> dict[str, Any]:
        """Conservative P2S Combo starting profile (single filament)."""
        return {
            "printer_model": PRINTER_MODEL,
            "printer_variant": PRINTER_VARIANT,
            "nozzle_diameter": ["0.4"],
            "layer_height": "0.20",
            "initial_layer_print_height": "0.20",
            "wall_loops": "3",
            "top_shell_layers": "5",
            "bottom_shell_layers": "3",
            "bottom_shell_thickness": "0.8",
            "xy_hole_compensation": "0",
            "sparse_infill_density": "15%",
            "sparse_infill_pattern": "grid",
            "wall_generator": "classic",
            "enable_support": "0",
            "support_type": "normal(auto)",
            "support_top_z_distance": "0.2",
            "brim_type": "auto_brim",
            "brim_width": "5",
            "elefant_foot_compensation": "0.1",
            "bottom_surface_pattern": "monotonic",
            "outer_wall_line_width": "0.42",
            "outer_wall_speed": ["150"],
            "inner_wall_speed": ["200"],
            "sparse_infill_speed": ["200"],
            "initial_layer_speed": "50",
            "default_acceleration": "5000",
            "outer_wall_acceleration": ["3000"],
            "fan_max_speed": ["80"],
            "fan_min_speed": ["60"],
            "fan_cooling_layer_time": ["10"],
            "nozzle_temperature": ["220"],
            "nozzle_temperature_initial_layer": ["220"],
            "filament_type": ["PLA"],
            "bed_temperature": ["60"],
            "textured_plate_temp": ["60"],
            "textured_plate_temp_initial_layer": ["60"],
            **P2S_IDENTITY,
        }

    def apply_rules(self, results: list[RuleResult]) -> dict[str, Any]:
        triggered = [r for r in results if r.triggered]
        LOGGER.info("%d / %d rules triggered", len(triggered), len(results))
        for r in triggered:
            LOGGER.info("Applying updates from rule '%s': %s", r.name, list(r.updates))
            for key, value in r.updates.items():
                self.profile[KEY_ALIASES.get(key, key)] = value
        layers = [
            r.updates.get("layer_height")
            for r in triggered
            if "layer_height" in r.updates
        ]
        if layers:
            try:
                chosen = min(float(x) for x in layers if x is not None)
                self.profile["layer_height"] = f"{chosen:.2f}"
            except ValueError:
                pass
        return self.profile

    def attach_metadata(self, metrics: GeometryMetrics, results: list[RuleResult]) -> None:
        self.profile["_auto_slicer_meta"] = {
            "source_file": metrics.filename,
            "printer": PRINTER_NAME,
            "is_watertight": metrics.is_watertight,
            "was_repaired": metrics.was_repaired,
            "volume_cm3": round(metrics.volume_cm3, 3),
            "extents_mm": [round(float(x), 3) for x in metrics.extents_mm],
            "overhang_area_percent": round(metrics.overhang_area_ratio * 100.0, 2),
            "aspect_ratio_z": round(metrics.aspect_ratio_z, 3),
            "top_cross_section_mm2": round(metrics.top_cross_section_mm2, 3),
            "vertex_density": round(metrics.vertex_density, 4),
            "normal_variance": round(metrics.normal_variance, 4),
            "fits_p2s_bed": metrics.fits_p2s_bed,
            "center_of_mass_mm": [round(float(x), 3) for x in metrics.center_of_mass],
            "cog_z_ratio": round(metrics.cog_z_ratio, 4),
            "cog_xy_offset_ratio": round(metrics.cog_xy_offset_ratio, 4),
            "tip_over_risk": metrics.tip_over_risk,
            "mechanical_hole_count": metrics.mechanical_hole_count,
            "hole_diameters_mm": [round(d, 2) for d in metrics.hole_diameters_mm],
            "part_count": metrics.part_count,
            "color_count": metrics.color_count,
            "triggered_rules": [r.name for r in results if r.triggered],
        }

    def merge_into_template(
        self,
        template: Optional[dict[str, Any]] = None,
        template_path: Optional[Path] = None,
    ) -> dict[str, Any]:
        """Patch the full Bambu Studio project_settings blob with rule overrides."""
        if template is None:
            path = Path(template_path) if template_path else TEMPLATE_PATH
            if path.exists():
                template = json.loads(path.read_text(encoding="utf-8"))
            else:
                LOGGER.warning("Project settings template missing (%s); using compact profile", path)
                template = {}
        settings = copy.deepcopy(template)
        for key, value in self.profile.items():
            if key.startswith("_"):
                continue
            dest_key = KEY_ALIASES.get(key, key)
            if dest_key in settings:
                settings[dest_key] = coerce_to_template(value, settings[dest_key])
            else:
                settings[dest_key] = value
        settings.update(P2S_IDENTITY)
        settings["printer_variant"] = "0.4"
        settings["printer_settings_id"] = PRINTER_SETTINGS_ID
        if "_auto_slicer_meta" in self.profile:
            settings["_auto_slicer_meta"] = self.profile["_auto_slicer_meta"]
        return settings

    def expand_filaments(
        self,
        settings: dict[str, Any],
        colors: list[str],
        slot_profiles: Optional[list[dict[str, Any]]] = None,
    ) -> dict[str, Any]:
        """Duplicate per-filament arrays so AMS colors line up with Studio."""
        palette = [c if c.startswith("#") else f"#{c}" for c in colors] or ["#FFFFFFFF"]
        n = len(palette)
        settings = copy.deepcopy(settings)
        settings["filament_colour"] = palette
        settings["default_filament_colour"] = palette
        settings["enable_prime_tower"] = "1" if n > 1 else "0"
        skip = {
            "wipe_tower_x",
            "wipe_tower_y",
            "extruder_ams_count",
            "bed_exclude_area",
            "printable_area",
            "thumbnail_size",
            "upward_compatible_machine",
            "nozzle_diameter",
        }
        for key, value in list(settings.items()):
            if key in skip or not isinstance(value, list) or not value:
                continue
            filament_key = key.startswith("filament_") or key in {
                "nozzle_temperature",
                "nozzle_temperature_initial_layer",
                "cool_plate_temp",
                "cool_plate_temp_initial_layer",
                "eng_plate_temp",
                "eng_plate_temp_initial_layer",
                "hot_plate_temp",
                "hot_plate_temp_initial_layer",
                "textured_plate_temp",
                "textured_plate_temp_initial_layer",
                "fan_max_speed",
                "fan_min_speed",
                "fan_cooling_layer_time",
                "filament_type",
                "filament_ids",
            }
            if filament_key and len(value) == 1 and n > 1:
                settings[key] = [value[0]] * n
        if "filament_type" in settings and isinstance(settings["filament_type"], list):
            if len(settings["filament_type"]) < n:
                fill = settings["filament_type"][0] if settings["filament_type"] else "PLA"
                settings["filament_type"] = (list(settings["filament_type"]) + [fill] * n)[:n]
        if slot_profiles:
            settings = self._apply_slot_profiles(settings, slot_profiles, n)
        return settings

    @staticmethod
    def _apply_slot_profiles(
        settings: dict[str, Any],
        slot_profiles: list[dict[str, Any]],
        n: int,
    ) -> dict[str, Any]:
        profiles = list(slot_profiles)
        if not profiles:
            return settings
        while len(profiles) < n:
            profiles.append(profiles[-1])
        profiles = profiles[:n]

        def column(key: str, default: str = "") -> list[str]:
            values: list[str] = []
            for profile in profiles:
                if isinstance(profile, dict):
                    values.append(str(profile.get(key, default)))
                else:
                    values.append(str(getattr(profile, key, default)))
            return values

        settings["filament_type"] = column("studio_type", "PLA")
        settings["filament_ids"] = column("filament_ids", "GFL99")
        settings["filament_settings_id"] = column("filament_settings_id", "Generic PLA @BBL P2S")
        settings["nozzle_temperature"] = column("nozzle_temp_c", "220")
        settings["nozzle_temperature_initial_layer"] = column("nozzle_temp_c", "220")
        bed = column("bed_temp_c", "60")
        for key in (
            "cool_plate_temp",
            "cool_plate_temp_initial_layer",
            "eng_plate_temp",
            "eng_plate_temp_initial_layer",
            "hot_plate_temp",
            "hot_plate_temp_initial_layer",
            "textured_plate_temp",
            "textured_plate_temp_initial_layer",
        ):
            settings[key] = bed
        settings["nozzle_temperature_range_low"] = column("nozzle_range_low", "190")
        settings["nozzle_temperature_range_high"] = column("nozzle_range_high", "240")
        settings["filament_vendor"] = ["Generic"] * n
        settings["filament_self_index"] = [str(i + 1) for i in range(n)]
        return settings

    def save(self, path: Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {k: v for k, v in self.profile.items()}
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        LOGGER.info("Wrote profile: %s", path.resolve())
        return path


def coerce_to_template(value: Any, template_value: Any) -> Any:
    """Keep Bambu Studio value shapes (string vs length-1 string array)."""
    if isinstance(template_value, list) and template_value:
        if isinstance(value, list):
            return [str(x) for x in value]
        return [str(value)]
    if isinstance(value, list):
        return str(value[0]) if value else str(template_value)
    if template_value is None:
        return value
    return str(value)
