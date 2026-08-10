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


class GeometryMetrics(BaseModel):
    filename: str
    file_id: str
    triangle_count: int
    bounding_box_mm: list[float] = Field(description="[x, y, z] extents in mm")
    volume_cm3: float
    surface_area_cm2: float
    is_watertight: bool
    aspect_ratio: float
    thin_feature_hint: bool
    thin_feature_note: str = ""
    overhang_risk_hint: bool = False
    overhang_note: str = ""


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


class RecommendRequest(BaseModel):
    file_id: str
    purpose: Purpose
    strength: Strength
    color_preference: Optional[str] = None
    notes: Optional[str] = None


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
    matched_inventory_id: Optional[int] = None
    matched_inventory_slot: Optional[str] = None
    missing_filament_warning: Optional[str] = None
    rationale: str
    # Phase B hook: values ready to map onto process/filament JSON
    slicer_hints: dict[str, Any] = Field(default_factory=dict)
    schema_version: str = "1.0"


class RecommendResponse(BaseModel):
    geometry: GeometryMetrics
    recommendation: PrintRecommendation
    used_llm: bool
    rule_baseline: dict[str, Any]
