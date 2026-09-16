"""Bambu Studio project_settings identity + value formatting (P2S).

The stock `bambu_project_settings_template.json` is an A1 0.20mm Standard export.
Studio uses `print_settings_id` / `from` / `different_settings_to_system` to decide
whether embedded JSON is a real project overlay or should be replaced by the
named system preset. Stamp P2S headers after every merge so the archive cannot
silently fall back to A1 Standard.
"""

from __future__ import annotations

from typing import Any, Optional

from slicer_pipeline.constants import PRINTER_MODEL, PRINTER_NAME, PRINTER_SETTINGS_ID

PRINTER_VARIANT_DIAMETER = "0.4"
PRINT_COMPATIBLE_PRINTERS = [PRINTER_SETTINGS_ID]
DEFAULT_PRINT_PROFILE = "0.20mm Standard @BBL P2S"

# Official 0.4-nozzle P2S process presets shipped with Bambu Studio.
# There is no "0.28mm Extra Draft @BBL P2S"; 0.28 maps to the nearest named profile
# and the actual layer height is listed in `different_settings_to_system`.
P2S_PROCESS_BY_LAYER: tuple[tuple[float, str], ...] = (
    (0.08, "0.08mm High Quality @BBL P2S"),
    (0.12, "0.12mm High Quality @BBL P2S"),
    (0.16, "0.16mm Standard @BBL P2S"),
    (0.20, DEFAULT_PRINT_PROFILE),
    (0.24, "0.24mm Standard @BBL P2S"),
)

P2S_UPWARD_COMPATIBLE = [
    "Bambu Lab A1 0.4 nozzle",
    "Bambu Lab H2S 0.4 nozzle",
    "Bambu Lab H2D 0.4 nozzle",
    "Bambu Lab H2D Pro 0.4 nozzle",
    "Bambu Lab H2C 0.4 nozzle",
    "Bambu Lab X2D 0.4 nozzle",
    "Bambu Lab A2L 0.4 nozzle",
]

# Process keys we always treat as project-level diffs vs the named system preset.
PROCESS_DIFF_KEYS: tuple[str, ...] = (
    "layer_height",
    "initial_layer_print_height",
    "wall_loops",
    "sparse_infill_density",
    "sparse_infill_pattern",
    "enable_support",
    "support_type",
    "brim_type",
    "brim_width",
    "outer_wall_speed",
    "inner_wall_speed",
    "sparse_infill_speed",
    "internal_solid_infill_speed",
    "top_surface_speed",
    "print_sequence",
)

FILAMENT_DIFF_KEYS: tuple[str, ...] = (
    "nozzle_temperature",
    "nozzle_temperature_initial_layer",
    "bed_temperature",
    "cool_plate_temp",
    "cool_plate_temp_initial_layer",
    "eng_plate_temp",
    "eng_plate_temp_initial_layer",
    "hot_plate_temp",
    "hot_plate_temp_initial_layer",
    "textured_plate_temp",
    "textured_plate_temp_initial_layer",
    "filament_type",
    "filament_settings_id",
)

# Per-object keys Studio honors from model_settings.config (not only the global JSON).
OBJECT_PROCESS_KEYS: tuple[str, ...] = (
    "layer_height",
    "wall_loops",
    "sparse_infill_density",
    "sparse_infill_pattern",
    "enable_support",
    "support_type",
    "brim_type",
    "brim_width",
)

P2S_PROJECT_IDENTITY = {
    "from": "project",
    "name": "project_settings",
    "printer_model": PRINTER_MODEL,
    "printer_variant": PRINTER_VARIANT_DIAMETER,
    "printer_settings_id": PRINTER_SETTINGS_ID,
    "print_compatible_printers": list(PRINT_COMPATIBLE_PRINTERS),
    "printer_structure": "corexy",
    "printer_notes": f"Generated for {PRINTER_NAME}",
    "upward_compatible_machine": list(P2S_UPWARD_COMPATIBLE),
}


def fmt_float(value: Any) -> str:
    """Compact decimal string: 0.28 → '0.28', 0.20 → '0.2'."""
    text = f"{float(value):.3f}".rstrip("0").rstrip(".")
    return text if "." in text else f"{text}.0"


def fmt_percent(value: Any) -> str:
    if value is None:
        return "0%"
    text = str(value).strip()
    if text.endswith("%"):
        return text
    try:
        return f"{int(round(float(text)))}%"
    except (TypeError, ValueError):
        return text


def fmt_bool01(value: Any) -> str:
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "on"}:
            return "1"
        if lowered in {"0", "false", "no", "off"}:
            return "0"
    return "1" if value else "0"


def first_scalar(value: Any) -> Any:
    if isinstance(value, list):
        return value[0] if value else None
    return value


def print_settings_id_for(layer_height: Any, nozzle_mm: Any = 0.4) -> str:
    """Nearest official P2S process preset name for the given layer height."""
    try:
        layer = float(first_scalar(layer_height) if layer_height is not None else 0.2)
    except (TypeError, ValueError):
        layer = 0.2
    try:
        nozzle = float(first_scalar(nozzle_mm) if nozzle_mm is not None else 0.4)
    except (TypeError, ValueError):
        nozzle = 0.4
    if abs(nozzle - 0.4) > 1e-6:
        return f"{PRINTER_SETTINGS_ID}"
    closest = min(P2S_PROCESS_BY_LAYER, key=lambda item: abs(item[0] - layer))
    return closest[1]


def generic_filament_settings_id(material: Any) -> str:
    kind = str(material or "PLA").upper().replace("PLA+", "PLA")
    if kind.startswith("PLA"):
        kind = "PLA"
    elif "PET" in kind:
        kind = "PETG"
    elif kind.startswith("ABS"):
        kind = "ABS"
    elif kind.startswith("ASA"):
        kind = "ASA"
    elif kind.startswith("TPU"):
        kind = "TPU"
    else:
        kind = "PLA"
    return f"Generic {kind} @BBL P2S"


def object_metadata_from_settings(settings: dict[str, Any]) -> dict[str, str]:
    """Flat string map written onto each `<object>` in model_settings.config."""
    out: dict[str, str] = {}
    for key in OBJECT_PROCESS_KEYS:
        if key not in settings:
            continue
        value = first_scalar(settings[key])
        if value is None:
            continue
        out[key] = str(value)
    return out


def _filament_slot_count(settings: dict[str, Any]) -> int:
    for key in ("filament_type", "filament_settings_id", "nozzle_temperature", "filament_colour"):
        value = settings.get(key)
        if isinstance(value, list) and value:
            return max(1, len(value))
    return 1


def different_settings_to_system(settings: dict[str, Any]) -> list[str]:
    """Studio only keeps JSON keys listed here; the rest snap back to the system preset."""
    process_keys = [key for key in PROCESS_DIFF_KEYS if key in settings]
    extra_process = [
        key
        for key in (
            "initial_layer_speed",
            "elefant_foot_compensation",
            "xy_hole_compensation",
            "wall_generator",
        )
        if key in settings and key not in process_keys
    ]
    process_entry = ";".join(process_keys + extra_process)
    slots = _filament_slot_count(settings)
    filament_keys = [key for key in FILAMENT_DIFF_KEYS if key in settings]
    filament_entry = ";".join(filament_keys)
    rows = [process_entry]
    rows.extend(filament_entry for _ in range(slots))
    return rows


def stamp_p2s_project_headers(settings: dict[str, Any]) -> dict[str, Any]:
    """Force P2S project identity so Studio does not bind the A1 0.20mm Standard preset."""
    settings.update(P2S_PROJECT_IDENTITY)
    layer = settings.get("layer_height", 0.2)
    nozzle = first_scalar(settings.get("nozzle_diameter", PRINTER_VARIANT_DIAMETER))
    process_name = print_settings_id_for(layer, nozzle)
    settings["print_settings_id"] = process_name
    settings["default_print_profile"] = process_name
    settings["printer_variant"] = PRINTER_VARIANT_DIAMETER
    settings["printer_settings_id"] = PRINTER_SETTINGS_ID
    settings["print_compatible_printers"] = list(PRINT_COMPATIBLE_PRINTERS)
    settings["from"] = "project"
    settings["name"] = "project_settings"

    filament_ids = settings.get("filament_settings_id")
    if isinstance(filament_ids, list) and filament_ids:
        cleaned = []
        for item in filament_ids:
            text = str(item)
            cleaned.append(text.replace("@BBL A1", "@BBL P2S").replace("@BBL A1M", "@BBL P2S"))
        settings["filament_settings_id"] = cleaned
        settings["default_filament_profile"] = [cleaned[0]]
    elif isinstance(filament_ids, str) and filament_ids:
        cleaned = filament_ids.replace("@BBL A1", "@BBL P2S").replace("@BBL A1M", "@BBL P2S")
        settings["filament_settings_id"] = [cleaned]
        settings["default_filament_profile"] = [cleaned]

    settings["different_settings_to_system"] = different_settings_to_system(settings)
    return settings


def optional_hint(hints: Optional[dict[str, Any]], key: str, fallback: Any) -> Any:
    if hints and key in hints and hints[key] is not None:
        return hints[key]
    return fallback
