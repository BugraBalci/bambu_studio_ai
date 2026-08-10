"""OpenAI structured recommendation + rule fallback."""

from __future__ import annotations

import json
from typing import Any

from openai import OpenAI
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Filament
from app.schemas import (
    GeometryMetrics,
    PrintRecommendation,
    Purpose,
    Strength,
)
from app.services.rules import baseline_for, build_slicer_hints, clamp_recommendation


RECOMMENDATION_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "material": {"type": "string"},
        "nozzle_mm": {"type": "number"},
        "layer_height_mm": {"type": "number"},
        "wall_loops": {"type": "integer"},
        "infill_percent": {"type": "integer"},
        "infill_pattern": {"type": "string"},
        "nozzle_temp_c": {"type": "integer"},
        "bed_temp_c": {"type": "integer"},
        "supports": {"type": "boolean"},
        "brim": {"type": "boolean"},
        "matched_inventory_id": {"type": ["integer", "null"]},
        "matched_inventory_slot": {"type": ["string", "null"]},
        "missing_filament_warning": {"type": ["string", "null"]},
        "rationale": {"type": "string"},
    },
    "required": [
        "material",
        "nozzle_mm",
        "layer_height_mm",
        "wall_loops",
        "infill_percent",
        "infill_pattern",
        "nozzle_temp_c",
        "bed_temp_c",
        "supports",
        "brim",
        "matched_inventory_id",
        "matched_inventory_slot",
        "missing_filament_warning",
        "rationale",
    ],
}

# Rough ranking for conflict copy (higher = tougher / more engineering)
MATERIAL_RANK = {
    "TPU": 1,
    "PLA": 2,
    "PLA+": 3,
    "PETG": 4,
    "ABS": 5,
    "ASA": 5,
}


def _inventory_payload(db: Session) -> list[dict[str, Any]]:
    rows = db.query(Filament).order_by(Filament.id).all()
    return [
        {
            "id": r.id,
            "material": r.material,
            "color": r.color,
            "brand": r.brand,
            "slot": r.slot,
        }
        for r in rows
    ]


def _norm_material(value: str) -> str:
    m = value.upper().replace("PLA PLUS", "PLA+").replace("PLA_PLUS", "PLA+")
    if m.startswith("PLA") and "+" in m:
        return "PLA+"
    if m.startswith("PLA"):
        return "PLA" if m == "PLA" else "PLA+"
    if "PET" in m:
        return "PETG"
    if m.startswith("ASA"):
        return "ASA"
    if m.startswith("ABS"):
        return "ABS"
    if m.startswith("TPU"):
        return "TPU"
    return m


def _materials_compatible(a: str, b: str) -> bool:
    na, nb = _norm_material(a), _norm_material(b)
    if na == nb:
        return True
    return {na, nb} <= {"PLA", "PLA+"}


def _conflict_message(ideal: str, chosen: dict[str, Any]) -> str:
    ideal_n = _norm_material(ideal)
    chosen_n = _norm_material(chosen["material"])
    label = f"{chosen.get('brand', '')} {chosen_n} {chosen['color']}".strip()
    slot = chosen.get("slot") or "—"
    ir = MATERIAL_RANK.get(ideal_n, 3)
    cr = MATERIAL_RANK.get(chosen_n, 3)
    if cr < ir:
        effect = (
            f"{chosen_n} ile basmak parçayı ideal {ideal_n}'ye göre daha zayıf / kırılgan yapabilir "
            "(özellikle yük taşıyan veya dış mekan kullanımında)."
        )
    elif cr > ir:
        effect = (
            f"{chosen_n} ile basmak parçayı ideal {ideal_n}'ye göre daha sert/dayanıklı yapabilir; "
            "büzülme/warping riski veya baskı zorluğu artabilir."
        )
    else:
        effect = f"Seçilen {chosen_n}, ideal {ideal_n} ile benzer sınıfta."
    return (
        f"İdeal malzeme: {ideal_n}. Seçtiğin renkte bu yok / farklı tip seçildi: "
        f"{label} (slot {slot}). {effect}"
    )


def _filament_label(item: dict[str, Any]) -> str:
    brand = (item.get("brand") or "").strip()
    return f"{brand} {item['material']} — {item['color']}".strip()


def _apply_preferred_filament(
    data: dict[str, Any],
    inventory: list[dict[str, Any]],
    preferred_filament_id: int | None,
    color_preference: str | None,
) -> dict[str, Any]:
    ideal = data.get("ideal_material") or data.get("material")
    data["ideal_material"] = _norm_material(str(ideal))
    data["color_conflict_warning"] = None

    pick = None
    if preferred_filament_id is not None:
        pick = next((i for i in inventory if i["id"] == preferred_filament_id), None)

    if pick is None and color_preference:
        pref = color_preference.lower()
        # Prefer ideal material + color, else any with that color
        same = [
            i
            for i in inventory
            if pref in i["color"].lower() and _materials_compatible(i["material"], data["ideal_material"])
        ]
        if same:
            pick = same[0]
        else:
            any_color = [i for i in inventory if pref in i["color"].lower()]
            if any_color:
                pick = any_color[0]

    if pick is None:
        data = _match_inventory(data, inventory, color_preference)
        return data

    if not _materials_compatible(pick["material"], data["ideal_material"]):
        data["color_conflict_warning"] = _conflict_message(data["ideal_material"], pick)
        # Keep print settings for the filament the user actually wants to load
        data["material"] = _norm_material(pick["material"])
        data = clamp_recommendation(data)
    else:
        data["material"] = _norm_material(pick["material"])
        data = clamp_recommendation(data)

    data["matched_inventory_id"] = pick["id"]
    data["matched_inventory_slot"] = pick.get("slot") or None
    data["matched_filament_label"] = _filament_label(pick)
    data["missing_filament_warning"] = None
    return data


def _match_inventory(
    data: dict[str, Any],
    inventory: list[dict[str, Any]],
    color_preference: str | None,
) -> dict[str, Any]:
    material = _norm_material(str(data.get("material", "")))
    data["material"] = material
    candidates = [i for i in inventory if _materials_compatible(i["material"], material)]

    if color_preference and candidates:
        pref = color_preference.lower()
        colored = [c for c in candidates if pref in c["color"].lower()]
        if colored:
            candidates = colored
        else:
            # Color exists only on other materials
            other = [i for i in inventory if pref in i["color"].lower()]
            if other:
                data["color_conflict_warning"] = _conflict_message(material, other[0])

    if candidates:
        pick = candidates[0]
        data["matched_inventory_id"] = pick["id"]
        data["matched_inventory_slot"] = pick["slot"] or None
        data["matched_filament_label"] = _filament_label(pick)
        data["missing_filament_warning"] = None
    else:
        data["matched_inventory_id"] = None
        data["matched_inventory_slot"] = None
        data["matched_filament_label"] = None
        data["missing_filament_warning"] = (
            f"Envanterde {material} bulunamadı. Uygun filamenti AMS/slot'a takman gerekir."
        )
    return data


def _rule_only_recommendation(
    geometry: GeometryMetrics,
    purpose: Purpose,
    strength: Strength,
    inventory: list[dict[str, Any]],
    color_preference: str | None,
    notes: str | None,
    preferred_filament_id: int | None = None,
) -> PrintRecommendation:
    base = baseline_for(purpose, strength)
    if geometry.thin_feature_hint and base["nozzle_mm"] > 0.4:
        base["nozzle_mm"] = 0.4
        base["wall_loops"] = max(base["wall_loops"], 3)
    if geometry.overhang_risk_hint:
        base["supports"] = True

    data = clamp_recommendation(dict(base))
    data["ideal_material"] = data["material"]
    data = _apply_preferred_filament(data, inventory, preferred_filament_id, color_preference)

    rationale_parts = [
        f"Amaç: {purpose.value}, sağlamlık: {strength.value}.",
        f"Önerilen malzeme {data['material']} "
        f"(%{data['infill_percent']} dolgu, {data['wall_loops']} duvar).",
    ]
    if geometry.bed_fit_note:
        rationale_parts.append(geometry.bed_fit_note)
    if geometry.thin_feature_note:
        rationale_parts.append(geometry.thin_feature_note)
    if geometry.overhang_note:
        rationale_parts.append(geometry.overhang_note)
    if notes:
        data["user_notes_applied"] = notes
        rationale_parts.append(f"Senin notun dikkate alındı: “{notes}”.")
    else:
        data["user_notes_applied"] = None
    if data.get("color_conflict_warning"):
        rationale_parts.append(data["color_conflict_warning"])
    if data.get("missing_filament_warning"):
        rationale_parts.append(data["missing_filament_warning"])
    data["rationale"] = " ".join(rationale_parts)
    data["slicer_hints"] = build_slicer_hints(data)
    data["schema_version"] = "1.0"
    return PrintRecommendation(**data)


def recommend(
    db: Session,
    geometry: GeometryMetrics,
    purpose: Purpose,
    strength: Strength,
    color_preference: str | None = None,
    notes: str | None = None,
    preferred_filament_id: int | None = None,
) -> tuple[PrintRecommendation, bool, dict[str, Any]]:
    settings = get_settings()
    inventory = _inventory_payload(db)
    baseline = baseline_for(purpose, strength)

    if not settings.openai_api_key or settings.openai_api_key.startswith("sk-your"):
        rec = _rule_only_recommendation(
            geometry,
            purpose,
            strength,
            inventory,
            color_preference,
            notes,
            preferred_filament_id,
        )
        return rec, False, baseline

    client = OpenAI(api_key=settings.openai_api_key)
    system = (
        "Sen Bambu Lab P2S Combo için 3D baskı ayarı asistanısın. "
        "Kullanıcının amacı, sağlamlık profili, notu, geometri metrikleri ve filament "
        "envanterine göre güvenli baskı parametreleri öner. "
        "Yanıtı yalnızca JSON şemasına uygun ver. rationale Türkçe ve kısa olsun. "
        "Malzeme tercihlerinde baseline preferred_materials sırasını dikkate al. "
        "nozzle_mm yalnızca 0.2, 0.4, 0.6 veya 0.8 olabilir. "
        "Kullanıcı notundaki işlevsel ipuçlarını (raf, kanca, dış mekan vb.) dikkate al."
    )
    user_payload = {
        "geometry": geometry.model_dump(),
        "purpose": purpose.value,
        "strength": strength.value,
        "color_preference": color_preference,
        "preferred_filament_id": preferred_filament_id,
        "notes": notes,
        "rule_baseline": baseline,
        "inventory": inventory,
        "printer": "Bambu Lab P2S Combo",
        "printer_bed_mm": [256, 256, 256],
    }

    try:
        response = client.chat.completions.create(
            model=settings.openai_model,
            temperature=0.2,
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "print_recommendation",
                    "strict": True,
                    "schema": RECOMMENDATION_JSON_SCHEMA,
                },
            },
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
            ],
        )
        raw = response.choices[0].message.content or "{}"
        data = json.loads(raw)
        data = clamp_recommendation(data)
        data["ideal_material"] = data.get("material")
        data = _apply_preferred_filament(data, inventory, preferred_filament_id, color_preference)

        if geometry.overhang_risk_hint:
            data["supports"] = True

        if notes:
            data["user_notes_applied"] = notes
            if notes not in (data.get("rationale") or ""):
                data["rationale"] = (
                    (data.get("rationale") or "") + f" Senin notun dikkate alındı: “{notes}”."
                ).strip()
        else:
            data["user_notes_applied"] = None

        data["slicer_hints"] = build_slicer_hints(data)
        data["schema_version"] = "1.0"
        if not data.get("rationale"):
            data["rationale"] = "AI önerisi kural tabanı ile birleştirildi."
        return PrintRecommendation(**data), True, baseline
    except Exception:
        rec = _rule_only_recommendation(
            geometry,
            purpose,
            strength,
            inventory,
            color_preference,
            notes,
            preferred_filament_id,
        )
        return rec, False, baseline


def source_meta(used_llm: bool) -> tuple[str, str]:
    if used_llm:
        return (
            "OpenAI + kural motoru",
            "Önce P2S kural tablosu (amaç/sağlamlık → malzeme, dolgu, sıcaklık) hesaplanır; "
            "OpenAI API anahtarı varsa bu tabanı modele göre incelterek Türkçe gerekçe üretir. "
            "Anahtar yoksa yalnızca kural motoru çalışır.",
        )
    return (
        "Kural motoru (yerel)",
        "Öneri bu bilgisayardaki kurallardan geliyor: amaç + sağlamlık → malzeme/nozzle/dolgu/sıcaklık; "
        "STL ölçüleri ve envanter eşleşmesi de buna eklenir. OpenAI anahtarı yoksa veya API hata verirse "
        "bu mod kullanılır — rastgele değil, sabit mühendislik kurallarıdır.",
    )
