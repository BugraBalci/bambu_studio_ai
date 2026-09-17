"""Hull-line / fine-text detectors, rule engine, and 3MF key injection."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
import zipfile
from io import BytesIO
from pathlib import Path
from xml.etree import ElementTree as ET

import numpy as np
import trimesh

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
for path in (str(ROOT), str(BACKEND)):
    if path not in sys.path:
        sys.path.insert(0, path)

from app.schemas import PrintRecommendation  # noqa: E402
from app.services.bambu_3mf import (  # noqa: E402
    recommendation_to_project_overrides,
    write_bambu_3mf_bytes,
)
from app.services.rules import build_slicer_hints  # noqa: E402
from slicer_pipeline.bambu_config import BambuConfigEngine  # noqa: E402
from slicer_pipeline.defects import (  # noqa: E402
    FINE_TEXT_EXPLANATION_TR,
    HULL_LINE_EXPLANATION_TR,
    MINIATURE_EXPLANATION_TR,
    walls_for_shell_thickness,
)
from slicer_pipeline.geometry import GeometryAnalyzer  # noqa: E402
from slicer_pipeline.rules import RuleEngine  # noqa: E402
from slicer_pipeline.studio_profile import different_settings_to_system  # noqa: E402


def _cup_with_thin_walls() -> trimesh.Trimesh:
    """Open box: 2 mm floor, ~1.5 mm walls — a canonical Hull Line junction."""
    try:
        from shapely.geometry import Polygon, box
        from trimesh.creation import extrude_polygon

        outer = box(-20.0, -15.0, 20.0, 15.0)
        inner = box(-18.5, -13.5, 18.5, 13.5)
        ring = Polygon(list(outer.exterior.coords), [list(inner.exterior.coords)])
        walls = extrude_polygon(ring, height=18.0)
        walls.apply_translation([0.0, 0.0, 2.0])
        floor = trimesh.creation.box(extents=(40.0, 30.0, 2.0))
        floor.apply_translation([0.0, 0.0, 1.0])
        return trimesh.util.concatenate([floor, walls])
    except Exception:  # noqa: BLE001
        floor = trimesh.creation.box(extents=(40.0, 30.0, 2.0))
        floor.apply_translation([0.0, 0.0, 1.0])
        walls = [
            _wall((1.5, 30.0, 18.0), (19.25, 0.0, 11.0)),
            _wall((1.5, 30.0, 18.0), (-19.25, 0.0, 11.0)),
            _wall((37.0, 1.5, 18.0), (0.0, 14.25, 11.0)),
            _wall((37.0, 1.5, 18.0), (0.0, -14.25, 11.0)),
        ]
        return trimesh.util.concatenate([floor, *walls])


def _wall(extents, translate) -> trimesh.Trimesh:
    mesh = trimesh.creation.box(extents=extents)
    mesh.apply_translation(list(translate))
    return mesh


def _letter_plate() -> trimesh.Trimesh:
    """Flat plate with 0.28 mm extruded strokes (sub-0.42 mm font)."""
    base = trimesh.creation.box(extents=(50.0, 22.0, 2.0))
    base.apply_translation([0.0, 0.0, 1.0])
    strokes = []
    for x in np.linspace(-16.0, 16.0, 8):
        stroke = trimesh.creation.box(extents=(0.28, 7.0, 0.55))
        stroke.apply_translation([float(x), 0.0, 2.275])
        strokes.append(stroke)
    return trimesh.util.concatenate([base, *strokes])


def _analyze(mesh: trimesh.Trimesh):
    return GeometryAnalyzer(mesh).analyze()


def _scalar(value):
    return value[0] if isinstance(value, list) else value


class ThicknessHelperTests(unittest.TestCase):
    def test_wall_count_exceeds_two_millimetres(self) -> None:
        self.assertEqual(walls_for_shell_thickness(0.42), 5)
        self.assertEqual(walls_for_shell_thickness(0.3), 7)
        self.assertGreaterEqual(walls_for_shell_thickness(0.42) * 0.42, 2.0)
        self.assertGreaterEqual(walls_for_shell_thickness(0.3) * 0.3, 2.0)


class HullLineDetectionTests(unittest.TestCase):
    def test_thin_walled_cup_flags_hull_line(self) -> None:
        metrics = _analyze(_cup_with_thin_walls())
        self.assertTrue(metrics.hull_line_risk, msg=metrics.hull_line_note)
        self.assertLess(metrics.hull_line_shell_thickness_mm, 2.0)
        self.assertGreater(metrics.hull_line_shell_thickness_mm, 0.4)

    def test_solid_cube_has_no_hull_line(self) -> None:
        cube = trimesh.creation.box(extents=(20.0, 16.0, 12.0))
        metrics = _analyze(cube)
        self.assertFalse(metrics.hull_line_risk, msg=metrics.hull_line_note)


class FineTextDetectionTests(unittest.TestCase):
    def test_thin_strokes_flag_fine_text(self) -> None:
        metrics = _analyze(_letter_plate())
        self.assertTrue(metrics.fine_text_detected, msg=metrics.fine_text_note)
        self.assertLess(metrics.fine_stroke_width_mm, 0.45)

    def test_plain_cube_has_no_fine_text(self) -> None:
        cube = trimesh.creation.box(extents=(20.0, 16.0, 12.0))
        metrics = _analyze(cube)
        self.assertFalse(metrics.fine_text_detected, msg=metrics.fine_text_note)


class DefectRuleEngineTests(unittest.TestCase):
    def test_hull_line_increases_wall_loops(self) -> None:
        metrics = _analyze(_cup_with_thin_walls())
        results = {r.name: r for r in RuleEngine().evaluate(metrics)}
        self.assertTrue(results["hull_line"].triggered)
        self.assertEqual(results["hull_line"].updates["wall_loops"], "5")
        self.assertEqual(
            results["hull_line"].updates["_explanation_tr"],
            HULL_LINE_EXPLANATION_TR,
        )
        profile = BambuConfigEngine()
        profile.apply_rules(list(results.values()))
        self.assertEqual(profile.profile["wall_loops"], "5")
        self.assertNotEqual(profile.profile.get("fuzzy_skin"), "contour")

    def test_fine_text_enables_arachne_and_narrow_lines(self) -> None:
        metrics = _analyze(_letter_plate())
        results = {r.name: r for r in RuleEngine().evaluate(metrics)}
        self.assertTrue(results["fine_text"].triggered)
        updates = results["fine_text"].updates
        self.assertEqual(updates["wall_generator"], "arachne")
        self.assertEqual(updates["line_width"], "0.3")
        self.assertEqual(updates["outer_wall_line_width"], "0.3")
        self.assertEqual(updates["initial_layer_line_width"], "0.3")
        self.assertEqual(updates["layer_height"], "0.12")
        self.assertEqual(updates["_explanation_tr"], FINE_TEXT_EXPLANATION_TR)
        profile = BambuConfigEngine()
        profile.apply_rules(list(results.values()))
        self.assertEqual(profile.profile["wall_generator"], "arachne")
        self.assertEqual(profile.profile["line_width"], "0.3")

    def test_combined_rules_recompute_walls_for_narrow_lines(self) -> None:
        metrics = _analyze(_cup_with_thin_walls())
        metrics.fine_text_detected = True
        metrics.fine_text_on_skin = True
        results = {r.name: r for r in RuleEngine().evaluate(metrics)}
        self.assertTrue(results["hull_line"].triggered)
        self.assertTrue(results["fine_text"].triggered)
        self.assertEqual(results["hull_line"].updates["wall_loops"], "7")


def _miniature_car() -> trimesh.Trimesh:
    """~28×12×10 mm block — a typical miniature-car envelope."""
    return trimesh.creation.box(extents=(28.0, 12.0, 10.0))


def _desktop_bracket() -> trimesh.Trimesh:
    return trimesh.creation.box(extents=(80.0, 50.0, 40.0))


class MiniatureDetectionTests(unittest.TestCase):
    def test_small_box_flags_miniature(self) -> None:
        metrics = _analyze(_miniature_car())
        self.assertTrue(metrics.is_miniature)
        self.assertLessEqual(float(np.max(metrics.obb_extents_mm)), 35.0)
        self.assertAlmostEqual(float(np.max(metrics.obb_extents_mm)), 28.0, delta=0.6)

    def test_large_box_is_not_miniature(self) -> None:
        metrics = _analyze(_desktop_bracket())
        self.assertFalse(metrics.is_miniature)
        self.assertGreater(float(np.max(metrics.obb_extents_mm)), 35.0)

    def test_rotated_miniature_uses_oriented_bbox_not_aabb(self) -> None:
        mesh = trimesh.creation.box(extents=(34.0, 34.0, 10.0))
        mesh.apply_transform(
            trimesh.transformations.rotation_matrix(np.radians(45.0), [0.0, 0.0, 1.0])
        )
        metrics = _analyze(mesh)
        aabb_max = float(np.max(metrics.extents_mm))
        obb_max = float(np.max(metrics.obb_extents_mm))
        self.assertGreater(aabb_max, 35.0)
        self.assertLessEqual(obb_max, 35.0)
        self.assertTrue(metrics.is_miniature)


class MiniatureRuleEngineTests(unittest.TestCase):
    def test_miniature_overrides_layer_walls_speed_support_brim(self) -> None:
        metrics = _analyze(_miniature_car())
        results = {r.name: r for r in RuleEngine().evaluate(metrics)}
        self.assertTrue(results["miniature"].triggered)
        updates = results["miniature"].updates
        self.assertEqual(updates["layer_height"], "0.12")
        self.assertEqual(updates["outer_wall_line_width"], "0.35")
        self.assertEqual(str(updates["outer_wall_speed"]), "35")
        self.assertEqual(updates["enable_support"], "0")
        self.assertEqual(updates["brim_type"], "outer_and_inner")
        self.assertEqual(updates["brim_width"], "7")
        self.assertEqual(updates["_explanation_tr"], MINIATURE_EXPLANATION_TR)
        profile = BambuConfigEngine()
        profile.apply_rules(list(results.values()))
        self.assertEqual(profile.profile["layer_height"], "0.12")
        self.assertEqual(profile.profile["outer_wall_line_width"], "0.35")
        speed = profile.profile["outer_wall_speed"]
        self.assertEqual(str(speed[0] if isinstance(speed, list) else speed), "35")
        self.assertEqual(profile.profile["enable_support"], "0")
        self.assertEqual(profile.profile["brim_type"], "outer_and_inner")
        self.assertEqual(profile.profile["brim_width"], "7")

    def test_miniature_disables_overhang_supports(self) -> None:
        metrics = _analyze(_miniature_car())
        metrics.support_required = True
        metrics.overhang_area_ratio = 0.4
        metrics.recommended_support_type = "tree(auto)"
        results = {r.name: r for r in RuleEngine().evaluate(metrics)}
        self.assertTrue(results["overhang_bridge"].triggered)
        self.assertTrue(results["miniature"].triggered)
        profile = BambuConfigEngine()
        profile.apply_rules(list(results.values()))
        self.assertEqual(profile.profile["enable_support"], "0")
        speed = profile.profile["outer_wall_speed"]
        self.assertEqual(str(speed[0] if isinstance(speed, list) else speed), "35")


class MiniatureThreeMfTests(unittest.TestCase):
    def test_overrides_and_archive_carry_miniature_keys(self) -> None:
        data = {
            "material": "PLA",
            "nozzle_mm": 0.4,
            "layer_height_mm": 0.12,
            "wall_loops": 3,
            "infill_percent": 15,
            "infill_pattern": "grid",
            "nozzle_temp_c": 210,
            "bed_temp_c": 60,
            "supports": False,
            "brim": True,
            "brim_type": "outer_and_inner",
            "brim_width_mm": 7,
            "outer_wall_speed_mm_s": 35,
            "outer_wall_line_width_mm": 0.35,
            "rationale": "miniature rule",
            "is_miniature": True,
            "miniature_optimization": True,
            "miniature_explanation": MINIATURE_EXPLANATION_TR,
        }
        data["slicer_hints"] = build_slicer_hints(data)
        rec = PrintRecommendation(**data)
        overrides = recommendation_to_project_overrides(rec)
        self.assertEqual(overrides["layer_height"], "0.12")
        self.assertEqual(overrides["outer_wall_line_width"], "0.35")
        self.assertEqual(str(_scalar(overrides["outer_wall_speed"])), "35")
        self.assertEqual(overrides["enable_support"], "0")
        self.assertEqual(overrides["brim_type"], "outer_and_inner")
        self.assertEqual(overrides["brim_width"], "7")

        mesh = trimesh.creation.box(extents=(28.0, 12.0, 10.0))
        with tempfile.TemporaryDirectory() as tmp:
            stl_path = Path(tmp) / "mini.stl"
            mesh.export(stl_path)
            blob = write_bambu_3mf_bytes(stl_path, rec, part_name="mini")
        with zipfile.ZipFile(BytesIO(blob)) as zf:
            project = json.loads(zf.read("Metadata/project_settings.config"))
            model_settings = zf.read("Metadata/model_settings.config").decode("utf-8")
        self.assertEqual(project["layer_height"], "0.12")
        self.assertEqual(str(_scalar(project["outer_wall_line_width"])), "0.35")
        self.assertEqual(str(_scalar(project["outer_wall_speed"])), "35")
        self.assertEqual(str(_scalar(project["enable_support"])), "0")
        self.assertEqual(project["brim_type"], "outer_and_inner")
        self.assertEqual(str(_scalar(project["brim_width"])), "7")
        process_diffs = different_settings_to_system(project)[0].split(";")
        for key in (
            "layer_height",
            "outer_wall_line_width",
            "outer_wall_speed",
            "enable_support",
            "brim_type",
            "brim_width",
        ):
            self.assertIn(key, process_diffs)
        meta = {
            el.get("key"): el.get("value")
            for el in ET.fromstring(model_settings).find("object").findall("metadata")
        }
        self.assertEqual(meta.get("layer_height"), "0.12")
        self.assertEqual(meta.get("outer_wall_line_width"), "0.35")
        self.assertEqual(meta.get("outer_wall_speed"), "35")
        self.assertEqual(meta.get("enable_support"), "0")
        self.assertEqual(meta.get("brim_type"), "outer_and_inner")
        self.assertEqual(meta.get("brim_width"), "7")


class DefectThreeMfTests(unittest.TestCase):
    def test_overrides_carry_arachne_and_line_width(self) -> None:
        data = {
            "material": "PLA",
            "nozzle_mm": 0.4,
            "layer_height_mm": 0.12,
            "wall_loops": 5,
            "infill_percent": 15,
            "infill_pattern": "grid",
            "nozzle_temp_c": 210,
            "bed_temp_c": 60,
            "supports": False,
            "brim": False,
            "rationale": "defect rules",
            "wall_generator": "arachne",
            "line_width_mm": 0.3,
            "hull_line_risk": True,
            "hull_line_mitigation": True,
            "fine_text_detected": True,
            "fine_detail_optimization": True,
            "apply_fuzzy_skin": True,
            "fuzzy_skin_recommended": True,
        }
        data["slicer_hints"] = build_slicer_hints(data)
        data["slicer_hints"].update(
            {
                "fuzzy_skin": "contour",
                "fuzzy_skin_point_distance": "0.8",
                "fuzzy_skin_thickness": "0.1",
            }
        )
        rec = PrintRecommendation(**data)
        overrides = recommendation_to_project_overrides(rec)
        self.assertEqual(overrides["wall_generator"], "arachne")
        self.assertEqual(overrides["wall_loops"], "5")
        self.assertEqual(overrides["line_width"], "0.3")
        self.assertEqual(overrides["outer_wall_line_width"], "0.3")
        self.assertEqual(overrides["initial_layer_line_width"], "0.3")
        self.assertEqual(overrides["fuzzy_skin"], "contour")
        self.assertEqual(overrides["fuzzy_skin_point_distance"], "0.8")
        self.assertEqual(overrides["fuzzy_skin_thickness"], "0.1")

        mesh = trimesh.creation.box(extents=(20.0, 16.0, 8.0))
        with tempfile.TemporaryDirectory() as tmp:
            stl_path = Path(tmp) / "cube.stl"
            mesh.export(stl_path)
            blob = write_bambu_3mf_bytes(stl_path, rec, part_name="cube")
        with zipfile.ZipFile(BytesIO(blob)) as zf:
            project = json.loads(zf.read("Metadata/project_settings.config"))
            model_settings = zf.read("Metadata/model_settings.config").decode("utf-8")
        self.assertEqual(project["wall_generator"], "arachne")
        self.assertEqual(project["wall_loops"], "5")
        self.assertEqual(project["line_width"], "0.3")
        self.assertEqual(project["outer_wall_line_width"], "0.3")
        self.assertEqual(project["fuzzy_skin"], "contour")
        process_diffs = different_settings_to_system(project)[0].split(";")
        for key in (
            "wall_generator",
            "wall_loops",
            "line_width",
            "outer_wall_line_width",
            "fuzzy_skin",
        ):
            self.assertIn(key, process_diffs)
        meta = {
            el.get("key"): el.get("value")
            for el in ET.fromstring(model_settings).find("object").findall("metadata")
        }
        self.assertEqual(meta.get("wall_generator"), "arachne")
        self.assertEqual(meta.get("line_width"), "0.3")
        self.assertEqual(meta.get("wall_loops"), "5")


if __name__ == "__main__":
    unittest.main()
