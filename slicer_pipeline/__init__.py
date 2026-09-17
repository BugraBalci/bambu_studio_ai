"""Geometry-driven Bambu Lab P2S Combo pipeline (Meshy 3MF → Studio project)."""

from slicer_pipeline.bambu_config import BambuConfigEngine
from slicer_pipeline.constants import SUPPORTED_MESH_SUFFIXES
from slicer_pipeline.defects import (
    FINE_TEXT_EXPLANATION_TR,
    HULL_LINE_EXPLANATION_TR,
    MINIATURE_EXPLANATION_TR,
    detect_fine_text,
    detect_hull_line,
)
from slicer_pipeline.geometry import GeometryAnalyzer, GeometryMetrics
from slicer_pipeline.mesh_parser import MeshAssembly, MeshParser, MeshPart, load_triangle_mesh
from slicer_pipeline.project_packager import ProjectPackager
from slicer_pipeline.rules import RuleEngine, RuleResult
from slicer_pipeline.support import OverhangSupportAnalysis, analyze_overhang_support
from slicer_pipeline.text_engine import (
    EMBOSS_EXPLANATION_TR,
    FLUSH_EXPLANATION_TR,
    PLANAR_EXPLANATION_TR,
    WRAP_EXPLANATION_TR,
    TextSpec,
    analyze_target_surface,
    apply_text_to_assembly,
)

__all__ = [
    "BambuConfigEngine",
    "GeometryAnalyzer",
    "GeometryMetrics",
    "MeshAssembly",
    "MeshParser",
    "MeshPart",
    "ProjectPackager",
    "RuleEngine",
    "RuleResult",
    "HULL_LINE_EXPLANATION_TR",
    "FINE_TEXT_EXPLANATION_TR",
    "MINIATURE_EXPLANATION_TR",
    "FLUSH_EXPLANATION_TR",
    "EMBOSS_EXPLANATION_TR",
    "WRAP_EXPLANATION_TR",
    "PLANAR_EXPLANATION_TR",
    "TextSpec",
    "analyze_target_surface",
    "apply_text_to_assembly",
    "detect_hull_line",
    "detect_fine_text",
    "SUPPORTED_MESH_SUFFIXES",
    "OverhangSupportAnalysis",
    "analyze_overhang_support",
    "load_triangle_mesh",
]
