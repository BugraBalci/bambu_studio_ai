"""Bambu Studio project identity for the P2S (`Metadata/project_settings.config`).

Bambu Studio does not read the embedded JSON as a standalone profile. On import it
splits `project_settings.config` into a process, N filament, and a printer preset
(`PresetBundle::load_config_file_config`) and re-binds each one to an installed
*system* preset. Two vectors drive that, both sized `N + 2` and ordered
`[process, filament_1 .. filament_N, printer]`:

* ``inherits_group`` — the system preset each split preset inherits from. An empty
  entry means "no base", which is why an archive without it lands on whatever the
  user last had selected (the reported "0.20mm Standard @BBL A1" fallback).
  ``PresetBundle::validate_presets`` also falls back to ``inherits_group[N + 1]``
  when ``printer_settings_id`` names a printer that is not installed.
* ``different_settings_to_system`` — the keys Studio treats as deliberate project
  overrides. Everything *not* listed is reset to the base preset's value by
  ``PresetCollection::load_external_preset``, so an override missing from this list
  silently reverts.

Every preset name below is a real 0.x-nozzle preset shipped in
``resources/profiles/BBL`` — an ``inherits`` pointing at a preset that does not
exist resolves to nothing and drops us back to the no-base behaviour. Notably
there is **no** ``0.28mm Standard @BBL P2S``: on a 0.4 nozzle the coarsest stock
P2S process preset is ``0.24mm Standard @BBL P2S``, so a 0.28 mm project inherits
from that one and carries 0.28 as a listed diff.
"""

from __future__ import annotations

from typing import Any, Iterable, Optional

from slicer_pipeline.constants import (
    PRINTER_MODEL,
    PRINTER_NAME,
    PRINTER_SETTINGS_ID,
    STUDIO_BED_TYPE,
    STUDIO_VERSION,
)

PRINTER_VARIANT_DIAMETER = "0.4"
DEFAULT_PRINT_PROFILE = "0.20mm Standard @BBL P2S"

# Stock P2S process presets, keyed by nozzle diameter then layer height.
# Mirrors resources/profiles/BBL/process/*@BBL P2S*.json.
P2S_PROCESS_BY_NOZZLE: dict[str, tuple[tuple[float, str], ...]] = {
    "0.2": (
        (0.08, "0.08mm High Quality @BBL P2S 0.2 nozzle"),
        (0.10, "0.10mm Standard @BBL P2S 0.2 nozzle"),
        (0.12, "0.12mm Balanced Quality @BBL P2S 0.2 nozzle"),
    ),
    "0.4": (
        (0.08, "0.08mm High Quality @BBL P2S"),
        (0.12, "0.12mm High Quality @BBL P2S"),
        (0.16, "0.16mm Standard @BBL P2S"),
        (0.20, DEFAULT_PRINT_PROFILE),
        (0.24, "0.24mm Standard @BBL P2S"),
    ),
    "0.6": (
        (0.18, "0.18mm Balanced Quality @BBL P2S 0.6 nozzle"),
        (0.24, "0.24mm Balanced Quality @BBL P2S 0.6 nozzle"),
        (0.30, "0.30mm Standard @BBL P2S 0.6 nozzle"),
    ),
    "0.8": (
        (0.24, "0.24mm Balanced Quality @BBL P2S 0.8 nozzle"),
        (0.32, "0.32mm Balanced Quality @BBL P2S 0.8 nozzle"),
        (0.40, "0.40mm Standard @BBL P2S 0.8 nozzle"),
    ),
}

# Printable layer-height window per nozzle (min_layer_height / max_layer_height
# of the matching "Bambu Lab P2S <d> nozzle" machine preset).
P2S_LAYER_LIMITS: dict[str, tuple[float, float]] = {
    "0.2": (0.04, 0.14),
    "0.4": (0.08, 0.28),
    "0.6": (0.12, 0.42),
    "0.8": (0.16, 0.56),
}

P2S_UPWARD_COMPATIBLE = [
    "Bambu Lab H2S 0.4 nozzle",
    "Bambu Lab H2D 0.4 nozzle",
    "Bambu Lab H2D Pro 0.4 nozzle",
    "Bambu Lab H2C 0.4 nozzle",
    "Bambu Lab X2D 0.4 nozzle",
]

# Process keys we always declare as project-level diffs vs the named system preset.
# Anything omitted here is reset to the base preset's value on import.
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
    "initial_layer_speed",
    "print_sequence",
    "elefant_foot_compensation",
    "xy_hole_compensation",
    "wall_generator",
    "top_shell_layers",
    "bottom_shell_layers",
)

# Bambu has no `bed_temperature` option; bed heat lives on the per-plate keys.
FILAMENT_DIFF_KEYS: tuple[str, ...] = (
    "filament_type",
    "filament_settings_id",
    "nozzle_temperature",
    "nozzle_temperature_initial_layer",
    "nozzle_temperature_range_low",
    "nozzle_temperature_range_high",
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

# Keys that only exist in other slicers. Left in the JSON they become unknown
# options that Studio reports as config substitutions on every open.
UNSUPPORTED_KEYS: tuple[str, ...] = (
    "bed_temperature",
    "bed_temperature_initial_layer",
    "cooling_fan_speed_max",
    "elephant_foot_compensation",
)

# Per-object keys Studio honours from model_settings.config.
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
    "version": STUDIO_VERSION,
    "printer_model": PRINTER_MODEL,
    "printer_structure": "corexy",
    "printer_technology": "FFF",
    "printer_notes": f"Generated for {PRINTER_NAME}",
    "is_bbl_printer": "1",
    "curr_bed_type": STUDIO_BED_TYPE,
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


def _as_float(value: Any, default: float) -> float:
    try:
        return float(first_scalar(value))
    except (TypeError, ValueError):
        return default


def nozzle_variant(nozzle_mm: Any = PRINTER_VARIANT_DIAMETER) -> str:
    """Snap an arbitrary nozzle diameter onto a variant P2S actually ships."""
    nozzle = _as_float(nozzle_mm, 0.4)
    return min(P2S_LAYER_LIMITS, key=lambda variant: abs(float(variant) - nozzle))


def printer_settings_id_for(nozzle_mm: Any = PRINTER_VARIANT_DIAMETER) -> str:
    return f"{PRINTER_MODEL} {nozzle_variant(nozzle_mm)} nozzle"


def clamp_layer_height(layer_height: Any, nozzle_mm: Any = PRINTER_VARIANT_DIAMETER) -> float:
    """Keep the requested layer height inside the nozzle's printable window."""
    variant = nozzle_variant(nozzle_mm)
    low, high = P2S_LAYER_LIMITS[variant]
    return max(low, min(high, _as_float(layer_height, 0.2)))


def print_settings_id_for(layer_height: Any, nozzle_mm: Any = PRINTER_VARIANT_DIAMETER) -> str:
    """Closest *installed* P2S process preset for a layer height / nozzle pair.

    The returned name is used both as `print_settings_id` and as the process entry
    of `inherits_group`, so it has to be a preset Studio can actually resolve.
    """
    variant = nozzle_variant(nozzle_mm)
    layer = clamp_layer_height(layer_height, variant)
    ladder = P2S_PROCESS_BY_NOZZLE[variant]
    return min(ladder, key=lambda item: abs(item[0] - layer))[1]


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


def retarget_to_p2s(name: Any) -> str:
    """Rewrite an `@BBL <other printer>` preset suffix onto the P2S."""
    text = str(name or "")
    for stale in ("@BBL A1M", "@BBL A1 mini", "@BBL A1", "@BBL P1S", "@BBL P1P", "@BBL X1C", "@BBL X1"):
        if stale in text:
            return text.replace(stale, "@BBL P2S")
    return text


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


def filament_slot_count(settings: dict[str, Any]) -> int:
    """Studio derives the filament count from `filament_colour`."""
    for key in ("filament_colour", "filament_type", "filament_settings_id", "nozzle_temperature"):
        value = settings.get(key)
        if isinstance(value, list) and value:
            return max(1, len(value))
    return 1


def _pad(values: Iterable[str], slots: int) -> list[str]:
    out = [str(v) for v in values]
    if not out:
        return [""] * slots
    while len(out) < slots:
        out.append(out[-1])
    return out[:slots]


def inherits_group(settings: dict[str, Any]) -> list[str]:
    """`[process, filament_1 .. filament_N, printer]` system parents (size N + 2)."""
    slots = filament_slot_count(settings)
    process = str(settings.get("print_settings_id") or DEFAULT_PRINT_PROFILE)
    printer = str(settings.get("printer_settings_id") or PRINTER_SETTINGS_ID)
    filaments = settings.get("filament_settings_id")
    if isinstance(filaments, list):
        filament_names = _pad((retarget_to_p2s(f) for f in filaments), slots)
    elif filaments:
        filament_names = _pad([retarget_to_p2s(filaments)], slots)
    else:
        filament_names = [generic_filament_settings_id("PLA")] * slots
    return [process, *filament_names, printer]


def different_settings_to_system(settings: dict[str, Any]) -> list[str]:
    """`[process, filament_1 .. filament_N, printer]` override lists (size N + 2).

    The printer entry stays empty on purpose: with no machine diffs Studio resets
    every machine key to the stock P2S values, which is what discards the bed
    shape, G-code and kinematics inherited from the A1 template.
    """
    process_keys = [key for key in PROCESS_DIFF_KEYS if key in settings]
    filament_keys = [key for key in FILAMENT_DIFF_KEYS if key in settings]
    slots = filament_slot_count(settings)
    return [";".join(process_keys), *([";".join(filament_keys)] * slots), ""]


def stamp_p2s_project_headers(settings: dict[str, Any]) -> dict[str, Any]:
    """Force the P2S project identity so Studio cannot rebind to another printer."""
    for key in UNSUPPORTED_KEYS:
        settings.pop(key, None)

    settings.update(P2S_PROJECT_IDENTITY)

    nozzle = settings.get("nozzle_diameter")
    variant = nozzle_variant(nozzle if nozzle else PRINTER_VARIANT_DIAMETER)
    printer_name = printer_settings_id_for(variant)
    process_name = print_settings_id_for(settings.get("layer_height", 0.2), variant)

    settings["nozzle_diameter"] = [variant]
    settings["printer_variant"] = variant
    settings["printer_settings_id"] = printer_name
    settings["print_compatible_printers"] = [printer_name]
    settings["print_settings_id"] = process_name
    settings["default_print_profile"] = process_name
    # Scalar `inherits` is what a single split preset carries; Studio overwrites it
    # per preset from inherits_group, but a matching value keeps the JSON readable
    # and covers older importers that only look at the scalar.
    settings["inherits"] = process_name

    filaments = settings.get("filament_settings_id")
    slots = filament_slot_count(settings)
    if isinstance(filaments, list) and filaments:
        cleaned = _pad((retarget_to_p2s(f) for f in filaments), slots)
    elif filaments:
        cleaned = _pad([retarget_to_p2s(filaments)], slots)
    else:
        cleaned = [generic_filament_settings_id("PLA")] * slots
    settings["filament_settings_id"] = cleaned
    settings["default_filament_profile"] = [cleaned[0]]

    settings["inherits_group"] = inherits_group(settings)
    settings["different_settings_to_system"] = different_settings_to_system(settings)
    return settings


def optional_hint(hints: Optional[dict[str, Any]], key: str, fallback: Any) -> Any:
    if hints and key in hints and hints[key] is not None:
        return hints[key]
    return fallback
