"""Verify exported .3mf archives open in Bambu Studio as P2S projects.

The assertions here mirror what `PresetBundle::load_config_file_config` and
`PresetCollection::load_external_preset` actually require, since a project that
fails any of them opens under whatever preset the user last had selected.
"""

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
from slicer_pipeline.project_packager import (  # noqa: E402
    REQUIRED_ENTRIES,
    ProjectArchiveError,
    verify_project_archive,
)
from slicer_pipeline.studio_profile import print_settings_id_for  # noqa: E402

# Every 0.4-nozzle process preset Bambu Studio ships for the P2S. An `inherits`
# outside this set resolves to nothing, which is what drops a project back onto
# the fallback profile.
INSTALLED_P2S_PROCESS_PRESETS = frozenset(
    {
        "0.08mm High Quality @BBL P2S",
        "0.12mm High Quality @BBL P2S",
        "0.16mm High Quality @BBL P2S",
        "0.16mm Standard @BBL P2S",
        "0.20mm High Quality @BBL P2S",
        "0.20mm Standard @BBL P2S",
        "0.24mm Standard @BBL P2S",
    }
)


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


def _export(rec: PrintRecommendation) -> bytes:
    mesh = trimesh.creation.box(extents=(20.0, 16.0, 8.0))
    with tempfile.TemporaryDirectory() as tmp:
        stl_path = Path(tmp) / "cube.stl"
        mesh.export(stl_path)
        return write_bambu_3mf_bytes(stl_path, rec, part_name="cube")


class Bambu3mfOverrideTests(unittest.TestCase):
    def test_overrides_use_rule_engine_values(self) -> None:
        overrides = recommendation_to_project_overrides(_sample_recommendation())
        self.assertEqual(overrides["layer_height"], "0.28")
        self.assertEqual(overrides["initial_layer_print_height"], "0.28")
        self.assertEqual(overrides["sparse_infill_density"], "12%")
        self.assertEqual(overrides["sparse_infill_pattern"], "grid")
        self.assertEqual(overrides["wall_loops"], "3")
        self.assertEqual(str(_scalar(overrides["outer_wall_speed"])), "80")
        self.assertEqual(str(_scalar(overrides["initial_layer_speed"])), "50")
        self.assertEqual(str(_scalar(overrides["internal_solid_infill_speed"])), "150")
        self.assertEqual(str(_scalar(overrides["sparse_infill_speed"])), "180")
        self.assertEqual(overrides["nozzle_temperature"], ["210"])
        self.assertEqual(overrides["textured_plate_temp"], ["60"])
        self.assertEqual(overrides["enable_support"], "0")
        self.assertEqual(overrides["brim_type"], "no_brim")
        self.assertEqual(overrides["printer_model"], "Bambu Lab P2S")
        self.assertEqual(overrides["printer_settings_id"], "Bambu Lab P2S 0.4 nozzle")
        self.assertEqual(overrides["from"], "project")
        self.assertNotIn("bed_temperature", overrides)

    def test_inherits_names_an_installed_process_preset(self) -> None:
        overrides = recommendation_to_project_overrides(_sample_recommendation())
        self.assertEqual(overrides["inherits"], overrides["print_settings_id"])
        self.assertIn(overrides["inherits"], INSTALLED_P2S_PROCESS_PRESETS)

    def test_every_layer_height_resolves_to_an_installed_preset(self) -> None:
        for millis in range(80, 290, 2):
            layer = millis / 1000.0
            with self.subTest(layer=layer):
                self.assertIn(print_settings_id_for(layer, 0.4), INSTALLED_P2S_PROCESS_PRESETS)

    def test_layer_height_clamped_to_nozzle_window(self) -> None:
        rec = _sample_recommendation()
        rec.layer_height_mm = 0.45
        rec.slicer_hints = {}
        overrides = recommendation_to_project_overrides(rec)
        self.assertEqual(overrides["layer_height"], "0.28")


class Bambu3mfProjectSettingsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.settings = build_project_settings(_sample_recommendation())

    def test_p2s_identity_replaces_a1_template_values(self) -> None:
        settings = self.settings
        self.assertEqual(settings["printer_model"], "Bambu Lab P2S")
        self.assertEqual(settings["printer_settings_id"], "Bambu Lab P2S 0.4 nozzle")
        self.assertEqual(settings["printer_variant"], "0.4")
        self.assertEqual(settings["nozzle_diameter"], ["0.4"])
        self.assertEqual(settings["from"], "project")
        self.assertEqual(settings["name"], "project_settings")
        self.assertEqual(settings["is_bbl_printer"], "1")
        self.assertEqual(settings["curr_bed_type"], "Textured PEI Plate")
        self.assertEqual(settings["print_compatible_printers"], ["Bambu Lab P2S 0.4 nozzle"])
        for key in ("print_settings_id", "default_print_profile", "inherits"):
            self.assertNotIn("A1", settings[key])
        self.assertNotIn("A1", json.dumps(settings["filament_settings_id"]))
        self.assertNotIn("A1", json.dumps(settings["upward_compatible_machine"]))

    def test_calculated_values_survive_the_merge(self) -> None:
        settings = self.settings
        self.assertEqual(settings["layer_height"], "0.28")
        self.assertEqual(settings["initial_layer_print_height"], "0.28")
        self.assertEqual(settings["sparse_infill_density"], "12%")
        self.assertEqual(settings["wall_loops"], "3")
        self.assertEqual(str(_scalar(settings["outer_wall_speed"])), "80")
        self.assertEqual(settings["nozzle_temperature"], ["210"])
        self.assertNotIn("bed_temperature", settings)

    def test_inherits_group_layout(self) -> None:
        """`[process, filament_1..N, printer]`, sized filament count + 2."""
        settings = self.settings
        slots = len(settings["filament_colour"])
        group = settings["inherits_group"]
        self.assertEqual(len(group), slots + 2)
        self.assertEqual(group[0], settings["print_settings_id"])
        self.assertEqual(group[1 : slots + 1], settings["filament_settings_id"])
        self.assertEqual(group[-1], settings["printer_settings_id"])

    def test_different_settings_to_system_layout(self) -> None:
        settings = self.settings
        slots = len(settings["filament_colour"])
        diffs = settings["different_settings_to_system"]
        self.assertEqual(len(diffs), slots + 2)
        process = diffs[0].split(";")
        for key in (
            "layer_height",
            "initial_layer_print_height",
            "wall_loops",
            "sparse_infill_density",
            "sparse_infill_pattern",
            "outer_wall_speed",
            "initial_layer_speed",
        ):
            self.assertIn(key, process)
        self.assertIn("nozzle_temperature", diffs[1].split(";"))
        self.assertNotIn("bed_temperature", diffs[1].split(";"))
        # Empty printer entry: Studio then resets every machine key to the stock
        # P2S values instead of keeping the A1 bed shape and G-code.
        self.assertEqual(diffs[-1], "")

    def test_filament_vectors_match_the_slot_count(self) -> None:
        settings = self.settings
        slots = len(settings["filament_colour"])
        for key in ("filament_type", "filament_diameter", "filament_self_index", "filament_map"):
            self.assertEqual(len(settings[key]), slots, msg=key)
        self.assertEqual(settings["filament_self_index"], [str(i + 1) for i in range(slots)])


class Bambu3mfArchiveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.data = _export(_sample_recommendation())
        with zipfile.ZipFile(BytesIO(cls.data)) as zf:
            cls.names = zf.namelist()
            cls.project = json.loads(zf.read("Metadata/project_settings.config"))
            cls.model_settings = zf.read("Metadata/model_settings.config").decode("utf-8")
            cls.slice_info = zf.read("Metadata/slice_info.config").decode("utf-8")
            cls.model = zf.read("3D/3dmodel.model").decode("utf-8")

    def test_archive_contains_required_entries_in_load_order(self) -> None:
        self.assertEqual(verify_project_archive(self.data), self.names)
        self.assertEqual(self.names[: len(REQUIRED_ENTRIES)], list(REQUIRED_ENTRIES))

    def test_verification_rejects_a_geometry_only_archive(self) -> None:
        buf = BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("[Content_Types].xml", "<Types/>")
            zf.writestr("_rels/.rels", "<Relationships/>")
            zf.writestr("3D/3dmodel.model", "<model/>")
        with self.assertRaises(ProjectArchiveError):
            verify_project_archive(buf.getvalue())

    def test_verification_rejects_slice_info_before_model_settings(self) -> None:
        buf = BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            for name in REQUIRED_ENTRIES[:3]:
                zf.writestr(name, "<x/>")
            zf.writestr("Metadata/project_settings.config", "{}")
            zf.writestr("Metadata/slice_info.config", "<config/>")
            zf.writestr("Metadata/model_settings.config", "<config/>")
        with self.assertRaises(ProjectArchiveError):
            verify_project_archive(buf.getvalue())

    def test_model_declares_a_bambu_studio_generator(self) -> None:
        """`m_is_bbl_3mf` only flips for an Application tag starting BambuStudio-."""
        self.assertIn('<metadata name="Application">BambuStudio-', self.model)
        self.assertIn('<metadata name="BambuStudio:3mfVersion">', self.model)

    def test_project_settings_carry_the_p2s_profile(self) -> None:
        project = self.project
        self.assertEqual(project["printer_model"], "Bambu Lab P2S")
        self.assertEqual(project["printer_settings_id"], "Bambu Lab P2S 0.4 nozzle")
        self.assertEqual(project["layer_height"], "0.28")
        self.assertEqual(project["initial_layer_print_height"], "0.28")
        self.assertEqual(project["wall_loops"], "3")
        self.assertEqual(project["sparse_infill_density"], "12%")
        self.assertEqual(project["sparse_infill_pattern"], "grid")
        self.assertEqual(str(_scalar(project["outer_wall_speed"])), "80")
        self.assertEqual(str(_scalar(project["initial_layer_speed"])), "50")
        self.assertEqual(str(_scalar(project["internal_solid_infill_speed"])), "150")
        self.assertEqual(str(_scalar(project["sparse_infill_speed"])), "180")
        self.assertEqual(project["nozzle_temperature"], ["210"])
        self.assertEqual(project["enable_support"], "0")
        self.assertEqual(project["brim_type"], "no_brim")
        self.assertEqual(project["from"], "project")
        self.assertIn(project["inherits"], INSTALLED_P2S_PROCESS_PRESETS)
        self.assertEqual(len(project["inherits_group"]), len(project["filament_colour"]) + 2)
        self.assertNotIn("A1", project["print_settings_id"])
        self.assertNotIn("A1", json.dumps(project.get("filament_settings_id")))

    def test_slice_info_declares_the_plate_and_printer(self) -> None:
        root = ET.fromstring(self.slice_info)
        header = {el.get("key"): el.get("value") for el in root.find("header").findall("header_item")}
        self.assertEqual(header["X-BBL-Client-Type"], "slicer")
        self.assertTrue(header["X-BBL-Client-Version"])

        plate = root.find("plate")
        self.assertIsNotNone(plate)
        meta = {el.get("key"): el.get("value") for el in plate.findall("metadata")}
        self.assertEqual(meta["index"], "1")
        self.assertEqual(meta["printer_model_id"], "N7")
        self.assertEqual(meta["nozzle_diameters"], "0.4")
        filaments = plate.findall("filament")
        self.assertEqual(len(filaments), len(self.project["filament_colour"]))
        self.assertEqual(filaments[0].get("id"), "1")
        self.assertEqual(filaments[0].get("type"), self.project["filament_type"][0])

    def test_slice_info_plate_index_matches_model_settings(self) -> None:
        """Studio resolves slice_info's plate by looking up the model_settings plate."""
        plate = ET.fromstring(self.model_settings).find("plate")
        model_meta = {el.get("key"): el.get("value") for el in plate.findall("metadata")}
        slice_meta = {
            el.get("key"): el.get("value")
            for el in ET.fromstring(self.slice_info).find("plate").findall("metadata")
        }
        self.assertEqual(model_meta["plater_id"], slice_meta["index"])
        self.assertEqual(model_meta["bed_type"], "Textured PEI Plate")
        self.assertIn("filament_maps", model_meta)

    def test_model_settings_object_carries_process_overrides(self) -> None:
        root = ET.fromstring(self.model_settings)
        objects = root.findall("object")
        self.assertTrue(objects)
        meta = {el.get("key"): el.get("value") for el in objects[0].findall("metadata")}
        self.assertEqual(meta.get("layer_height"), "0.28")
        self.assertEqual(meta.get("sparse_infill_density"), "12%")
        self.assertEqual(meta.get("wall_loops"), "3")
        self.assertEqual(meta.get("enable_support"), "0")
        self.assertEqual(meta.get("brim_type"), "no_brim")
        parts = objects[0].findall("part")
        self.assertTrue(parts)
        self.assertEqual(parts[0].get("subtype"), "normal_part")
        self.assertIsNotNone(root.find("assemble"))


if __name__ == "__main__":
    unittest.main()
