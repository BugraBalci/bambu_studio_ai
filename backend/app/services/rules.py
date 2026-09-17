"""Rule baselines for purpose × strength → print parameters."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from app.schemas import DetailTier, GeometryMetrics, Purpose, Strength

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from slicer_pipeline.defects import (  # noqa: E402
    DEFAULT_LINE_WIDTH_MM,
    FINE_TEXT_EXPLANATION_TR,
    FINE_TEXT_LAYER_HEIGHT_MM,
    FINE_TEXT_LINE_WIDTH_MM,
    FUZZY_SKIN_RECOMMENDED,
    HULL_LINE_EXPLANATION_TR,
    MINIATURE_BRIM_TYPE,
    MINIATURE_BRIM_WIDTH_MM,
    MINIATURE_EXPLANATION_TR,
    MINIATURE_LAYER_HEIGHT_MM,
    MINIATURE_OUTER_WALL_LINE_WIDTH_MM,
    MINIATURE_OUTER_WALL_SPEED_MM_S,
    miniature_brim_width_mm,
    miniature_explanation_tr,
    walls_for_shell_thickness,
)

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

# Conservative P2S Combo speed bands (mm/s)
SPEED_BY_TIER: dict[DetailTier, dict[str, int]] = {
    DetailTier.low: {
        "print_speed_mm_s": 200,
        "outer_wall_speed_mm_s": 120,
        "sparse_infill_speed_mm_s": 220,
    },
    DetailTier.medium: {
        "print_speed_mm_s": 150,
        "outer_wall_speed_mm_s": 80,
        "sparse_infill_speed_mm_s": 180,
    },
    DetailTier.high: {
        "print_speed_mm_s": 100,
        "outer_wall_speed_mm_s": 50,
        "sparse_infill_speed_mm_s": 120,
    },
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


def apply_geometry_overrides(baseline: dict[str, Any], geometry: GeometryMetrics) -> dict[str, Any]:
    """Fold mesh detail / thin / overhang into speeds, layer, nozzle, supports."""
    data = dict(baseline)
    tier = geometry.detail_tier
    if isinstance(tier, str):
        tier = DetailTier(tier)

    speeds = SPEED_BY_TIER[tier]
    data["detail_tier"] = tier.value
    data["print_speed_mm_s"] = speeds["print_speed_mm_s"]
    data["outer_wall_speed_mm_s"] = speeds["outer_wall_speed_mm_s"]
    data["sparse_infill_speed_mm_s"] = speeds["sparse_infill_speed_mm_s"]

    layer = float(data.get("layer_height_mm", 0.2))
    nozzle = float(data.get("nozzle_mm", 0.4))
    reasons: list[str] = []

    if tier == DetailTier.low:
        layer = max(layer, 0.24)
        reasons.append(
            "Yüzey sade → kalın katman ve yüksek hız (dış duvar "
            f"{speeds['outer_wall_speed_mm_s']} mm/s)."
        )
    elif tier == DetailTier.high:
        layer = min(layer, 0.16)
        nozzle = min(nozzle, 0.4)
        reasons.append(
            "Yoğun detay → ince katman, 0.4 mm nozzle ve yavaş dış duvar "
            f"({speeds['outer_wall_speed_mm_s']} mm/s)."
        )
    else:
        reasons.append(
            "Orta detay → dengeli hız "
            f"(dış duvar {speeds['outer_wall_speed_mm_s']} mm/s)."
        )

    if geometry.thin_feature_hint:
        nozzle = min(nozzle, 0.4)
        data["wall_loops"] = int(data.get("wall_loops", 3)) + 1
        # bump speed tier down one step if we were on low
        if tier == DetailTier.low:
            data["print_speed_mm_s"] = SPEED_BY_TIER[DetailTier.medium]["print_speed_mm_s"]
            data["outer_wall_speed_mm_s"] = SPEED_BY_TIER[DetailTier.medium]["outer_wall_speed_mm_s"]
            data["sparse_infill_speed_mm_s"] = SPEED_BY_TIER[DetailTier.medium][
                "sparse_infill_speed_mm_s"
            ]
        reasons.append("İnce bölgeler → nozzle ≤ 0.4 mm, +1 duvar, hız kısildi.")

    if getattr(geometry, "fine_text_detected", False):
        layer = min(layer, FINE_TEXT_LAYER_HEIGHT_MM)
        nozzle = min(nozzle, 0.4)
        data["wall_generator"] = "arachne"
        data["line_width_mm"] = FINE_TEXT_LINE_WIDTH_MM
        data["fine_text_detected"] = True
        data["fine_detail_optimization"] = True
        data["fine_text_explanation"] = FINE_TEXT_EXPLANATION_TR
        reasons.append(FINE_TEXT_EXPLANATION_TR)

    if getattr(geometry, "hull_line_risk", False):
        line_w = float(data.get("line_width_mm") or DEFAULT_LINE_WIDTH_MM)
        needed = walls_for_shell_thickness(line_w)
        data["wall_loops"] = max(int(data.get("wall_loops", 3)), needed)
        data["hull_line_risk"] = True
        data["hull_line_mitigation"] = True
        data["hull_line_explanation"] = HULL_LINE_EXPLANATION_TR
        data["fuzzy_skin_recommended"] = True
        data["fuzzy_skin_settings"] = dict(FUZZY_SKIN_RECOMMENDED)
        reasons.append(HULL_LINE_EXPLANATION_TR)

    need_support = bool(getattr(geometry, "support_required", False) or geometry.overhang_risk_hint)
    if need_support:
        data["supports"] = True
        stype = getattr(geometry, "recommended_support_type", None) or "tree(auto)"
        if stype in ("none", "", None):
            stype = "tree(auto)"
        data["support_type"] = stype
        data["outer_wall_speed_mm_s"] = min(int(data["outer_wall_speed_mm_s"]), 60)
        data["print_speed_mm_s"] = min(int(data["print_speed_mm_s"]), 120)
        reasons.append("Overhang riski → support açık, hız düşürüldü.")

    if getattr(geometry, "is_miniature", False):
        layer = min(layer, MINIATURE_LAYER_HEIGHT_MM)
        nozzle = min(nozzle, 0.4)
        data["supports"] = False
        data["brim"] = True
        brim_w = miniature_brim_width_mm(geometry.bounding_box_mm)
        data["brim_type"] = MINIATURE_BRIM_TYPE
        data["brim_width_mm"] = brim_w
        data["outer_wall_speed_mm_s"] = MINIATURE_OUTER_WALL_SPEED_MM_S
        existing_w = data.get("outer_wall_line_width_mm")
        if existing_w is None and data.get("line_width_mm") is not None:
            existing_w = data["line_width_mm"]
        try:
            current = float(existing_w) if existing_w is not None else MINIATURE_OUTER_WALL_LINE_WIDTH_MM
        except (TypeError, ValueError):
            current = MINIATURE_OUTER_WALL_LINE_WIDTH_MM
        data["outer_wall_line_width_mm"] = min(current, MINIATURE_OUTER_WALL_LINE_WIDTH_MM)
        data["is_miniature"] = True
        data["miniature_optimization"] = True
        data["miniature_explanation"] = miniature_explanation_tr(brim_w)
        reasons.append(data["miniature_explanation"])

    if geometry.detail_note:
        reasons.insert(0, geometry.detail_note)

    data["nozzle_mm"] = nozzle
    data["layer_height_mm"] = layer
    data["speed_rationale"] = " ".join(reasons)
    return data


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
    if data.get("is_miniature"):
        data["supports"] = False
        data["brim"] = True
        data["brim_type"] = data.get("brim_type") or MINIATURE_BRIM_TYPE
        data["outer_wall_speed_mm_s"] = MINIATURE_OUTER_WALL_SPEED_MM_S
        try:
            data["brim_width_mm"] = int(
                max(5, min(10, int(data.get("brim_width_mm") or MINIATURE_BRIM_WIDTH_MM)))
            )
        except (TypeError, ValueError):
            data["brim_width_mm"] = MINIATURE_BRIM_WIDTH_MM
    if data.get("outer_wall_line_width_mm") is not None:
        try:
            data["outer_wall_line_width_mm"] = round(float(data["outer_wall_line_width_mm"]), 3)
        except (TypeError, ValueError):
            data["outer_wall_line_width_mm"] = None
    if not data.get("infill_pattern"):
        data["infill_pattern"] = "grid"
    if data.get("line_width_mm") is not None:
        try:
            data["line_width_mm"] = round(float(data["line_width_mm"]), 3)
        except (TypeError, ValueError):
            data["line_width_mm"] = None

    # speed clamps (P2S-safe band)
    for key, default, lo, hi in (
        ("print_speed_mm_s", 150, 40, 300),
        ("outer_wall_speed_mm_s", 80, 20, 200),
        ("sparse_infill_speed_mm_s", 180, 40, 320),
    ):
        try:
            data[key] = int(max(lo, min(hi, int(data.get(key, default)))))
        except (TypeError, ValueError):
            data[key] = default

    if not data.get("detail_tier"):
        data["detail_tier"] = DetailTier.medium.value
    if not data.get("speed_rationale"):
        data["speed_rationale"] = "Varsayılan P2S hız bandı."

    return data


MATERIAL_TEMP_WHY: dict[str, str] = {
    "PLA": "PLA akışkanlığı ve PEI tabla yapışması için.",
    "PLA+": "PLA+ viskozitesi ve PEI tabla tutunması için hafif yüksek nozül.",
    "PETG": "PETG'nin daha yüksek erime bandı ve tabla yapışması için.",
    "ABS": "ABS warping'ini azaltmak için sıcak tabla / yüksek nozül.",
    "ASA": "ASA UV/dış mekan filamentinin erime ve tabla bandı.",
    "TPU": "Esnek TPU akışı ve düşük tabla ısısı için.",
}


def build_setting_reasons(data: dict[str, Any], geometry: GeometryMetrics) -> dict[str, str]:
    """Per-setting engineering rationale shown in the recommendation panel."""
    layer = float(data.get("layer_height_mm") or 0.2)
    nozzle = float(data.get("nozzle_mm") or 0.4)
    material = str(data.get("material") or "PLA")
    n_temp = int(data.get("nozzle_temp_c") or 210)
    b_temp = int(data.get("bed_temp_c") or 60)
    outer = int(data.get("outer_wall_speed_mm_s") or 80)
    print_speed = int(data.get("print_speed_mm_s") or 150)
    infill_speed = int(data.get("sparse_infill_speed_mm_s") or 180)
    walls = int(data.get("wall_loops") or 3)
    infill = int(data.get("infill_percent") or 20)
    pattern = str(data.get("infill_pattern") or "grid")
    supports = bool(data.get("supports"))
    support_type = str(data.get("support_type") or "none")
    brim = bool(data.get("brim"))
    tier = str(data.get("detail_tier") or getattr(geometry, "detail_tier", "medium"))
    if hasattr(tier, "value"):
        tier = tier.value

    if getattr(geometry, "is_miniature", False) or data.get("is_miniature"):
        layer_why = (
            f"{layer:.2f} mm seçildi: Minyatür model — merdivenlenmeyi kaldırmak için "
            "ince katman (0.12 mm). "
            + (data.get("miniature_explanation") or MINIATURE_EXPLANATION_TR)
        )
    elif getattr(geometry, "fine_text_detected", False) or data.get("fine_text_detected"):
        layer_why = (
            f"{layer:.2f} mm seçildi: İnce yazı / mikro detay için dikey çözünürlük. "
            "Arachne ile 0.12 mm (gerekirse 0.08 mm) harf kenarlarını korur."
        )
    elif layer <= 0.16:
        layer_why = (
            f"{layer:.2f} mm seçildi: Kavisli yüzeylerde merdivenlenmeyi önlerken baskı süresini dengeler. "
            "(Not: 0.08–0.12 mm mikro figürlerde, 0.24–0.28 mm ise kaba mekanik kutularda kullanılır.)"
        )
    elif layer >= 0.24:
        layer_why = (
            f"{layer:.2f} mm seçildi: Kaba mekanik gövdelerde süreyi kısaltır; merdiven etkisi kabul edilir. "
            "(Not: 0.08–0.12 mm mikro figürlerde, 0.16 mm kavisli yüzeylerde dengeli seçimdir.)"
        )
    else:
        layer_why = (
            f"{layer:.2f} mm seçildi: Kavisli yüzeylerde merdivenlenmeyi önlerken baskı süresini dengeler. "
            "(Not: 0.08–0.12 mm mikro figürlerde, 0.24–0.28 mm ise kaba mekanik kutularda kullanılır.)"
        )

    temp_why = MATERIAL_TEMP_WHY.get(material, f"{material} için güvenli nozül/tabla bandı.")
    temperature = (
        f"{n_temp}°C nozül / {b_temp}°C tabla seçildi: {temp_why}"
    )

    if getattr(geometry, "is_miniature", False) or data.get("is_miniature"):
        outer_why = (
            f"{outer} mm/s dış duvar seçildi: Minyatür çevrelerde soğuma ve titreşim "
            "artefaktlarını kesmek için hız 35 mm/s'ye çekildi."
        )
    elif supports or getattr(geometry, "support_required", False):
        outer_why = (
            f"{outer} mm/s dış duvar seçildi: Dik overhang soğuması ve yüzey hatalarını "
            "önlemek için hız düşürüldü."
        )
    elif tier == "high":
        outer_why = (
            f"{outer} mm/s dış duvar seçildi: Yoğun mesh detayını korumak için yavaş dış duvar."
        )
    else:
        outer_why = (
            f"{outer} mm/s dış duvar seçildi: {tier} detay profiline göre P2S güvenli hız bandı."
        )

    print_why = (
        f"{print_speed} mm/s genel hız: {tier} detay ve {material} akışına göre P2S Combo bandı."
    )
    infill_speed_why = f"{infill_speed} mm/s dolgu hızı: iç yapıda süreyi korurken dış yüzeyi yavaş bırakır."

    geo_reason = getattr(geometry, "support_reason", None) or ""
    if getattr(geometry, "is_miniature", False) or data.get("is_miniature"):
        support_why = (
            "Support kapalı: minyatür alt yüzeylerde destek izi/kaynaşması modeli bozar; "
            "0.12 mm katmanda köprü ve overhang destek olmadan daha temiz basılır."
        )
    elif supports:
        type_label = (
            "tree(auto) — organik/izole overhang"
            if "tree" in support_type
            else "grid / normal(auto) — geniş düz köprüler"
        )
        support_why = geo_reason or (
            f"Support açık ({type_label}). 45° altı overhang alanı eşiği aşıldı."
        )
    else:
        support_why = geo_reason or (
            "Support kapalı: 45° overhang alanı eşiğin altında; tabla teması support sayılmaz."
        )

    nozzle_bits = [f"{nozzle} mm nozzle"]
    if getattr(geometry, "thin_feature_hint", False):
        nozzle_bits.append("ince özellikler için ≤ 0.4 mm")
    if tier == "high":
        nozzle_bits.append("yüzey detayı için ince hat")
    nozzle_why = " seçildi: " + ", ".join(nozzle_bits[1:] or ["P2S Combo standart nozül"]) + "."
    nozzle_why = f"{nozzle} mm{nozzle_why}"
    if getattr(geometry, "hull_line_risk", False) or data.get("hull_line_risk"):
        walls_why = (
            f"{walls} duvar seçildi: Hull Line (gövde çizgisi) riski — iç taban-duvar "
            "birleşiminde kabuk 2.0 mm altına düşmesin diye çevre kalınlığı artırıldı. "
            "Alternatif kamufle: Fuzzy Skin contour."
        )
    elif walls <= 2:
        walls_why = (
            f"{walls} duvar seçildi: Hızlı prototip kabuğu — süre kısalır ama iç dolgu dış yüzeye "
            "gölge yapabilir, ince uzuvlar zayıf kalır. (Not: Figürlerde 3 duvar; vida delikli ve "
            "yük taşıyan mekanik parçalarda 5+ duvar önerilir.)"
        )
    elif walls >= 5:
        walls_why = (
            f"{walls} duvar seçildi: Vida delikli / yük taşıyan mekanik parçalar için kalın kabuk. "
            "İç dolgunun dış yüzeye gölge yapmasını da keser. (Not: Hızlı prototiplerde 2 duvar; "
            "figür ve genel parçalarda 3 duvar yeterlidir.)"
        )
    else:
        walls_why = (
            f"{walls} duvar seçildi: Figürün iç dolgusunun (infill) dış yüzeye gölge yapmasını engeller "
            "ve kollar/ince uzuvlar için ideal kabuk dayanımı sağlar. (Not: Hızlı prototiplerde 2 duvar; "
            "vida delikli ve yük taşıyan mekanik parçalarda 5+ duvar önerilir.)"
        )

    pattern_l = pattern.lower()
    gyroid = "gyroid" in pattern_l or "gyroid" in pattern_l
    if infill >= 40:
        infill_why = (
            f"%{infill} {pattern}: Mukavemet odaklı dolgu. Mekanik parçalarda %{infill} "
            f"{'Gyroid' if gyroid else pattern} iyi bir rijitlik/malzeme dengesidir. "
            "(Not: Figür ve süs parçalarında %12–20 Grid yeterlidir.)"
        )
    elif gyroid:
        infill_why = (
            f"%{infill} {pattern}: Mukavemet ve malzeme dengesi. Izotropik Gyroid, darbe ve bükülmede "
            "Grid'den daha tutarlıdır. Mekanik parçalarda %40+ Gyroid önerilir."
        )
    else:
        infill_why = (
            f"%{infill} {pattern}: Mukavemet ve malzeme dengesi. Mekanik parçalarda %40+ Gyroid önerilir."
        )

    return {
        "material": f"{material} seçildi: amaç/sağlamlık profili ve envanter eşlemesine göre.",
        "nozzle": nozzle_why,
        "layer_height": layer_why,
        "walls": walls_why,
        "infill": infill_why,
        "temperature": temperature,
        "print_speed": print_why,
        "outer_wall_speed": outer_why,
        "infill_speed": infill_speed_why,
        "supports": support_why,
        "brim": (
            (
                data.get("miniature_explanation")
                or getattr(geometry, "miniature_explanation", "")
                or MINIATURE_EXPLANATION_TR
            )
            if getattr(geometry, "is_miniature", False) or data.get("is_miniature")
            else (
                "Brim açık: tabla tutunması ve warping riskini azaltmak için."
                if brim
                else "Brim kapalı: taban alanı yeterli; extra etek gerekmedi."
            )
        ),
        "miniature": (
            data.get("miniature_explanation")
            or getattr(geometry, "miniature_explanation", "")
            or MINIATURE_EXPLANATION_TR
        )
        if getattr(geometry, "is_miniature", False) or data.get("is_miniature")
        else "Minyatür kuralı kapalı: model 35 mm eşiğinin üzerinde.",
        "outer_wall_line_width": (
            f"{data.get('outer_wall_line_width_mm') or data.get('line_width_mm') or 0.42} mm "
            "dış duvar hattı: minyatür köşeleri 0.4 mm nozzleda daha keskin çözmek için "
            "0.35 mm'ye çekildi."
            if getattr(geometry, "is_miniature", False) or data.get("is_miniature")
            else (
                "Arachne 0.3 mm hat: ince yazı/mikro kontur."
                if data.get("fine_text_detected") or getattr(geometry, "fine_text_detected", False)
                else "Varsayılan 0.42 mm dış duvar hattı."
            )
        ),
        "hull_line": (
            getattr(geometry, "hull_line_explanation", "")
            or HULL_LINE_EXPLANATION_TR
        )
        if getattr(geometry, "hull_line_risk", False) or data.get("hull_line_risk")
        else "Hull Line riski yok: iç taban-ince duvar geçişi tespit edilmedi.",
        "fine_text": (
            getattr(geometry, "fine_text_explanation", "")
            or FINE_TEXT_EXPLANATION_TR
        )
        if getattr(geometry, "fine_text_detected", False) or data.get("fine_text_detected")
        else "İnce yazı / mikro detay yok: klasik duvar motoru yeterli.",
        "wall_generator": (
            "Arachne (değişken hat genişliği) seçildi: 0.45 mm altındaki harf ve mikro "
            "konturların dilimlenirken düşmesini önler."
            if str(data.get("wall_generator") or "") == "arachne"
            or getattr(geometry, "fine_text_detected", False)
            else "Classic duvar motoru: sabit hat genişliği, sade gövdeler için yeterli."
        ),
        "fuzzy_skin": (
            "Fuzzy Skin (contour) önerildi: taban-duvar birleşimindeki yatay şişkinliği "
            "yüzey dokusuyla kamufle eder. "
            f"point_distance={FUZZY_SKIN_RECOMMENDED['fuzzy_skin_point_distance']} mm, "
            f"thickness={FUZZY_SKIN_RECOMMENDED['fuzzy_skin_thickness']} mm."
            if data.get("fuzzy_skin_recommended") or getattr(geometry, "hull_line_risk", False)
            else "Fuzzy Skin kapalı: yüzey dokusu değiştirilmedi."
        ),
    }


def attach_support_and_reasons(data: dict[str, Any], geometry: GeometryMetrics) -> dict[str, Any]:
    """Copy geometry support fields onto the recommendation and build why-text."""
    data["support_required"] = bool(getattr(geometry, "support_required", False))
    data["recommended_support_type"] = getattr(geometry, "recommended_support_type", None) or "none"
    data["support_reason"] = getattr(geometry, "support_reason", None) or ""
    data["is_miniature"] = bool(
        data.get("is_miniature") or getattr(geometry, "is_miniature", False)
    )
    data["miniature_optimization"] = bool(
        data.get("miniature_optimization") or data["is_miniature"]
    )
    brim_w = data.get("brim_width_mm")
    if brim_w is None and data["is_miniature"]:
        brim_w = miniature_brim_width_mm(geometry.bounding_box_mm)
        data["brim_width_mm"] = brim_w
    data["miniature_explanation"] = (
        data.get("miniature_explanation")
        or getattr(geometry, "miniature_explanation", "")
        or (miniature_explanation_tr(int(brim_w or MINIATURE_BRIM_WIDTH_MM)) if data["is_miniature"] else "")
    )
    if data["is_miniature"]:
        data["supports"] = False
        data["brim"] = True
        data["brim_type"] = data.get("brim_type") or MINIATURE_BRIM_TYPE
        data["outer_wall_speed_mm_s"] = MINIATURE_OUTER_WALL_SPEED_MM_S
        if data.get("outer_wall_line_width_mm") is None:
            data["outer_wall_line_width_mm"] = MINIATURE_OUTER_WALL_LINE_WIDTH_MM
        stype = data.get("support_type") or data["recommended_support_type"] or "normal(auto)"
        data["support_type"] = "normal(auto)" if stype in ("none", "", None) else stype
    elif data["support_required"]:
        data["supports"] = True
        stype = data["recommended_support_type"]
        data["support_type"] = stype if stype not in ("none", "", None) else "tree(auto)"
    elif data.get("supports"):
        stype = data.get("support_type") or data["recommended_support_type"] or "tree(auto)"
        data["support_type"] = "tree(auto)" if stype in ("none", "", None) else stype
    else:
        data["support_type"] = "normal(auto)"
    data["setting_reasons"] = build_setting_reasons(data, geometry)
    data["hull_line_risk"] = bool(
        data.get("hull_line_risk") or getattr(geometry, "hull_line_risk", False)
    )
    data["hull_line_mitigation"] = bool(
        data.get("hull_line_mitigation") or data["hull_line_risk"]
    )
    data["hull_line_explanation"] = (
        data.get("hull_line_explanation")
        or getattr(geometry, "hull_line_explanation", "")
        or (HULL_LINE_EXPLANATION_TR if data["hull_line_risk"] else "")
    )
    data["fuzzy_skin_recommended"] = bool(
        data.get("fuzzy_skin_recommended") or data["hull_line_risk"]
    )
    data["fine_text_detected"] = bool(
        data.get("fine_text_detected") or getattr(geometry, "fine_text_detected", False)
    )
    data["fine_detail_optimization"] = bool(
        data.get("fine_detail_optimization") or data["fine_text_detected"]
    )
    data["fine_text_explanation"] = (
        data.get("fine_text_explanation")
        or getattr(geometry, "fine_text_explanation", "")
        or (FINE_TEXT_EXPLANATION_TR if data["fine_text_detected"] else "")
    )
    if data["fine_text_detected"] and not data.get("wall_generator"):
        data["wall_generator"] = "arachne"
    if data["fine_text_detected"] and data.get("line_width_mm") is None:
        data["line_width_mm"] = FINE_TEXT_LINE_WIDTH_MM
    return data


def build_slicer_hints(data: dict[str, Any]) -> dict[str, Any]:
    """Map recommendation fields to Bambu/Orca-style keys for Phase B CLI."""
    miniature = bool(data.get("is_miniature") or data.get("miniature_optimization"))
    brim = bool(data.get("brim")) or miniature
    brim_width = data.get("brim_width_mm")
    if brim_width is None:
        brim_width = (MINIATURE_BRIM_WIDTH_MM if miniature else 5) if brim else 0
    brim_type = data.get("brim_type")
    if not brim_type:
        if miniature:
            brim_type = MINIATURE_BRIM_TYPE
        else:
            brim_type = "outer_only" if brim else "no_brim"
    hints: dict[str, Any] = {
        "filament_type": data["material"],
        "nozzle_diameter": data["nozzle_mm"],
        "layer_height": data["layer_height_mm"],
        "wall_loops": data["wall_loops"],
        "sparse_infill_density": data["infill_percent"],
        "sparse_infill_pattern": data["infill_pattern"],
        "nozzle_temperature": data["nozzle_temp_c"],
        "bed_temperature": data["bed_temp_c"],
        "enable_support": False if miniature else data["supports"],
        "support_type": data.get("support_type")
        or ("tree(auto)" if data["supports"] and not miniature else "normal(auto)"),
        "brim_width": brim_width,
        "outer_wall_speed": (
            MINIATURE_OUTER_WALL_SPEED_MM_S
            if miniature
            else data.get("outer_wall_speed_mm_s")
        ),
        "internal_solid_infill_speed": data.get("print_speed_mm_s"),
        "sparse_infill_speed": data.get("sparse_infill_speed_mm_s"),
        "print_speed": data.get("print_speed_mm_s"),
        "brim_type": brim_type,
        "printer_model": "Bambu Lab P2S",
        "printer_settings_id": "Bambu Lab P2S 0.4 nozzle",
        "hull_line_mitigation": bool(data.get("hull_line_mitigation")),
        "fine_detail_optimization": bool(data.get("fine_detail_optimization")),
        "miniature_optimization": miniature,
    }
    if data.get("wall_generator"):
        hints["wall_generator"] = data["wall_generator"]
    line_w = data.get("line_width_mm")
    outer_w = data.get("outer_wall_line_width_mm")
    if line_w is not None:
        hints["line_width"] = line_w
        hints["initial_layer_line_width"] = line_w
        hints["outer_wall_line_width"] = line_w
    if outer_w is not None:
        hints["outer_wall_line_width"] = outer_w
    elif miniature:
        hints["outer_wall_line_width"] = MINIATURE_OUTER_WALL_LINE_WIDTH_MM
    if data.get("fuzzy_skin_recommended") and data.get("apply_fuzzy_skin"):
        hints.update(data.get("fuzzy_skin_settings") or FUZZY_SKIN_RECOMMENDED)
    return hints
