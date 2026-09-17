"""Text & badge engine: flush modifier vs embossed part, planar vs wrap."""

from __future__ import annotations

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
from app.services.bambu_3mf import write_bambu_3mf_bytes  # noqa: E402
from app.services.rules import build_slicer_hints  # noqa: E402
from slicer_pipeline.mesh_parser import MeshAssembly, MeshPart  # noqa: E402
from slicer_pipeline.text_engine import (  # noqa: E402
    FLUSH_EXPLANATION_TR,
    WRAP_EXPLANATION_TR,
    TextSpec,
    analyze_target_surface,
    apply_text_to_assembly,
    build_text_volume,
    spec_from_mapping,
)


def _rec() -> PrintRecommendation:
    data = {
        "material": "PLA",
        "nozzle_mm": 0.4,
        "layer_height_mm": 0.2,
        "wall_loops": 3,
        "infill_percent": 15,
        "infill_pattern": "grid",
        "nozzle_temp_c": 210,
        "bed_temp_c": 60,
        "supports": False,
        "brim": False,
        "rationale": "test",
    }
    data["slicer_hints"] = build_slicer_hints(data)
    return PrintRecommendation(**data)


class SurfaceClassificationTests(unittest.TestCase):
    def test_box_is_planar(self) -> None:
        mesh = trimesh.creation.box(extents=(30.0, 24.0, 8.0))
        surface = analyze_target_surface(mesh)
        self.assertEqual(surface.kind, "planar")
        self.assertFalse(surface.wrap_recommended)

    def test_cylinder_recommends_wrap(self) -> None:
        mesh = trimesh.creation.cylinder(radius=18.0, height=42.0, sections=48)
        surface = analyze_target_surface(mesh)
        self.assertIn(surface.kind, {"cylindrical", "curved"})
        self.assertTrue(surface.wrap_recommended)
        self.assertGreater(surface.cylinder_radius, 12.0)


class TextGeometryTests(unittest.TestCase):
    def test_embossed_raises_above_the_top_skin(self) -> None:
        host = trimesh.creation.box(extents=(40.0, 28.0, 10.0))
        spec = TextSpec(content="AB", style="embossed", surface_mode="planar", height_mm=0.6, size_mm=8.0)
        built = build_text_volume(host, spec)
        self.assertFalse(built.wrap_applied)
        self.assertEqual(built.spec.subtype, "normal_part")
        host_top = float(host.bounds[1, 2])
        text_top = float(built.mesh.bounds[1, 2])
        self.assertGreater(text_top, host_top + 0.35)
        self.assertLess(text_top, host_top + 1.2)

    def test_flush_stays_coplanar_and_inlays(self) -> None:
        host = trimesh.creation.box(extents=(40.0, 28.0, 10.0))
        spec = TextSpec(content="OK", style="flush", surface_mode="planar", inlay_depth_mm=0.8, size_mm=8.0)
        built = build_text_volume(host, spec)
        self.assertEqual(built.spec.subtype, "modifier_part")
        host_top = float(host.bounds[1, 2])
        text_top = float(built.mesh.bounds[1, 2])
        text_bot = float(built.mesh.bounds[0, 2])
        self.assertLess(abs(text_top - host_top), 0.25)
        self.assertLess(text_bot, host_top - 0.45)
        self.assertIn("gömülür", built.explanations["flush"])

    def test_cylinder_wrap_snaps_to_radius(self) -> None:
        host = trimesh.creation.cylinder(radius=16.0, height=36.0, sections=64)
        spec = TextSpec(content="CUP", style="embossed", surface_mode="curved", height_mm=0.6, size_mm=7.0)
        built = build_text_volume(host, spec)
        self.assertTrue(built.wrap_applied)
        xy = np.asarray(built.mesh.vertices)[:, :2]
        center = np.asarray(built.surface.cylinder_center)[:2]
        radii = np.linalg.norm(xy - center, axis=1)
        self.assertTrue(np.median(radii) > 14.5)
        self.assertTrue(np.median(radii) < 18.5)
        self.assertIn("Çevreleyen Yüzey", WRAP_EXPLANATION_TR)

    def test_embossed_style_survives_enum_stringification(self) -> None:
        spec = TextSpec(content="HI", style="embossed", surface_mode="curved")
        self.assertEqual(spec.style, "embossed")
        self.assertEqual(spec.subtype, "normal_part")
        mapped = spec_from_mapping({"enabled": True, "content": "HI", "style": "embossed"})
        self.assertEqual(mapped.style, "embossed")
        host = trimesh.creation.box(extents=(24.0, 18.0, 8.0))
        assembly = MeshAssembly(
            source_path=Path("badge.stl"),
            parts=[MeshPart(name="host", mesh=host, color_hex="#FFFFFFFF", extruder=1)],
            materials=["#FFFFFFFF"],
        )
        spec = TextSpec(content="HI", style="flush", surface_mode="planar", size_mm=6.0, extruder=2)
        result = apply_text_to_assembly(assembly, spec)
        self.assertEqual(len(assembly.parts), 2)
        self.assertEqual(assembly.parts[-1].subtype, "modifier_part")
        self.assertEqual(assembly.parts[-1].extruder, 2)
        self.assertTrue(assembly.parts[-1].lock_extruder)
        self.assertGreaterEqual(len(assembly.materials), 2)
        self.assertEqual(result.spec.subtype, "modifier_part")
        self.assertTrue(FLUSH_EXPLANATION_TR.startswith("Pürüzsüz"))


class Text3mfExportTests(unittest.TestCase):
    def test_flush_modifier_and_second_filament(self) -> None:
        host = trimesh.creation.box(extents=(30.0, 20.0, 8.0))
        spec = TextSpec(
            content="P2S",
            style="flush",
            surface_mode="planar",
            size_mm=7.0,
            color_hex="#1C1C1CFF",
            extruder=2,
        )
        rec = _rec()
        rec.wall_generator = "arachne"
        rec.slicer_hints["wall_generator"] = "arachne"
        with tempfile.TemporaryDirectory() as tmp:
            stl_path = Path(tmp) / "plate.stl"
            host.export(stl_path)
            data = write_bambu_3mf_bytes(stl_path, rec, part_name="plate", text_spec=spec)
        with zipfile.ZipFile(BytesIO(data)) as zf:
            settings_xml = zf.read("Metadata/model_settings.config").decode("utf-8")
            sidecar = zf.read("Metadata/auto_slicer.json").decode("utf-8")
            project = zf.read("Metadata/project_settings.config").decode("utf-8")
        root = ET.fromstring(settings_xml)
        parts = root.findall("object/part")
        subtypes = [part.get("subtype") for part in parts]
        self.assertIn("normal_part", subtypes)
        self.assertIn("modifier_part", subtypes)
        self.assertIn("Text", sidecar)
        self.assertGreaterEqual(len(parts), 2)

    def test_embossed_enables_arachne(self) -> None:
        host = trimesh.creation.box(extents=(26.0, 18.0, 8.0))
        spec = TextSpec(content="R", style="embossed", surface_mode="planar", size_mm=8.0)
        rec = _rec()
        with tempfile.TemporaryDirectory() as tmp:
            stl_path = Path(tmp) / "tag.stl"
            host.export(stl_path)
            data = write_bambu_3mf_bytes(stl_path, rec, part_name="tag", text_spec=spec)
        with zipfile.ZipFile(BytesIO(data)) as zf:
            project = zf.read("Metadata/project_settings.config").decode("utf-8")
            settings_xml = zf.read("Metadata/model_settings.config").decode("utf-8")
        self.assertIn("arachne", project.lower())
        self.assertIn('subtype="normal_part"', settings_xml)


if __name__ == "__main__":
    unittest.main()
