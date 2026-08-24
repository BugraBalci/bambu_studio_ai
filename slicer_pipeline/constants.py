"""Shared geometric thresholds and printer constants (Bambu Lab P2S Combo)."""

from __future__ import annotations

from pathlib import Path

import numpy as np

NEG_Z = np.array([0.0, 0.0, -1.0], dtype=np.float64)
OVERHANG_ANGLE_DEG = 45.0  # θ from -Z
BED_FLAT_ANGLE_DEG = 15.0  # exclude near-horizontal bed contact from "overhang"
OVERHANG_AREA_RATIO = 0.10
SUPPORT_AREA_RATIO = 0.05  # enable supports when overhang area exceeds this share
PLANAR_OVERHANG_ANGLE_DEG = 30.0  # closer to -Z than this → wide/flat underside
SUPPORT_CLUSTER_CELL_MM = 12.0
SUPPORT_TYPE_TREE = "tree(auto)"
SUPPORT_TYPE_NORMAL = "normal(auto)"
SUPPORT_TYPE_NONE = "none"
TALL_ASPECT_RATIO = 4.0
TOP_SECTION_Z_FRAC = 0.80  # analyze plane at 80% of Z height (top 20%)
NARROW_TOP_AREA_MM2 = 25.0  # "extremely narrow" top cross-section
LARGE_VOLUME_CM3 = 1500.0
LARGE_FLAT_BOTTOM_MM2 = 5000.0
HIGH_VERTEX_DENSITY = 8.0  # vertices per mm² of surface
HIGH_NORMAL_VARIANCE = 0.35  # mean adjacent normal disagreement (1 - |n_i·n_j|)

# Center-of-mass / tip-over stability
COG_Z_TOP_HEAVY = 0.68  # CoG above this fraction of height → top-heavy
COG_XY_SKEW = 0.28  # CoG XY offset / half-width → lateral imbalance
COG_TALL_Z_RATIO = 0.58  # lower threshold when aspect_ratio_z is high

# Mechanical hole detection (cross-section loops)
HOLE_SLICE_FRACTIONS = (0.25, 0.50, 0.75)
HOLE_MIN_DIAMETER_MM = 1.5
HOLE_MAX_DIAMETER_MM = 45.0
HOLE_MIN_CIRCULARITY = 0.55  # 4πA/P² ≈ 1 for a perfect circle
HOLE_COMPENSATION_MM = "0.15"

DEFAULT_QUEUE_DIR = Path("uploads")
SUPPORTED_MESH_SUFFIXES = {".stl", ".obj", ".glb", ".gltf", ".3mf"}
_METERISH_SUFFIXES = {".glb", ".gltf", ".obj"}
_METER_TO_MM = 1000.0
_METER_SCALE_MAX_EXTENT = 2.0

# Official P2S Combo build volume (same XYZ envelope as P1S)
P2S_BED_MM = (256.0, 256.0, 256.0)
P1S_BED_MM = P2S_BED_MM  # backward-compatible alias

PRINTER_MODEL = "Bambu Lab P2S"
PRINTER_NAME = "Bambu Lab P2S Combo"
PRINTER_VARIANT = "0.4 nozzle"
PRINTER_SETTINGS_ID = "Bambu Lab P2S 0.4 nozzle"
AMS_SLOT_CAP = 16

_3MF_UNIT_TO_MM = {
    "micron": 0.001,
    "micrometer": 0.001,
    "millimeter": 1.0,
    "millimetre": 1.0,
    "centimeter": 10.0,
    "centimetre": 10.0,
    "meter": 1000.0,
    "metre": 1000.0,
    "inch": 25.4,
    "foot": 304.8,
}

REPO_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_PATH = REPO_ROOT / "profiles" / "bambu_project_settings_template.json"

# Compatibility aliases for GeometryAnalyzer / mesh_parser / RuleEngine
AMS_SLOT_CAP = AMS_SLOT_CAP
P2S_BED_MM = P2S_BED_MM
SUPPORTED_MESH_SUFFIXES = SUPPORTED_MESH_SUFFIXES
_3MF_UNIT_TO_MM = _3MF_UNIT_TO_MM
_METER_SCALE_MAX_EXTENT = _METER_SCALE_MAX_EXTENT
_METER_TO_MM = _METER_TO_MM
_METERISH_SUFFIXES = _METERISH_SUFFIXES
COG_TALL_Z_RATIO = COG_TALL_Z_RATIO
TALL_ASPECT_RATIO = TALL_ASPECT_RATIO
TOP_SECTION_Z_FRAC = TOP_SECTION_Z_FRAC
HOLE_MAX_DIAMETER_MM = HOLE_MAX_DIAMETER_MM
HOLE_MIN_CIRCULARITY = HOLE_MIN_CIRCULARITY
HOLE_MIN_DIAMETER_MM = HOLE_MIN_DIAMETER_MM
HOLE_SLICE_FRACTIONS = HOLE_SLICE_FRACTIONS
HIGH_NORMAL_VARIANCE = HIGH_NORMAL_VARIANCE
HIGH_VERTEX_DENSITY = HIGH_VERTEX_DENSITY
HOLE_COMPENSATION_MM = HOLE_COMPENSATION_MM
LARGE_FLAT_BOTTOM_MM2 = LARGE_FLAT_BOTTOM_MM2
LARGE_VOLUME_CM3 = LARGE_VOLUME_CM3
NARROW_TOP_AREA_MM2 = NARROW_TOP_AREA_MM2
DEFAULT_QUEUE_DIR = DEFAULT_QUEUE_DIR
PRINTER_SETTINGS_ID = PRINTER_SETTINGS_ID
