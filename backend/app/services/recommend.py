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


def _match_inventory(
    data: dict[str, Any],
    inventory: list[dict[str, Any]],
    color_preference: str | None,
) -> dict[str, Any]:
    material = str(data.get("material", "")).upper()
    candidates = [i for i in inventory if i["material"].upper() == material or (
        material == "PLA+" and i["material"].upper() in ("PLA+", "PLA PLUS")
    )]
    if not candidates:
        # softer match: PLA+ accepts PLA
        if material in ("PLA+", "PLA"):
            candidates = [i for i in inventory if i["material"].upper().startswith("PLA")]
        elif material == "PETG":
            candidates = [i for i in inventory if "PET" in i["material"].upper()]

    if color_preference and candidates:
        pref = color_preference.lower()
        colored = [c for c in candidates if pref in c["color"].lower()]
        if colored:
            candidates = colored

    if candidates:
        pick = candidates[0]
        data["matched_inventory_id"] = pick["id"]
        data["matched_inventory_slot"] = pick["slot"] or None
        data["missing_filament_warning"] = None
    else:
        data["matched_inventory_id"] = None
        data["matched_inventory_slot"] = None
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
) -> PrintRecommendation:
    base = baseline_for(purpose, strength)
    if geometry.thin_feature_hint and base["nozzle_mm"] > 0.4:
        base["nozzle_mm"] = 0.4
        base["wall_loops"] = max(base["wall_loops"], 3)
    if geometry.overhang_risk_hint:
        base["supports"] = True

    data = clamp_recommendation(dict(base))
    data = _match_inventory(data, inventory, color_preference)

    rationale_parts = [
        f"Amaç: {purpose.value}, sağlamlık: {strength.value}.",
        f"Önerilen malzeme {data['material']} "
        f"(%{data['infill_percent']} dolgu, {data['wall_loops']} duvar).",
    ]
    if geometry.thin_feature_note:
        rationale_parts.append(geometry.thin_feature_note)
    if geometry.overhang_note:
        rationale_parts.append(geometry.overhang_note)
    if notes:
        rationale_parts.append(f"Not: {notes}")
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
) -> tuple[PrintRecommendation, bool, dict[str, Any]]:
    settings = get_settings()
    inventory = _inventory_payload(db)
    baseline = baseline_for(purpose, strength)

    if not settings.openai_api_key or settings.openai_api_key.startswith("sk-your"):
        rec = _rule_only_recommendation(
            geometry, purpose, strength, inventory, color_preference, notes
        )
        return rec, False, baseline

    client = OpenAI(api_key=settings.openai_api_key)
    system = (
        "Sen Bambu Lab P2S için 3D baskı ayarı asistanısın. "
        "Kullanıcının amacı ve sağlamlık profiline, geometri metriklerine ve filament "
        "envanterine göre güvenli baskı parametreleri öner. "
        "Yanıtı yalnızca JSON şemasına uygun ver. rationale Türkçe ve kısa olsun. "
        "Malzeme tercihlerinde baseline preferred_materials sırasını dikkate al ama "
        "envanterde varsa eşleştir. nozzle_mm yalnızca 0.2, 0.4, 0.6 veya 0.8 olabilir."
    )
    user_payload = {
        "geometry": geometry.model_dump(),
        "purpose": purpose.value,
        "strength": strength.value,
        "color_preference": color_preference,
        "notes": notes,
        "rule_baseline": baseline,
        "inventory": inventory,
        "printer": "Bambu Lab P2S",
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
        # Prefer LLM inventory pick if valid, else re-match
        inv_ids = {i["id"] for i in inventory}
        if data.get("matched_inventory_id") not in inv_ids:
            data = _match_inventory(data, inventory, color_preference)
        else:
            pick = next(i for i in inventory if i["id"] == data["matched_inventory_id"])
            data["matched_inventory_slot"] = pick.get("slot") or data.get("matched_inventory_slot")
            if pick["material"].upper() != str(data["material"]).upper() and not (
                data["material"].upper().startswith("PLA") and pick["material"].upper().startswith("PLA")
            ):
                data = _match_inventory(data, inventory, color_preference)

        if geometry.overhang_risk_hint:
            data["supports"] = True

        data["slicer_hints"] = build_slicer_hints(data)
        data["schema_version"] = "1.0"
        if not data.get("rationale"):
            data["rationale"] = "AI önerisi kural tabanı ile birleştirildi."
        return PrintRecommendation(**data), True, baseline
    except Exception:
        rec = _rule_only_recommendation(
            geometry, purpose, strength, inventory, color_preference, notes
        )
        return rec, False, baseline
