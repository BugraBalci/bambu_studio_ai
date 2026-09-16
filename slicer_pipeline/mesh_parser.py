"""Parse STL/OBJ/GLB/GLTF/3MF into a multi-body MeshAssembly.

Meshy AI `.3mf` files carry native colors and separate bodies. trimesh is used
to load sub-meshes *without* flattening (`force='mesh'` is never applied). A
second pass over the 3MF XML recovers materials, per-triangle paint, and the
object/component hierarchy that trimesh otherwise drops.
"""

from __future__ import annotations

import json
import logging
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator, Optional
from xml.etree import ElementTree as ET

import numpy as np
import trimesh

from slicer_pipeline.constants import (
    AMS_SLOT_CAP,
    P2S_BED_MM,
    SUPPORTED_MESH_SUFFIXES,
    _3MF_UNIT_TO_MM,
    _METER_SCALE_MAX_EXTENT,
    _METER_TO_MM,
    _METERISH_SUFFIXES,
)

LOGGER = logging.getLogger("auto_slicer")

_IDENTITY = np.eye(4, dtype=np.float64)


def _local_tag(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _find(el: ET.Element, local: str) -> ET.Element | None:
    return el.find(f"{{*}}{local}")


def _findall(el: ET.Element, local: str, recursive: bool = True) -> list[ET.Element]:
    path = f".//{{*}}{local}" if recursive else f"{{*}}{local}"
    return el.findall(path)


def _hex_rgba(color: np.ndarray | tuple | list | None) -> str | None:
    if color is None:
        return None
    arr = np.asarray(color, dtype=np.float64).flatten()
    if arr.size < 3:
        return None
    if arr.max() <= 1.0 + 1e-6:
        arr = arr * 255.0
    rgb = [int(np.clip(round(v), 0, 255)) for v in arr[:3]]
    alpha = int(np.clip(round(arr[3] if arr.size > 3 else 255), 0, 255))
    return f"#{rgb[0]:02X}{rgb[1]:02X}{rgb[2]:02X}{alpha:02X}"


def _parse_display_color(raw: str | None) -> np.ndarray | None:
    if not raw:
        return None
    s = raw.strip()
    if s.startswith("#"):
        s = s[1:]
    if len(s) == 6:
        s += "FF"
    if len(s) != 8:
        return None
    try:
        r = int(s[0:2], 16)
        g = int(s[2:4], 16)
        b = int(s[4:6], 16)
        a = int(s[6:8], 16)
    except ValueError:
        return None
    return np.array([r, g, b, a], dtype=np.uint8)


def _attrib_to_transform(attrib: dict[str, str]) -> np.ndarray:
    transform = np.eye(4, dtype=np.float64)
    raw = attrib.get("transform")
    if not raw:
        return transform
    values = np.array(raw.split(), dtype=np.float64)
    if values.size != 12:
        return transform
    transform[:3, :4] = values.reshape((4, 3)).T
    return transform


def _transform_to_attrib(matrix: np.ndarray) -> str:
    return " ".join(f"{v:.8g}" for v in np.asarray(matrix, dtype=np.float64)[:3, :4].T.flatten())


def _read_mesh_element(mesh_el: ET.Element) -> tuple[np.ndarray, np.ndarray]:
    vertices_el = _find(mesh_el, "vertices")
    faces_el = _find(mesh_el, "triangles")
    if vertices_el is None or faces_el is None:
        return np.zeros((0, 3), dtype=np.float64), np.zeros((0, 3), dtype=np.int64)

    vs = " ".join(
        f'{v.attrib["x"]} {v.attrib["y"]} {v.attrib["z"]}'
        for v in _findall(vertices_el, "vertex", recursive=False)
    )
    v_array = (
        np.fromstring(vs, dtype=np.float64, sep=" ").reshape((-1, 3))
        if vs
        else np.zeros((0, 3), dtype=np.float64)
    )

    tris = list(_findall(faces_el, "triangle", recursive=False))
    fs = " ".join(f'{t.attrib["v1"]} {t.attrib["v2"]} {t.attrib["v3"]}' for t in tris)
    f_array = (
        np.fromstring(fs, dtype=np.int64, sep=" ").reshape((-1, 3))
        if fs
        else np.zeros((0, 3), dtype=np.int64)
    )
    return v_array, f_array


def _triangle_style_attrs(mesh_el: ET.Element) -> dict[str, Any]:
    faces_el = _find(mesh_el, "triangles")
    if faces_el is None:
        return {}
    tris = list(_findall(faces_el, "triangle", recursive=False))
    n = len(tris)
    if n == 0:
        return {}
    pids = [_local_attr(t, "pid") for t in tris]
    p1s = [_local_attr(t, "p1") for t in tris]
    paints = [_local_attr(t, "paint_color") or _local_attr(t, "paintcolor") for t in tris]
    out: dict[str, Any] = {"count": n}
    if any(p is not None for p in pids):
        out["pid"] = pids
    if any(p is not None for p in p1s):
        out["p1"] = p1s
    if any(p for p in paints):
        out["paint_color"] = paints
    return out


def _visual_color(mesh: trimesh.Trimesh) -> np.ndarray | None:
    vis = getattr(mesh, "visual", None)
    if vis is None:
        return None
    try:
        main = getattr(vis, "main_color", None)
        if main is not None:
            arr = np.asarray(main).flatten()
            if arr.size >= 3 and np.any(arr[:3] > 0):
                return np.asarray(main, dtype=np.uint8).flatten()[:4]
    except Exception:  # noqa: BLE001
        pass
    material = getattr(vis, "material", None)
    if material is not None:
        for attr in ("baseColorFactor", "main_color", "diffuse"):
            value = getattr(material, attr, None)
            if value is None:
                continue
            arr = np.asarray(value, dtype=np.float64).flatten()
            if arr.size >= 3:
                return arr[:4] if arr.size >= 4 else np.append(arr[:3], 1.0)
    try:
        if hasattr(vis, "face_colors") and vis.face_colors is not None and len(vis.face_colors):
            return np.asarray(vis.face_colors[0], dtype=np.uint8)[:4]
    except Exception:  # noqa: BLE001
        pass
    return None


_PAINT_SLOT_CODES = (
    "4",
    "8",
    "0C",
    "1C",
    "2C",
    "3C",
    "4C",
    "5C",
    "6C",
    "7C",
    "8C",
    "9C",
    "AC",
    "BC",
    "CC",
    "DC",
)


def _norm_zip_path(name: str | None) -> str:
    return str(name or "").replace("\\", "/").lstrip("/").lower()


def _local_attr(el: ET.Element, name: str) -> str | None:
    if name in el.attrib:
        val = el.attrib.get(name)
        return val if val else None
    needle = name.lower()
    for key, val in el.attrib.items():
        local = key.rsplit("}", 1)[-1].lower()
        if local == needle:
            return val or None
    return None


def _obj_key(model_path: str, oid: str) -> str:
    return f"{_norm_zip_path(model_path)}::{oid}"


def _decode_paint_slot(raw: str | None) -> int | None:
    if not raw:
        return None
    s = str(raw).strip()
    if not s:
        return None
    upper = s.upper()
    for i, code in enumerate(_PAINT_SLOT_CODES):
        if upper == code:
            return i + 1
    rest = upper
    found: list[int] = []
    for i in range(len(_PAINT_SLOT_CODES) - 1, -1, -1):
        code = _PAINT_SLOT_CODES[i]
        if code in rest:
            rest = rest.replace(code, "")
            found.append(i + 1)
    if found:
        return min(found)
    if s.isdigit():
        n = int(s)
        return n if n > 0 else None
    return None


def _coerce_filament_palette(raw: Any) -> list[str]:
    if raw is None:
        return []
    parts: Any = raw
    if isinstance(raw, str):
        text = raw.strip()
        if text.startswith("["):
            try:
                parts = json.loads(text)
            except json.JSONDecodeError:
                parts = [p for p in text.strip("[]").replace('"', "").split(",") if p.strip()]
        else:
            parts = [p for p in text.replace(";", ",").split(",") if p.strip()]
    if not isinstance(parts, list):
        return []
    out: list[str] = []
    for item in parts:
        parsed = _parse_display_color(str(item).strip() if item is not None else None)
        hex_color = _hex_rgba(parsed)
        if hex_color:
            out.append(hex_color)
    return out


@dataclass
class MeshPart:
    """One printable body (Meshy sub-mesh / 3MF object instance)."""

    name: str
    mesh: trimesh.Trimesh
    transform: np.ndarray = field(default_factory=lambda: np.eye(4, dtype=np.float64))
    color_rgba: Optional[np.ndarray] = None
    color_hex: Optional[str] = None
    extruder: int = 1
    object_id: str = ""
    triangle_pid: Optional[list[str | None]] = None
    triangle_p1: Optional[list[str | None]] = None
    paint_color: Optional[list[str | None]] = None
    material_pid: Optional[str] = None
    material_pindex: Optional[str] = None

    def world_mesh(self) -> trimesh.Trimesh:
        m = self.mesh.copy()
        T = np.asarray(self.transform, dtype=np.float64)
        if not np.allclose(T, _IDENTITY):
            m.apply_transform(T)
        return m

    @property
    def face_count(self) -> int:
        return int(len(self.mesh.faces))


@dataclass
class MeshAssembly:
    """Hierarchy-preserving collection of sub-meshes plus analysis helpers."""

    source_path: Path
    parts: list[MeshPart] = field(default_factory=list)
    unit: str = "millimeter"
    materials: list[str] = field(default_factory=list)  # #RRGGBBAA unique colors
    notes: list[str] = field(default_factory=list)

    @property
    def filename(self) -> str:
        return self.source_path.name

    def combined_mesh(self) -> trimesh.Trimesh:
        geoms = [p.world_mesh() for p in self.parts if p.face_count > 0]
        if not geoms:
            raise ValueError(f"No triangle geometry in {self.filename}")
        if len(geoms) == 1:
            return geoms[0]
        return trimesh.util.concatenate(tuple(geoms))

    def apply_scale(self, scale: float) -> None:
        if abs(scale - 1.0) < 1e-15:
            return
        for part in self.parts:
            part.mesh.apply_scale(scale)

    def apply_translation(self, delta: np.ndarray) -> None:
        delta = np.asarray(delta, dtype=np.float64).reshape(3)
        T = np.eye(4, dtype=np.float64)
        T[:3, 3] = delta
        for part in self.parts:
            part.mesh.apply_transform(T)

    def bounds(self) -> np.ndarray:
        mins = []
        maxs = []
        for part in self.parts:
            if part.face_count == 0:
                continue
            b = part.world_mesh().bounds
            mins.append(b[0])
            maxs.append(b[1])
        if not mins:
            return np.zeros((2, 3), dtype=np.float64)
        return np.vstack([np.min(mins, axis=0), np.max(maxs, axis=0)])

    def center_on_bed(self, bed: tuple[float, float, float] = P2S_BED_MM) -> None:
        """Translate the whole assembly so it sits on Z=0, XY-centered on the bed."""
        bounds = self.bounds()
        center = (bounds[0] + bounds[1]) * 0.5
        delta = np.array(
            [bed[0] / 2.0 - center[0], bed[1] / 2.0 - center[1], -bounds[0][2]],
            dtype=np.float64,
        )
        self.apply_translation(delta)

    def assign_extruders(self, cap: int = AMS_SLOT_CAP) -> list[str]:
        """Map unique part colors onto AMS slots (1-based). Returns filament hex list."""
        palette: list[str] = [c for c in self.materials if c]
        for part in self.parts:
            hex_color = part.color_hex or _hex_rgba(part.color_rgba)
            if hex_color:
                part.color_hex = hex_color
                if hex_color not in palette:
                    palette.append(hex_color)
        if not palette:
            palette = ["#FFFFFFFF"]
        for part in self.parts:
            hex_color = part.color_hex or palette[0]
            idx = palette.index(hex_color) if hex_color in palette else 0
            part.extruder = min(idx, cap - 1) + 1
        self.materials = palette[:cap] if len(palette) > cap else palette
        return self.materials


class MeshParser:
    """Load a mesh file into a MeshAssembly without flattening part hierarchy."""

    def parse(self, path: Path) -> MeshAssembly:
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Model not found: {path}")
        suffix = path.suffix.lower()
        if suffix not in SUPPORTED_MESH_SUFFIXES:
            raise ValueError(f"Unsupported mesh format: {suffix or '(none)'}")

        LOGGER.info("Parsing mesh assembly: %s", path.name)
        if suffix == ".3mf":
            assembly = self._parse_3mf(path)
        else:
            assembly = self._parse_generic(path)

        if not assembly.parts:
            raise ValueError(f"No triangle geometry in {path.name}")

        self._maybe_scale_meters(assembly, suffix)
        assembly.assign_extruders()
        LOGGER.info(
            "Loaded %d part(s), %d unique color(s), %d triangles",
            len(assembly.parts),
            len(assembly.materials),
            sum(p.face_count for p in assembly.parts),
        )
        return assembly

    def _parse_generic(self, path: Path) -> MeshAssembly:
        suffix = path.suffix.lower()
        load_kwargs: dict[str, Any] = {"process": False}
        if suffix in {".glb", ".gltf"}:
            # Keep PBR materials, baseColorFactor, and textures for analysis/export.
            load_kwargs["skip_materials"] = False

        try:
            loaded = trimesh.load(path, **load_kwargs)
        except TypeError:
            load_kwargs.pop("skip_materials", None)
            loaded = trimesh.load(path, **load_kwargs)

        if isinstance(loaded, trimesh.Trimesh):
            color = _visual_color(loaded)
            part = MeshPart(
                name=path.stem,
                mesh=loaded,
                color_rgba=color,
                color_hex=_hex_rgba(color),
                object_id="1",
            )
            return MeshAssembly(source_path=path, parts=[part])

        if isinstance(loaded, trimesh.Scene):
            return self._assembly_from_scene(path, loaded)

        raise ValueError(f"Could not parse {path.name} as triangle geometry")

    def _parse_3mf(self, path: Path) -> MeshAssembly:
        xml_meta = self._parse_3mf_xml(path)
        model_paths = {rec.get("model_path") for rec in (xml_meta.get("object_map") or {}).values()}
        prefer_xml = bool(
            xml_meta.get("filament_palette")
            or xml_meta.get("extruders")
            or xml_meta.get("components")
            or len(model_paths) > 1
        )
        if prefer_xml:
            assembly = self._assembly_from_xml(path, xml_meta)
            if assembly.parts:
                self._seed_materials(assembly, xml_meta)
                return assembly
            LOGGER.warning("XML assembly for %s had no parts; trying trimesh", path.name)

        scene = self._trimesh_load_scene(path)
        if scene is not None:
            assembly = self._assembly_from_scene(path, scene, xml_meta)
            if assembly.parts:
                if xml_meta.get("unit"):
                    assembly.unit = xml_meta["unit"]
                    self._apply_unit_scale(assembly)
                self._seed_materials(assembly, xml_meta)
                return assembly
            LOGGER.warning("trimesh Scene for %s had no parts; using XML meshes", path.name)
        assembly = self._assembly_from_xml(path, xml_meta)
        self._seed_materials(assembly, xml_meta)
        return assembly

    def _trimesh_load_scene(self, path: Path) -> Optional[trimesh.Scene]:
        try:
            loaded = trimesh.load(path, process=False)
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning(
                "trimesh.load() failed for %s (%s); falling back to 3MF XML parser",
                path.name,
                exc,
            )
            return None
        if isinstance(loaded, trimesh.Trimesh):
            return trimesh.Scene(geometry={path.stem: loaded})
        if isinstance(loaded, trimesh.Scene):
            return loaded
        return None

    def _assembly_from_scene(
        self,
        path: Path,
        scene: trimesh.Scene,
        xml_meta: Optional[dict[str, Any]] = None,
    ) -> MeshAssembly:
        xml_meta = xml_meta or {}
        objects: list[dict[str, Any]] = xml_meta.get("objects") or []
        unused_xml = list(objects)
        parts: list[MeshPart] = []

        nodes = list(getattr(scene.graph, "nodes_geometry", []) or [])
        if not nodes:
            for name, geom in scene.geometry.items():
                if isinstance(geom, trimesh.Trimesh) and len(geom.faces):
                    parts.append(self._part_from_geom(name, geom, _IDENTITY, unused_xml))
            return MeshAssembly(source_path=path, parts=parts, unit=xml_meta.get("unit", "millimeter"))

        for node in nodes:
            try:
                transform, geom_name = scene.graph.get(node)
            except Exception:  # noqa: BLE001
                continue
            geom = scene.geometry.get(geom_name)
            if not isinstance(geom, trimesh.Trimesh) or len(geom.faces) == 0:
                continue
            T = np.asarray(transform if transform is not None else _IDENTITY, dtype=np.float64)
            parts.append(self._part_from_geom(str(geom_name), geom, T, unused_xml))

        return MeshAssembly(source_path=path, parts=parts, unit=xml_meta.get("unit", "millimeter"))

    def _part_from_geom(
        self,
        name: str,
        geom: trimesh.Trimesh,
        transform: np.ndarray,
        unused_xml: list[dict[str, Any]],
    ) -> MeshPart:
        xml_obj = self._match_xml_object(name, geom, unused_xml)
        color = None
        hex_color = None
        triangle_pid = triangle_p1 = paint = None
        material_pid = material_pindex = None
        object_id = ""
        if xml_obj is not None:
            color = xml_obj.get("color_rgba")
            hex_color = xml_obj.get("color_hex")
            triangle_pid = xml_obj.get("triangle_pid")
            triangle_p1 = xml_obj.get("triangle_p1")
            paint = xml_obj.get("paint_color")
            material_pid = xml_obj.get("pid")
            material_pindex = xml_obj.get("pindex")
            object_id = str(xml_obj.get("id") or "")
            name = xml_obj.get("name") or name
            try:
                extruder = int(xml_obj.get("extruder") or 1)
            except (TypeError, ValueError):
                extruder = 1
        else:
            extruder = 1
        if color is None:
            color = _visual_color(geom)
            hex_color = _hex_rgba(color)
        return MeshPart(
            name=str(name),
            mesh=geom.copy(),
            transform=transform,
            color_rgba=color,
            color_hex=hex_color,
            extruder=max(1, extruder),
            object_id=object_id,
            triangle_pid=triangle_pid,
            triangle_p1=triangle_p1,
            paint_color=paint,
            material_pid=material_pid,
            material_pindex=material_pindex,
        )

    @staticmethod
    def _match_xml_object(
        name: str,
        geom: trimesh.Trimesh,
        unused_xml: list[dict[str, Any]],
    ) -> Optional[dict[str, Any]]:
        if not unused_xml:
            return None
        n_faces = int(len(geom.faces))
        n_verts = int(len(geom.vertices))
        name_l = name.lower()
        for i, obj in enumerate(unused_xml):
            obj_name = str(obj.get("name") or "").lower()
            if obj_name and (obj_name == name_l or obj_name in name_l or name_l in obj_name):
                return unused_xml.pop(i)
        for i, obj in enumerate(unused_xml):
            if obj.get("face_count") == n_faces and obj.get("vertex_count") == n_verts:
                return unused_xml.pop(i)
        for i, obj in enumerate(unused_xml):
            if obj.get("face_count") == n_faces:
                return unused_xml.pop(i)
        return unused_xml.pop(0)

    def _parse_3mf_xml(self, path: Path) -> dict[str, Any]:
        try:
            with zipfile.ZipFile(path) as zf:
                names = zf.namelist()
                main_name = next(
                    (n for n in names if _norm_zip_path(n).endswith("3d/3dmodel.model")),
                    None,
                )
                if main_name is None:
                    LOGGER.warning("3MF archive %s has no 3D/3dmodel.model", path.name)
                    return {}
                docs: dict[str, ET.Element] = {}
                for n in names:
                    if not _norm_zip_path(n).endswith(".model"):
                        continue
                    try:
                        with zf.open(n) as fh:
                            docs[_norm_zip_path(n)] = ET.parse(fh).getroot()
                    except Exception as exc:  # noqa: BLE001
                        LOGGER.warning("Failed to parse %s in %s: %s", n, path.name, exc)
                filament_palette, extruders = self._load_bambu_sidecar(zf)
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("3MF XML parse failed for %s: %s", path.name, exc)
            return {}

        main_path = _norm_zip_path(main_name)
        main_root = docs.get(main_path)
        if main_root is None:
            return {}

        unit = (main_root.attrib.get("unit") or "millimeter").lower()
        resources: dict[str, list[str]] = {}
        object_map: dict[str, dict[str, Any]] = {}
        components: dict[str, list[tuple[str, np.ndarray]]] = {}

        for model_path, root in docs.items():
            parsed = self._parse_color_resources(root)
            for gid, colors in parsed.items():
                resources[gid] = colors
                resources[f"{model_path}::{gid}"] = colors
            self._ingest_model_objects(root, model_path, object_map, components)

        for rec in object_map.values():
            ext = rec.get("extruder") or extruders.get(str(rec.get("id")))
            if ext:
                rec["extruder"] = ext
            rec["color_rgba"], rec["color_hex"] = self._resolve_object_color(
                rec, resources, filament_palette
            )

        objects = [rec for rec in object_map.values() if rec.get("face_count", 0) > 0]
        build_items: list[tuple[str, np.ndarray]] = []
        for build in _findall(main_root, "build"):
            for item in _findall(build, "item"):
                oid = _local_attr(item, "objectid")
                if not oid:
                    continue
                item_path = _norm_zip_path(_local_attr(item, "path") or main_path)
                build_items.append((_obj_key(item_path, oid), _attrib_to_transform(item.attrib)))

        return {
            "unit": unit,
            "resources": resources,
            "objects": objects,
            "object_map": object_map,
            "components": components,
            "build_items": build_items,
            "filament_palette": filament_palette,
            "extruders": extruders,
        }

    def _ingest_model_objects(
        self,
        root: ET.Element,
        model_path: str,
        object_map: dict[str, dict[str, Any]],
        components: dict[str, list[tuple[str, np.ndarray]]],
    ) -> None:
        for obj in _findall(root, "object"):
            oid = _local_attr(obj, "id") or obj.attrib.get("id")
            if not oid:
                continue
            rec = self._object_record(obj, oid)
            rec["model_path"] = model_path
            key = _obj_key(model_path, oid)
            object_map[key] = rec
            comps: list[tuple[str, np.ndarray]] = []
            for comp in _findall(obj, "component"):
                child = _local_attr(comp, "objectid")
                if not child:
                    continue
                child_path = _norm_zip_path(_local_attr(comp, "path") or model_path)
                comps.append((_obj_key(child_path, child), _attrib_to_transform(comp.attrib)))
            if comps:
                components[key] = comps

    def _object_record(self, obj: ET.Element, oid: str) -> dict[str, Any]:
        name = obj.attrib.get("name") or oid
        pid = obj.attrib.get("pid")
        pindex = obj.attrib.get("pindex")
        extruder = _local_attr(obj, "extruder")
        direct_meshes = [m for m in obj if _local_tag(m.tag) == "mesh"]
        verts_list: list[np.ndarray] = []
        faces_list: list[np.ndarray] = []
        style: dict[str, Any] = {}
        for mesh_el in direct_meshes:
            v, f = _read_mesh_element(mesh_el)
            if len(f) == 0:
                continue
            offset = sum(len(x) for x in verts_list)
            verts_list.append(v)
            faces_list.append(f + offset)
            if not style:
                style = _triangle_style_attrs(mesh_el)
        return {
            "id": oid,
            "name": name,
            "pid": pid,
            "pindex": pindex,
            "extruder": extruder,
            "vertices": np.concatenate(verts_list) if verts_list else None,
            "faces": np.concatenate(faces_list) if faces_list else None,
            "face_count": int(sum(len(f) for f in faces_list)),
            "vertex_count": int(sum(len(v) for v in verts_list)),
            "triangle_pid": style.get("pid"),
            "triangle_p1": style.get("p1"),
            "paint_color": style.get("paint_color"),
        }

    @staticmethod
    def _load_bambu_sidecar(zf: zipfile.ZipFile) -> tuple[list[str], dict[str, str]]:
        palette: list[str] = []
        extruders: dict[str, str] = {}
        for name in zf.namelist():
            p = _norm_zip_path(name)
            try:
                if p.endswith("metadata/project_settings.config") or p.endswith("project_settings.config"):
                    text = zf.read(name).decode("utf-8", errors="replace")
                    parsed = MeshParser._parse_filament_palette_text(text)
                    if parsed:
                        palette = parsed
                if p.endswith("metadata/model_settings.config") or p.endswith("model_settings.config"):
                    text = zf.read(name).decode("utf-8", errors="replace")
                    extruders.update(MeshParser._parse_model_settings_extruders(text))
            except Exception as exc:  # noqa: BLE001
                LOGGER.warning("Failed reading Bambu sidecar %s: %s", name, exc)
        return palette, extruders

    @staticmethod
    def _parse_filament_palette_text(text: str) -> list[str]:
        trimmed = (text or "").strip()
        if not trimmed:
            return []
        if trimmed.startswith("{") or trimmed.startswith("["):
            try:
                data = json.loads(trimmed)
            except json.JSONDecodeError:
                data = None
            if isinstance(data, dict):
                for key in (
                    "filament_colour",
                    "filament_colors",
                    "filament_colours",
                    "default_filament_colour",
                ):
                    pal = _coerce_filament_palette(data.get(key))
                    if pal:
                        return pal
            elif isinstance(data, list):
                pal = _coerce_filament_palette(data)
                if pal:
                    return pal
        for key in ("filament_colour", "filament_colors", "filament_colours", "default_filament_colour"):
            match = re.search(rf'"{key}"\s*:\s*(\[[\s\S]*?\])', text, flags=re.I)
            if match:
                pal = _coerce_filament_palette(match.group(1))
                if pal:
                    return pal
        return []

    @staticmethod
    def _parse_model_settings_extruders(xml_text: str) -> dict[str, str]:
        out: dict[str, str] = {}
        if not xml_text:
            return out
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError:
            return out
        for obj in _findall(root, "object"):
            oid = _local_attr(obj, "id")
            obj_ext = None
            for meta in list(obj):
                if _local_tag(meta.tag) == "metadata" and (
                    meta.attrib.get("key") == "extruder" or _local_attr(meta, "key") == "extruder"
                ):
                    obj_ext = meta.attrib.get("value") or _local_attr(meta, "value")
            if oid and obj_ext:
                out[str(oid)] = str(obj_ext)
            for part in _findall(obj, "part"):
                pid = _local_attr(part, "id")
                part_ext = obj_ext
                for meta in list(part):
                    if _local_tag(meta.tag) == "metadata" and (
                        meta.attrib.get("key") == "extruder" or _local_attr(meta, "key") == "extruder"
                    ):
                        part_ext = meta.attrib.get("value") or _local_attr(meta, "value")
                if pid and part_ext:
                    out[str(pid)] = str(part_ext)
        return out

    def _parse_color_resources(self, root: ET.Element) -> dict[str, list[str]]:
        """resource id -> list of #RRGGBBAA colors (basematerials / colorgroup)."""
        resources: dict[str, list[str]] = {}
        for base_group in _findall(root, "basematerials"):
            gid = base_group.attrib.get("id")
            if not gid:
                continue
            colors: list[str] = []
            for base in base_group:
                if _local_tag(base.tag) != "base":
                    continue
                rgba = _parse_display_color(base.attrib.get("displaycolor"))
                colors.append(_hex_rgba(rgba) or "#FFFFFFFF")
            resources[gid] = colors
        for group in _findall(root, "colorgroup"):
            gid = group.attrib.get("id")
            if not gid:
                continue
            colors = []
            for color_el in group:
                if _local_tag(color_el.tag) != "color":
                    continue
                rgba = _parse_display_color(color_el.attrib.get("color"))
                colors.append(_hex_rgba(rgba) or "#FFFFFFFF")
            resources[gid] = colors
        return resources

    def _resolve_object_color(
        self,
        rec: dict[str, Any],
        resources: dict[str, list[str]],
        filament_palette: Optional[list[str]] = None,
    ) -> tuple[Optional[np.ndarray], Optional[str]]:
        palette = filament_palette or []
        paints = rec.get("paint_color") or []
        paint_hit = next((p for p in paints if p), None)
        if paint_hit:
            slot = _decode_paint_slot(paint_hit)
            if slot is not None and palette:
                idx = slot - 1 if slot >= 1 else slot
                if 0 <= idx < len(palette):
                    hex_color = palette[idx]
                    return _parse_display_color(hex_color), hex_color
            rgba = _parse_display_color(paint_hit if str(paint_hit).startswith("#") else f"#{paint_hit}")
            if rgba is not None:
                return rgba, _hex_rgba(rgba)

        pid = rec.get("pid")
        pindex = rec.get("pindex")
        p1s = rec.get("triangle_p1") or []
        model_path = rec.get("model_path") or ""
        resource_keys = [f"{model_path}::{pid}" if pid else None, pid]
        if not pindex and p1s:
            pindex = next((p for p in p1s if p is not None), None)
        for key in resource_keys:
            if not key or key not in resources:
                continue
            group = resources[key]
            try:
                idx = int(pindex) if pindex is not None else 0
            except ValueError:
                idx = 0
            if 0 <= idx < len(group):
                hex_color = group[idx]
                return _parse_display_color(hex_color), hex_color

        if pid and p1s:
            counts: dict[str, int] = {}
            for p1 in p1s:
                if p1 is None:
                    continue
                counts[p1] = counts.get(p1, 0) + 1
            if counts:
                dominant = max(counts, key=counts.get)  # type: ignore[arg-type]
                try:
                    idx = int(dominant)
                except ValueError:
                    idx = 0
                for key in resource_keys:
                    if not key or key not in resources:
                        continue
                    group = resources[key]
                    if 0 <= idx < len(group):
                        hex_color = group[idx]
                        return _parse_display_color(hex_color), hex_color

        if palette:
            try:
                slot = int(rec.get("extruder") or 1)
            except (TypeError, ValueError):
                slot = 1
            idx = max(0, slot - 1)
            if idx < len(palette):
                hex_color = palette[idx]
                return _parse_display_color(hex_color), hex_color
        return None, None

    def _assembly_from_xml(self, path: Path, xml_meta: dict[str, Any]) -> MeshAssembly:
        object_map: dict[str, dict[str, Any]] = xml_meta.get("object_map") or {}
        components: dict[str, list[tuple[str, np.ndarray]]] = xml_meta.get("components") or {}
        build_items: list[tuple[str, np.ndarray]] = xml_meta.get("build_items") or []
        if not build_items:
            build_items = [(oid, _IDENTITY.copy()) for oid in object_map]

        parts: list[MeshPart] = []
        for oid, transform in build_items:
            for rec, world_T in self._walk_instances(oid, transform, object_map, components):
                verts = rec.get("vertices")
                faces = rec.get("faces")
                if verts is None or faces is None or len(faces) == 0:
                    continue
                mesh = trimesh.Trimesh(vertices=verts, faces=faces, process=False)
                try:
                    extruder = int(rec.get("extruder") or 1)
                except (TypeError, ValueError):
                    extruder = 1
                parts.append(
                    MeshPart(
                        name=str(rec.get("name") or rec["id"]),
                        mesh=mesh,
                        transform=world_T,
                        color_rgba=rec.get("color_rgba"),
                        color_hex=rec.get("color_hex"),
                        extruder=max(1, extruder),
                        object_id=str(rec["id"]),
                        triangle_pid=rec.get("triangle_pid"),
                        triangle_p1=rec.get("triangle_p1"),
                        paint_color=rec.get("paint_color"),
                        material_pid=rec.get("pid"),
                        material_pindex=rec.get("pindex"),
                    )
                )

        assembly = MeshAssembly(
            source_path=path,
            parts=parts,
            unit=xml_meta.get("unit", "millimeter"),
        )
        self._apply_unit_scale(assembly)
        return assembly

    def _walk_instances(
        self,
        oid: str,
        parent_T: np.ndarray,
        object_map: dict[str, dict[str, Any]],
        components: dict[str, list[tuple[str, np.ndarray]]],
        stack: Optional[set[str]] = None,
    ) -> Iterator[tuple[dict[str, Any], np.ndarray]]:
        stack = set(stack or ())
        if oid in stack:
            return
        stack.add(oid)
        rec = object_map.get(oid)
        if rec is None and "::" not in str(oid):
            matches = [k for k in object_map if str(k).endswith(f"::{oid}")]
            if len(matches) == 1:
                oid = matches[0]
                rec = object_map[oid]
        if rec is not None and rec.get("face_count", 0) > 0:
            yield rec, parent_T
        for child_id, child_T in components.get(oid, []):
            yield from self._walk_instances(
                child_id,
                parent_T @ child_T,
                object_map,
                components,
                stack,
            )

    @staticmethod
    def _seed_materials(assembly: MeshAssembly, xml_meta: dict[str, Any]) -> None:
        filament = xml_meta.get("filament_palette") or []
        if filament:
            assembly.materials = list(filament)
            return
        resources = xml_meta.get("resources") or {}
        palette: list[str] = []
        for colors in resources.values():
            for color in colors:
                if color and color not in palette:
                    palette.append(color)
        if palette:
            assembly.materials = palette

    def _apply_unit_scale(self, assembly: MeshAssembly) -> None:
        scale = _3MF_UNIT_TO_MM.get(assembly.unit.lower(), 1.0)
        if abs(scale - 1.0) < 1e-15:
            return
        assembly.apply_scale(scale)
        LOGGER.info("Scaled %s from unit=%s to millimetres (×%g)", assembly.filename, assembly.unit, scale)
        assembly.unit = "millimeter"

    def _maybe_scale_meters(self, assembly: MeshAssembly, suffix: str) -> None:
        if suffix not in _METERISH_SUFFIXES:
            return
        bounds = assembly.bounds()
        extents = bounds[1] - bounds[0]
        max_ext = float(np.max(extents)) if extents.size else 0.0
        if 1e-9 < max_ext < _METER_SCALE_MAX_EXTENT:
            assembly.apply_scale(_METER_TO_MM)
            LOGGER.info("Scaled %s from meters to millimetres (×%g)", assembly.filename, _METER_TO_MM)


def load_triangle_mesh(path: Path) -> trimesh.Trimesh:
    """Combined triangle mesh for analysis (parts are concatenated, not discarded)."""
    return MeshParser().parse(path).combined_mesh()
