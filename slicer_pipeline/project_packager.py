"""Pack analyzed geometry + Bambu Studio settings into a project `.3mf`."""

from __future__ import annotations

import json
import logging
import uuid
import zipfile
from io import BytesIO
from pathlib import Path
from typing import Any, Optional
from xml.sax.saxutils import escape

import numpy as np

from slicer_pipeline.constants import P2S_BED_MM, PRINTER_NAME
from slicer_pipeline.mesh_parser import MeshAssembly, MeshPart, _transform_to_attrib

LOGGER = logging.getLogger("auto_slicer")

_IDENTITY_16 = "1 0 0 0 0 1 0 0 0 0 1 0 0 0 0 1"


def _a(value: object) -> str:
    return escape(str(value), {'"': "&quot;"})


def _triangle_attrs(part: MeshPart, index: int, material_id: int) -> str:
    bits = [f' pid="{material_id}"']
    p1s = part.triangle_p1
    paints = part.paint_color
    if p1s and index < len(p1s) and p1s[index] is not None:
        bits.append(f' p1="{_a(p1s[index])}"')
    elif part.material_pindex is not None:
        bits.append(f' p1="{_a(part.material_pindex)}"')
    else:
        bits.append(f' p1="{max(part.extruder - 1, 0)}"')
    if paints and index < len(paints) and paints[index]:
        bits.append(f' paint_color="{_a(paints[index])}"')
    return "".join(bits)


def _mesh_xml(part: MeshPart, material_id: int) -> str:
    mesh = part.world_mesh()
    v = np.asarray(mesh.vertices, dtype=float)
    f = np.asarray(mesh.faces, dtype=np.int64)
    verts = "\n".join(f'        <vertex x="{x:.6f}" y="{y:.6f}" z="{z:.6f}" />' for x, y, z in v)
    tris = "\n".join(
        f'        <triangle v1="{a}" v2="{b}" v3="{c}"{_triangle_attrs(part, i, material_id)} />'
        for i, (a, b, c) in enumerate(f)
    )
    return (
        "      <mesh>\n"
        "        <vertices>\n"
        f"{verts}\n"
        "        </vertices>\n"
        "        <triangles>\n"
        f"{tris}\n"
        "        </triangles>\n"
        "      </mesh>"
    )


def _basematerials_xml(colors: list[str]) -> str:
    if not colors:
        colors = ["#FFFFFFFF"]
    rows = []
    for i, color in enumerate(colors, start=1):
        hex_color = color if color.startswith("#") else f"#{color}"
        if len(hex_color) == 7:
            hex_color += "FF"
        rows.append(f'        <base name="AMS{i}" displaycolor="{_a(hex_color)}" />')
    return (
        '    <basematerials id="1">\n'
        + "\n".join(rows)
        + "\n    </basematerials>"
    )


class ProjectPackager:
    """Write a Bambu Studio project archive: geometry + Metadata/*.config."""

    def pack(
        self,
        assembly: MeshAssembly,
        settings: dict[str, Any],
        output_path: Path,
        extra_meta: Optional[dict[str, Any]] = None,
        part_name: Optional[str] = None,
    ) -> Path:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(
            self.pack_bytes(assembly, settings, extra_meta=extra_meta, part_name=part_name)
        )
        LOGGER.info("Wrote Bambu Studio project: %s", output_path.resolve())
        return output_path

    def pack_bytes(
        self,
        assembly: MeshAssembly,
        settings: dict[str, Any],
        extra_meta: Optional[dict[str, Any]] = None,
        part_name: Optional[str] = None,
    ) -> bytes:
        working = self._prepare_assembly(assembly)
        colors = working.materials or ["#FFFFFFFF"]
        model_name = part_name or Path(working.filename).stem or "model"
        model_xml, model_settings, object_ids = self._build_model_documents(
            working, colors, model_name
        )
        content_types, rels, slice_info = self._static_xml()

        embed_settings = {k: v for k, v in settings.items() if not str(k).startswith("_")}
        sidecar = {
            "source": "bambu_studio_ai",
            "printer": PRINTER_NAME,
            "note": (
                "Bambu Studio project .3mf — open in Studio and Slice. "
                "Settings live in Metadata/project_settings.config. "
                "This is not a pre-sliced .gcode.3mf."
            ),
            "parts": [
                {
                    "name": p.name,
                    "extruder": p.extruder,
                    "color": p.color_hex,
                    "triangles": p.face_count,
                }
                for p in working.parts
            ],
            "filament_colours": colors,
            "object_ids": object_ids,
        }
        if extra_meta:
            sidecar.update(extra_meta)
        meta = settings.get("_auto_slicer_meta")
        if meta:
            sidecar["auto_slicer"] = meta

        buf = BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("[Content_Types].xml", content_types)
            zf.writestr("_rels/.rels", rels)
            zf.writestr("3D/3dmodel.model", model_xml)
            zf.writestr(
                "Metadata/project_settings.config",
                json.dumps(embed_settings, indent=4, ensure_ascii=False),
            )
            zf.writestr("Metadata/model_settings.config", model_settings)
            zf.writestr("Metadata/slice_info.config", slice_info)
            zf.writestr(
                "Metadata/auto_slicer.json",
                json.dumps(sidecar, indent=2, ensure_ascii=False),
            )
        return buf.getvalue()

    def _prepare_assembly(self, assembly: MeshAssembly) -> MeshAssembly:
        working = MeshAssembly(
            source_path=assembly.source_path,
            parts=[
                MeshPart(
                    name=p.name,
                    mesh=p.mesh.copy(),
                    transform=np.array(p.transform, copy=True),
                    color_rgba=None if p.color_rgba is None else np.array(p.color_rgba, copy=True),
                    color_hex=p.color_hex,
                    extruder=p.extruder,
                    object_id=p.object_id,
                    triangle_pid=list(p.triangle_pid) if p.triangle_pid else None,
                    triangle_p1=list(p.triangle_p1) if p.triangle_p1 else None,
                    paint_color=list(p.paint_color) if p.paint_color else None,
                    material_pid=p.material_pid,
                    material_pindex=p.material_pindex,
                )
                for p in assembly.parts
                if p.face_count > 0
            ],
            unit="millimeter",
            materials=list(assembly.materials),
        )
        # Bake instance transforms into vertices, then sit the assembly on the P2S bed.
        for part in working.parts:
            if not np.allclose(part.transform, np.eye(4)):
                part.mesh.apply_transform(part.transform)
                part.transform = np.eye(4, dtype=np.float64)
        working.center_on_bed(P2S_BED_MM)
        working.assign_extruders()
        return working

    def _build_model_documents(
        self,
        assembly: MeshAssembly,
        colors: list[str],
        model_name: str,
    ) -> tuple[str, str, dict[str, int]]:
        material_id = 1
        leaf_ids: list[int] = []
        object_blocks: list[str] = []
        part_settings: list[str] = []
        id_map: dict[str, int] = {}

        next_id = 2
        for part in assembly.parts:
            oid = next_id
            next_id += 1
            leaf_ids.append(oid)
            id_map[part.name] = oid
            obj_uuid = str(uuid.uuid4())
            pindex = max(part.extruder - 1, 0)
            object_blocks.append(
                f'    <object id="{oid}" p:UUID="{obj_uuid}" type="model" '
                f'name="{_a(part.name)}" pid="{material_id}" pindex="{pindex}">\n'
                f"{_mesh_xml(part, material_id)}\n"
                "    </object>"
            )
            part_settings.append(
                f'    <part id="{oid}">\n'
                f'      <metadata key="name" value="{_a(part.name)}"/>\n'
                f'      <metadata key="matrix" value="{_IDENTITY_16}"/>\n'
                f'      <metadata key="extruder" value="{part.extruder}"/>\n'
                "    </part>"
            )

        if len(leaf_ids) > 1:
            assembly_id = next_id
            assembly_uuid = str(uuid.uuid4())
            comps = "\n".join(
                f'        <component objectid="{oid}" transform="{_transform_to_attrib(np.eye(4))}" />'
                for oid in leaf_ids
            )
            object_blocks.append(
                f'    <object id="{assembly_id}" p:UUID="{assembly_uuid}" '
                f'type="model" name="{_a(model_name)}">\n'
                "      <components>\n"
                f"{comps}\n"
                "      </components>\n"
                "    </object>"
            )
            build_id = assembly_id
            instances_xml = (
                "    <model_instance>\n"
                f'      <metadata key="object_id" value="{assembly_id}"/>\n'
                '      <metadata key="instance_id" value="0"/>\n'
                "    </model_instance>"
            )
            object_config = (
                f'  <object id="{assembly_id}">\n'
                f'    <metadata key="name" value="{_a(model_name)}"/>\n'
                '    <metadata key="extruder" value="1"/>\n'
                + "\n".join(part_settings)
                + "\n  </object>"
            )
        else:
            build_id = leaf_ids[0]
            instances_xml = (
                "    <model_instance>\n"
                f'      <metadata key="object_id" value="{build_id}"/>\n'
                '      <metadata key="instance_id" value="0"/>\n'
                "    </model_instance>"
            )
            only = assembly.parts[0]
            object_config = (
                f'  <object id="{build_id}">\n'
                f'    <metadata key="name" value="{_a(only.name or model_name)}"/>\n'
                f'    <metadata key="extruder" value="{only.extruder}"/>\n'
                "  </object>"
            )

        build_uuid = str(uuid.uuid4())
        item_uuid = str(uuid.uuid4())
        model_xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<model unit="millimeter" xml:lang="en-US"
  xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02"
  xmlns:p="http://schemas.microsoft.com/3dmanufacturing/production/2015/06"
  xmlns:m="http://schemas.microsoft.com/3dmanufacturing/material/2015/02"
  requiredextensions="p">
  <metadata name="Application">BambuStudio-02.06.00.51</metadata>
  <metadata name="BambuStudio:3mfVersion">1</metadata>
  <metadata name="Title">{_a(model_name)}</metadata>
  <resources>
{_basematerials_xml(colors)}
{chr(10).join(object_blocks)}
  </resources>
  <build p:UUID="{build_uuid}">
    <item objectid="{build_id}" p:UUID="{item_uuid}" transform="1 0 0 0 1 0 0 0 1 0 0 0" />
  </build>
</model>
"""

        model_settings = f"""<?xml version="1.0" encoding="UTF-8"?>
<config>
{object_config}
  <plate>
    <metadata key="plater_id" value="1"/>
    <metadata key="plater_name" value="Plate 1"/>
    <metadata key="locked" value="false"/>
{instances_xml}
  </plate>
</config>
"""
        id_map["_build"] = build_id
        return model_xml, model_settings, id_map

    @staticmethod
    def _static_xml() -> tuple[str, str, str]:
        content_types = """<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>
  <Default Extension="config" ContentType="application/vnd.bambu.metadata+json"/>
  <Default Extension="json" ContentType="application/json"/>
  <Default Extension="xml" ContentType="application/xml"/>
</Types>
"""
        rels = """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Target="/3D/3dmodel.model"
    Id="rel-1"
    Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>
</Relationships>
"""
        slice_info = """<?xml version="1.0" encoding="UTF-8"?>
<config>
  <header>
    <header_item key="X-BBL-Client-Type" value="slicer"/>
    <header_item key="X-BBL-Client-Version" value="02.06.00.51"/>
  </header>
</config>
"""
        return content_types, rels, slice_info
