"""Verify exported .3mf archives carry Bambu Studio P2S project metadata."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
import zipfile
from io import BytesIO
from pathlib import Path
from xml.etree import ElementTree as ET

import trimesh

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
for path in (str(ROOT), str(BACKEND)):
    if path not in sys.path:
        sys.path.insert(0, path)

from app.schemas import PrintRecommendation  # noqa: E402
from app.services.bambu_3mf import (  # noqa: E402
    build_project_settings,
    recommendation_to_project_overrides,
    write_bambu_3mf_bytes,
)
from app.services.rules import build_slicer_hints  # noqa: E402


def _scalar(value):
    return value[0] if isinstance(value, list) else value


def _sample_recommendation() -> PrintRecommendation:
    data = {
        "material": "PLA",
        "nozzle_mm": 0.4,
        "layer_height_mm": 0.28,
        "wall_loops": 3,
        "infill_percent": 12,
        "infill_pattern": "grid",
        "nozzle_temp_c": 210,
        "bed_temp_c": 60,
        "supports": False,
        "brim": False,
        "print_speed_mm_s": 150,
        "outer_wall_speed_mm_s": 80,
        "sparse_infill_speed_mm_s": 180,
        "rationale": "Rule-engine decorative/weak baseline.",
    }
    data["slicer_hints"] = build_slicer_hints(data)
    return PrintRecommendation(**data)


class Bambu3mfMetadataTests(unittest.TestCase):
    def test_overrides_use_rule_engine_values(self) -> None:
        rec = _sample_recommendation()
        overrides = recommendation_to_project_overrides(rec)
        self.assertEqual(overrides["layer_height"], "0.28")
        self.assertEqual(overrides["sparse_infill_density"], "12%")
        self.assertEqual(overrides["sparse_infill_pattern"], "grid")
        self.assertEqual(overrides["wall_loops"], "3")
        self.assertEqual(str(_scalar(overrides["outer_wall_speed"])), "80")
        self.assertEqual(str(_scalar(overrides["internal_solid_infill_speed"])), "150")
        self.assertEqual(str(_scalar(overrides["sparse_infill_speed"])), "180")
        self.assertEqual(overrides["nozzle_temperature"], ["210"])
        self.assertEqual(overrides["bed_temperature"], ["60"])
        self.assertEqual(overrides["enable_support"], "0")
        self.assertEqual(overrides["brim_type"], "no_brim")
        self.assertEqual(overrides["printer_model"], "Bambu Lab P2S")
        self.assertEqual(overrides["from"], "project")
        self.assertNotIn("A1", overrides["print_settings_id"])
        self.assertIn("P2S", overrides["print_settings_id"])

    def test_merged_project_settings_keep_p2s_identity(self) -> None:
        rec = _sample_recommendation()
        settings = build_project_settings(rec)
        self.assertEqual(settings["printer_model"], "Bambu Lab P2S")
        self.assertEqual(settings["printer_settings_id"], "Bambu Lab P2S 0.4 nozzle")
        self.assertEqual(settings["from"], "project")
        self.assertEqual(settings["name"], "project_settings")
        self.assertEqual(settings["print_compatible_printers"], ["Bambu Lab P2S 0.4 nozzle"])
        self.assertNotIn("A1", settings["print_settings_id"])
        self.assertNotIn("A1", settings["default_print_profile"])
        self.assertEqual(settings["layer_height"], "0.28")
        self.assertEqual(settings["sparse_infill_density"], "12%")
        self.assertEqual(str(_scalar(settings["outer_wall_speed"])), "80")
        self.assertEqual(settings["nozzle_temperature"], ["210"])
        self.assertEqual(settings["bed_temperature"], ["60"])
        diffs = settings["different_settings_to_system"]
        self.assertTrue(diffs)
        self.assertIn("layer_height", diffs[0])
        self.assertIn("sparse_infill_density", diffs[0])
        self.assertIn("outer_wall_speed", diffs[0])
        self.assertIn("nozzle_temperature", diffs[1])

    def test_exported_archive_embeds_metadata_files(self) -> None:
        rec = _sample_recommendation()
        mesh = trimesh.creation.box(extents=(20.0, 16.0, 8.0))
        with tempfile.TemporaryDirectory() as tmp:
            stl_path = Path(tmp) / "cube.stl"
            mesh.export(stl_path)
            data = write_bambu_3mf_bytes(stl_path, rec, part_name="cube")

        with zipfile.ZipFile(BytesIO(data)) as zf:
            names = set(zf.namelist())
            self.assertIn("Metadata/project_settings.config", names)
            self.assertIn("Metadata/model_settings.config", names)
            self.assertIn("3D/3dmodel.model", names)
            project = json.loads(zf.read("Metadata/project_settings.config"))
            model_xml = zf.read("Metadata/model_settings.config").decode("utf-8")

        self.assertEqual(project["printer_model"], "Bambu Lab P2S")
        self.assertEqual(project["layer_height"], "0.28")
        self.assertEqual(project["wall_loops"], "3")
        self.assertEqual(project["sparse_infill_density"], "12%")
        self.assertEqual(project["sparse_infill_pattern"], "grid")
        self.assertEqual(str(_scalar(project["outer_wall_speed"])), "80")
        self.assertEqual(str(_scalar(project["internal_solid_infill_speed"])), "150")
        self.assertEqual(str(_scalar(project["sparse_infill_speed"])), "180")
        self.assertEqual(project["nozzle_temperature"], ["210"])
        self.assertEqual(project["bed_temperature"], ["60"])
        self.assertEqual(project["enable_support"], "0")
        self.assertEqual(project["brim_type"], "no_brim")
        self.assertEqual(project["from"], "project")
        self.assertIn("P2S", project["printer_settings_id"])
        self.assertNotIn("A1", project["print_settings_id"])
        self.assertNotIn("A1", json.dumps(project.get("filament_settings_id")))

        root = ET.fromstring(model_xml)
        objects = root.findall("object")
        self.assertTrue(objects)
        obj = objects[0]
        meta = {el.get("key"): el.get("value") for el in obj.findall("metadata")}
        self.assertEqual(meta.get("layer_height"), "0.28")
        self.assertEqual(meta.get("sparse_infill_density"), "12%")
        self.assertEqual(meta.get("wall_loops"), "3")
        self.assertEqual(meta.get("enable_support"), "0")
        self.assertEqual(meta.get("brim_type"), "no_brim")
        parts = obj.findall("part")
        self.assertTrue(parts)
        self.assertEqual(parts[0].get("subtype"), "normal_part")
        self.assertIsNotNone(root.find("plate"))
        self.assertIsNotNone(root.find("assemble"))


if __name__ == "__main__":
    unittest.main()
