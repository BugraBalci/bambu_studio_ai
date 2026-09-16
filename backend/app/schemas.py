from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class Purpose(str, Enum):
    outdoor = "outdoor"
    decorative = "decorative"
    functional = "functional"


class Strength(str, Enum):
    weak = "weak"
    medium = "medium"
    strong = "strong"


class DetailTier(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"


# P2S Combo official build volume
P2S_BED_MM = (256.0, 256.0, 256.0)


class DetectedColor(BaseModel):
    """A distinct base color extracted from a 3MF/GLB assembly."""

    id: str
    hex: str
    hex_rgba: str = ""
    name: str
    slot_index: int = 0
    extruder: int = 1
    part_count: int = 1
    aliases: list[str] = Field(default_factory=list)


class GeometryMetrics(BaseModel):
    filename: str
    file_id: str
    triangle_count: int
    vertex_count: int = 0
    bounding_box_mm: list[float] = Field(description="Model boyutları [genişlik, derinlik, yükseklik] mm")
    volume_cm3: float
    surface_area_cm2: float
    is_watertight: bool
    aspect_ratio: float
    thin_feature_hint: bool
    thin_feature_note: str = ""
    overhang_risk_hint: bool = False
    overhang_note: str = ""
    support_required: bool = False
    recommended_support_type: str = "none"
    support_reason: str = ""
    overhang_area_ratio: float = 0.0
    fits_p2s_bed: bool = True
    bed_fit_note: str = ""
    printer_bed_mm: list[float] = Field(default_factory=lambda: list(P2S_BED_MM))
    triangles_per_cm2: float = 0.0
    detail_tier: DetailTier = DetailTier.medium
    detail_note: str = ""
    part_count: int = 1
    color_count: int = 1
    colors: list[DetectedColor] = Field(default_factory=list)


class FilamentBase(BaseModel):
    material: str
    color: str
    brand: str = ""
    slot: str = ""
    diameter_mm: float = 1.75
    notes: str = ""


class FilamentCreate(FilamentBase):
    pass


class FilamentUpdate(BaseModel):
    material: Optional[str] = None
    color: Optional[str] = None
    brand: Optional[str] = None
    slot: Optional[str] = None
    diameter_mm: Optional[float] = None
    notes: Optional[str] = None


class FilamentOut(FilamentBase):
    id: int

    model_config = {"from_attributes": True}


class ColorSlotMapping(BaseModel):
    color_id: str
    filament_id: Optional[int] = None


class FilamentSlotPlan(BaseModel):
    """Per-AMS-slot filament assignment for a detected model color."""

    color_id: str
    color_hex: str
    color_name: str
    extruder: int = 1
    filament_id: Optional[int] = None
    material: str
    studio_type: str
    nozzle_temp_c: int
    bed_temp_c: int
    nozzle_range_low: int = 190
    nozzle_range_high: int = 240
    filament_ids: str = "GFL99"
    filament_settings_id: str = "Generic PLA @BBL P2S"
    label: str = ""
    slot: str = ""


class FilamentWarning(BaseModel):
    code: str
    severity: str
    color_id: Optional[str] = None
    color_name: Optional[str] = None
    filament_label: Optional[str] = None
    reasons: list[str] = Field(default_factory=list)
    message: str


class RecommendRequest(BaseModel):
    file_id: str
    purpose: Purpose
    strength: Strength
    color_preference: Optional[str] = None
    preferred_filament_id: Optional[int] = None
    notes: Optional[str] = None
    color_filament_map: list[ColorSlotMapping] = Field(default_factory=list)
    acknowledge_filament_warnings: bool = False


class FilamentMapValidateRequest(BaseModel):
    file_id: str
    purpose: Purpose
    strength: Strength
    color_filament_map: list[ColorSlotMapping] = Field(default_factory=list)


class FilamentMapValidateResponse(BaseModel):
    colors: list[DetectedColor] = Field(default_factory=list)
    slots: list[FilamentSlotPlan] = Field(default_factory=list)
    warnings: list[FilamentWarning] = Field(default_factory=list)


class PrintRecommendation(BaseModel):
    """Canonical recommendation schema — also the Phase B CLI/profile bridge."""

    material: str
    nozzle_mm: float
    layer_height_mm: float
    wall_loops: int
    infill_percent: int
    infill_pattern: str
    nozzle_temp_c: int
    bed_temp_c: int
    supports: bool
    brim: bool
    support_type: Optional[str] = None
    support_required: bool = False
    recommended_support_type: Optional[str] = None
    support_reason: Optional[str] = None
    setting_reasons: dict[str, str] = Field(default_factory=dict)
    matched_inventory_id: Optional[int] = None
    matched_inventory_slot: Optional[str] = None
    matched_filament_label: Optional[str] = None
    missing_filament_warning: Optional[str] = None
    color_conflict_warning: Optional[str] = None
    ideal_material: Optional[str] = None
    user_notes_applied: Optional[str] = None
    detail_tier: Optional[str] = None
    print_speed_mm_s: Optional[int] = None
    outer_wall_speed_mm_s: Optional[int] = None
    sparse_infill_speed_mm_s: Optional[int] = None
    speed_rationale: Optional[str] = None
    rationale: str
    slicer_hints: dict[str, Any] = Field(default_factory=dict)
    filament_slots: list[FilamentSlotPlan] = Field(default_factory=list)
    filament_warnings: list[FilamentWarning] = Field(default_factory=list)
    schema_version: str = "1.0"


class RecommendResponse(BaseModel):
    geometry: GeometryMetrics
    recommendation: PrintRecommendation
    used_llm: bool
    rule_baseline: dict[str, Any]
    source_label: str
    source_explanation: str
