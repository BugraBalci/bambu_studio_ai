"""Color naming, AMS slot planning, and multi-material compatibility rules."""

from __future__ import annotations

from typing import Any, Iterable, Optional

from app.schemas import (
    ColorSlotMapping,
    DetectedColor,
    FilamentSlotPlan,
    FilamentWarning,
    Purpose,
    Strength,
)
from app.services.rules import MATERIAL_NOZZLE_RANGE, MATERIAL_TEMPS

PLA_FAMILY = frozenset({"PLA", "PLA+"})
ENGINEERING_FAMILY = frozenset({"PETG", "ASA", "ABS"})
TPU_FAMILY = frozenset({"TPU"})
TEMP_GAP_C = 30

STUDIO_PRESETS: dict[str, dict[str, Any]] = {
    "PLA": {
        "studio_type": "PLA",
        "filament_ids": "GFL99",
        "filament_settings_id": "Generic PLA @BBL P2S",
    },
    "PLA+": {
        "studio_type": "PLA",
        "filament_ids": "GFL99",
        "filament_settings_id": "Generic PLA @BBL P2S",
    },
    "PETG": {
        "studio_type": "PETG",
        "filament_ids": "GFG99",
        "filament_settings_id": "Generic PETG @BBL P2S",
    },
    "ABS": {
        "studio_type": "ABS",
        "filament_ids": "GFB99",
        "filament_settings_id": "Generic ABS @BBL P2S",
    },
    "ASA": {
        "studio_type": "ASA",
        "filament_ids": "GFA99",
        "filament_settings_id": "Generic ASA @BBL P2S",
    },
    "TPU": {
        "studio_type": "TPU",
        "filament_ids": "GFU99",
        "filament_settings_id": "Generic TPU @BBL P2S",
    },
}

_NAMED_COLORS: list[tuple[str, tuple[int, int, int], tuple[str, ...]]] = [
    ("Siyah", (12, 12, 14), ("black", "siyah", "noir")),
    ("Beyaz", (248, 248, 248), ("white", "beyaz", "blanc")),
    ("Gri", (128, 128, 132), ("gray", "grey", "gri")),
    ("Kırmızı", (200, 36, 36), ("red", "kırmızı", "kirmizi")),
    ("Yeşil", (42, 158, 72), ("green", "yeşil", "yesil")),
    ("Mavi", (42, 92, 198), ("blue", "mavi")),
    ("Sarı", (228, 198, 42), ("yellow", "sarı", "sari")),
    ("Turuncu", (230, 128, 32), ("orange", "turuncu")),
    ("Mor", (138, 62, 178), ("purple", "violet", "mor")),
    ("Pembe", (228, 92, 148), ("pink", "pembe")),
    ("Kahverengi", (118, 72, 42), ("brown", "kahverengi")),
    ("Camgöbeği", (42, 178, 198), ("cyan", "teal", "camgöbeği", "camgobeği")),
    ("Lacivert", (22, 42, 102), ("navy", "lacivert")),
    ("Bej", (218, 188, 142), ("beige", "bej", "tan")),
    ("Gümüş", (178, 178, 186), ("silver", "gümüş", "gumus")),
    ("Altın", (210, 172, 54), ("gold", "altın", "altin")),
]


def normalize_material(value: str) -> str:
    text = (value or "PLA").upper().replace("PLA PLUS", "PLA+").replace("PLA_PLUS", "PLA+")
    aliases = {"PLA PLUS": "PLA+", "PLA-PLUS": "PLA+", "PLA_PLUS": "PLA+"}
    text = aliases.get(text, text)
    if text.startswith("PLA") and ("+" in text or "PLUS" in text):
        return "PLA+"
    if text.startswith("PLA"):
        return "PLA"
    if "PET" in text:
        return "PETG"
    if text.startswith("ASA"):
        return "ASA"
    if text.startswith("ABS"):
        return "ABS"
    if text.startswith("TPU"):
        return "TPU"
    return text


def material_family(material: str) -> str:
    kind = normalize_material(material)
    if kind in PLA_FAMILY:
        return "pla"
    if kind in ENGINEERING_FAMILY:
        return "engineering"
    if kind in TPU_FAMILY:
        return "tpu"
    return kind.lower()


def studio_preset(material: str) -> dict[str, Any]:
    kind = normalize_material(material)
    preset = dict(STUDIO_PRESETS.get(kind, STUDIO_PRESETS["PLA"]))
    nozzle, bed = MATERIAL_TEMPS.get(kind, MATERIAL_TEMPS["PLA"])
    low, high = MATERIAL_NOZZLE_RANGE.get(kind, (190, 240))
    preset.update(
        {
            "material": kind,
            "nozzle_temp_c": int(nozzle),
            "bed_temp_c": int(bed),
            "nozzle_range_low": int(low),
            "nozzle_range_high": int(high),
        }
    )
    return preset


def rgba_hex(value: str | None) -> str:
    text = (value or "").strip().upper()
    if not text:
        return "#FFFFFFFF"
    if not text.startswith("#"):
        text = f"#{text}"
    if len(text) == 7:
        text += "FF"
    if len(text) < 9:
        text = (text + "FFFFFFFF")[:9]
    return text[:9]


def display_hex(value: str | None) -> str:
    return rgba_hex(value)[:7]


def _parse_rgb(value: str | None) -> tuple[int, int, int]:
    hex_rgb = display_hex(value).lstrip("#")
    try:
        return int(hex_rgb[0:2], 16), int(hex_rgb[2:4], 16), int(hex_rgb[4:6], 16)
    except ValueError:
        return 255, 255, 255


def color_name_from_hex(value: str | None) -> tuple[str, list[str]]:
    red, green, blue = _parse_rgb(value)
    best_name = "Gri"
    best_aliases: tuple[str, ...] = ("gray",)
    best_dist = 1e9
    for name, rgb, aliases in _NAMED_COLORS:
        dist = (red - rgb[0]) ** 2 + (green - rgb[1]) ** 2 + (blue - rgb[2]) ** 2
        if dist < best_dist:
            best_dist = dist
            best_name = name
            best_aliases = aliases
    return best_name, list(best_aliases)


def filament_label(item: dict[str, Any] | None, material: str | None = None) -> str:
    if not item:
        return f"Önerilen {material or 'PLA'}"
    slot = (item.get("slot") or "").strip() or "Envanter"
    brand = (item.get("brand") or "").strip()
    mat = item.get("material") or material or ""
    color = (item.get("color") or "").strip()
    core = " ".join(part for part in (slot, brand, mat) if part)
    return f"{core} — {color}" if color else core


def detected_colors_from_hexes(
    palette: Iterable[str],
    part_counts: Optional[dict[str, int]] = None,
) -> list[DetectedColor]:
    counts = part_counts or {}
    used_names: dict[str, int] = {}
    colors: list[DetectedColor] = []
    for index, raw in enumerate(list(palette)):
        hex_rgba = rgba_hex(raw)
        hex_rgb = hex_rgba[:7]
        base, aliases = color_name_from_hex(hex_rgba)
        seen = used_names.get(base, 0) + 1
        used_names[base] = seen
        name = base if seen == 1 else f"{base} {seen}"
        part_count = counts.get(raw, 0) or counts.get(hex_rgba, 0) or counts.get(hex_rgb, 0) or 1
        colors.append(
            DetectedColor(
                id=f"c{index}",
                hex=hex_rgb,
                hex_rgba=hex_rgba,
                name=name,
                slot_index=index,
                extruder=index + 1,
                part_count=int(part_count),
                aliases=list(aliases) + [base.lower()],
            )
        )
    return colors


def _inventory_by_id(inventory: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    return {int(row["id"]): row for row in inventory if row.get("id") is not None}


def _mapping_dict(
    mappings: list[ColorSlotMapping] | list[dict[str, Any]] | None,
) -> dict[str, Optional[int]]:
    mapped: dict[str, Optional[int]] = {}
    for item in mappings or []:
        if isinstance(item, ColorSlotMapping):
            mapped[item.color_id] = item.filament_id
        else:
            mapped[str(item.get("color_id"))] = item.get("filament_id")
    return mapped


def plan_filament_slots(
    colors: list[DetectedColor],
    mappings: list[ColorSlotMapping] | list[dict[str, Any]] | None,
    inventory: list[dict[str, Any]],
    fallback_material: str,
) -> list[FilamentSlotPlan]:
    by_id = _inventory_by_id(inventory)
    mapped = _mapping_dict(mappings)
    fallback = studio_preset(fallback_material)
    slots: list[FilamentSlotPlan] = []
    for color in colors:
        filament_id = mapped.get(color.id)
        row = by_id.get(int(filament_id)) if filament_id is not None else None
        material = normalize_material(row["material"]) if row else fallback["material"]
        preset = studio_preset(material)
        slots.append(
            FilamentSlotPlan(
                color_id=color.id,
                color_hex=color.hex,
                color_name=color.name,
                extruder=color.extruder,
                filament_id=int(filament_id) if filament_id is not None and row else None,
                material=preset["material"],
                studio_type=preset["studio_type"],
                nozzle_temp_c=int(preset["nozzle_temp_c"]),
                bed_temp_c=int(preset["bed_temp_c"]),
                nozzle_range_low=int(preset["nozzle_range_low"]),
                nozzle_range_high=int(preset["nozzle_range_high"]),
                filament_ids=str(preset["filament_ids"]),
                filament_settings_id=str(preset["filament_settings_id"]),
                label=filament_label(row, preset["material"]),
                slot=(row.get("slot") or "") if row else "",
            )
        )
    return slots


def validate_filament_slots(
    slots: list[FilamentSlotPlan],
    *,
    purpose: Purpose,
    strength: Strength,
    ideal_material: str,
) -> list[FilamentWarning]:
    if not slots:
        return []

    warnings: list[FilamentWarning] = []
    ideal = normalize_material(ideal_material)
    families = {material_family(slot.material) for slot in slots}

    if "pla" in families and "engineering" in families:
        pla_slot = next(slot for slot in slots if material_family(slot.material) == "pla")
        eng_slot = next(slot for slot in slots if material_family(slot.material) == "engineering")
        reasons = [
            "PLA/PLA+ ile PETG/ASA aynı yapısal gövdede kaynaşmaz; katman ayrılması ve yapısal göçme riski yüksektir.",
            f"{pla_slot.color_name} → {pla_slot.label}; {eng_slot.color_name} → {eng_slot.label}.",
        ]
        warnings.append(
            FilamentWarning(
                code="material_mix",
                severity="high",
                color_id=pla_slot.color_id,
                color_name=pla_slot.color_name,
                filament_label=pla_slot.label,
                reasons=reasons,
                message=(
                    f"Uyarı: {pla_slot.color_name} için {pla_slot.label} seçmek önerilmez çünkü: "
                    f"{reasons[0]} Yine de devam etmek istiyor musun?"
                ),
            )
        )

    if "tpu" in families and len(families) > 1:
        tpu_slot = next(slot for slot in slots if material_family(slot.material) == "tpu")
        reasons = [
            "TPU diğer sert filamentlerle (PLA/PETG/ASA) aynı gövdede güvenilir şekilde kaynaşmaz.",
        ]
        warnings.append(
            FilamentWarning(
                code="material_mix_tpu",
                severity="high",
                color_id=tpu_slot.color_id,
                color_name=tpu_slot.color_name,
                filament_label=tpu_slot.label,
                reasons=reasons,
                message=(
                    f"Uyarı: {tpu_slot.color_name} için {tpu_slot.label} seçmek önerilmez çünkü: "
                    f"{reasons[0]} Yine de devam etmek istiyor musun?"
                ),
            )
        )

    functional_job = purpose == Purpose.functional or strength == Strength.strong
    if functional_job and ideal in ENGINEERING_FAMILY:
        for slot in slots:
            if slot.material not in PLA_FAMILY:
                continue
            reasons = [
                "Model işlevsel / yüksek mukavemet için analiz edildi; dekoratif PLA, önerilen PETG kadar yük taşımaz.",
            ]
            warnings.append(
                FilamentWarning(
                    code="functional_purpose",
                    severity="advisory",
                    color_id=slot.color_id,
                    color_name=slot.color_name,
                    filament_label=slot.label,
                    reasons=reasons,
                    message=(
                        f"Uyarı: {slot.color_name} için {slot.label} seçmek önerilmez çünkü: "
                        f"{reasons[0]} Yine de devam etmek istiyor musun?"
                    ),
                )
            )

    temps = [int(slot.nozzle_temp_c) for slot in slots]
    gap = max(temps) - min(temps)
    if gap > TEMP_GAP_C:
        hot = max(slots, key=lambda slot: slot.nozzle_temp_c)
        cold = min(slots, key=lambda slot: slot.nozzle_temp_c)
        reasons = [
            f"Seçilen filamentlerin nozul sıcaklıkları {gap}°C farklı (> {TEMP_GAP_C}°C); "
            "renk değişiminde purge döngüleri uzar ve baskı süresi artar.",
            f"{cold.label} {cold.nozzle_temp_c}°C / {hot.label} {hot.nozzle_temp_c}°C.",
        ]
        warnings.append(
            FilamentWarning(
                code="temperature_gap",
                severity="warn",
                color_id=hot.color_id,
                color_name=hot.color_name,
                filament_label=hot.label,
                reasons=reasons,
                message=(
                    f"Uyarı: {hot.color_name} için {hot.label} seçmek önerilmez çünkü: "
                    f"{reasons[0]} Yine de devam etmek istiyor musun?"
                ),
            )
        )

    return warnings
