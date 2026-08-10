"""Rule baselines for purpose × strength → print parameters."""

from __future__ import annotations

from typing import Any

from app.schemas import Purpose, Strength

# Typical safe temps for common filaments (nozzle, bed)
MATERIAL_TEMPS: dict[str, tuple[int, int]] = {
    "PLA": (210, 60),
    "PLA+": (215, 60),
    "PETG": (245, 80),
    "ABS": (260, 100),
    "ASA": (260, 100),
    "TPU": (230, 50),
}

MATERIAL_NOZZLE_RANGE: dict[str, tuple[int, int]] = {
    "PLA": (190, 230),
    "PLA+": (200, 230),
    "PETG": (230, 260),
    "ABS": (240, 280),
    "ASA": (240, 280),
    "TPU": (210, 250),
}

MATERIAL_BED_RANGE: dict[str, tuple[int, int]] = {
    "PLA": (50, 70),
    "PLA+": (50, 70),
    "PETG": (70, 90),
    "ABS": (90, 110),
    "ASA": (90, 110),
    "TPU": (40, 60),
}


def baseline_for(purpose: Purpose, strength: Strength) -> dict[str, Any]:
    """Deterministic starting point before LLM refinement / clamp."""
    preferred_materials: list[str]
    if purpose == Purpose.outdoor:
        preferred_materials = ["PETG", "ASA", "ABS"]
    elif purpose == Purpose.functional:
        preferred_materials = ["PETG", "ABS", "PLA+"]
    else:  # decorative
        preferred_materials = ["PLA", "PLA+"]

    if strength == Strength.weak:
        walls, infill, layer = 2, 12, 0.28
    elif strength == Strength.medium:
        walls, infill, layer = 3, 20, 0.20
    else:
        walls, infill, layer = 4, 40, 0.16

    if purpose == Purpose.decorative and strength != Strength.strong:
        preferred_nozzle = 0.4
    elif strength == Strength.strong or purpose == Purpose.functional:
        preferred_nozzle = 0.6 if strength == Strength.strong else 0.4
    else:
        preferred_nozzle = 0.4

    material = preferred_materials[0]
    nozzle_temp, bed_temp = MATERIAL_TEMPS[material]

    return {
        "preferred_materials": preferred_materials,
        "material": material,
        "nozzle_mm": preferred_nozzle,
        "layer_height_mm": layer,
        "wall_loops": walls,
        "infill_percent": infill,
        "infill_pattern": "gyroid" if strength == Strength.strong else "grid",
        "nozzle_temp_c": nozzle_temp,
        "bed_temp_c": bed_temp,
        "supports": False,
        "brim": purpose == Purpose.functional or strength == Strength.strong,
    }


def clamp_recommendation(data: dict[str, Any]) -> dict[str, Any]:
    """Clamp temps and numeric ranges to safe values."""
    material = str(data.get("material", "PLA")).upper().replace("PLA+", "PLA+")
    # normalize common variants
    aliases = {
        "PLA PLUS": "PLA+",
        "PLA_PLUS": "PLA+",
        "PLA-PLUS": "PLA+",
    }
    material = aliases.get(material, material)
    if material not in MATERIAL_TEMPS:
        # try stripping plus etc.
        if material.startswith("PLA"):
            material = "PLA+" if "+" in material or "PLUS" in material else "PLA"
        elif material.startswith("PET"):
            material = "PETG"
        else:
            material = "PLA"

    data["material"] = material

    n_lo, n_hi = MATERIAL_NOZZLE_RANGE[material]
    b_lo, b_hi = MATERIAL_BED_RANGE[material]
    default_n, default_b = MATERIAL_TEMPS[material]

    try:
        data["nozzle_temp_c"] = int(max(n_lo, min(n_hi, int(data.get("nozzle_temp_c", default_n)))))
    except (TypeError, ValueError):
        data["nozzle_temp_c"] = default_n

    try:
        data["bed_temp_c"] = int(max(b_lo, min(b_hi, int(data.get("bed_temp_c", default_b)))))
    except (TypeError, ValueError):
        data["bed_temp_c"] = default_b

    nozzle = float(data.get("nozzle_mm", 0.4))
    if nozzle not in (0.2, 0.4, 0.6, 0.8):
        nozzle = 0.4
    data["nozzle_mm"] = nozzle

    layer = float(data.get("layer_height_mm", 0.2))
    # layer height should be ~25–75% of nozzle
    layer = max(nozzle * 0.25, min(nozzle * 0.75, layer))
    data["layer_height_mm"] = round(layer, 3)

    data["wall_loops"] = int(max(1, min(8, int(data.get("wall_loops", 3)))))
    data["infill_percent"] = int(max(0, min(100, int(data.get("infill_percent", 20)))))
    data["supports"] = bool(data.get("supports", False))
    data["brim"] = bool(data.get("brim", False))
    if not data.get("infill_pattern"):
        data["infill_pattern"] = "grid"

    return data


def build_slicer_hints(data: dict[str, Any]) -> dict[str, Any]:
    """Map recommendation fields to Bambu/Orca-style keys for Phase B CLI."""
    return {
        "filament_type": data["material"],
        "nozzle_diameter": data["nozzle_mm"],
        "layer_height": data["layer_height_mm"],
        "wall_loops": data["wall_loops"],
        "sparse_infill_density": data["infill_percent"],
        "sparse_infill_pattern": data["infill_pattern"],
        "nozzle_temperature": data["nozzle_temp_c"],
        "bed_temperature": data["bed_temp_c"],
        "enable_support": data["supports"],
        "brim_width": 5 if data["brim"] else 0,
        "printer_model": "Bambu Lab P2S",
    }
