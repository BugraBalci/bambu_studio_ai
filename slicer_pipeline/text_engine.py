"""Embossed / flush text volumes with planar projection and curved wrapping.

Bambu Studio's Text tool has two volume types we reproduce here:

* **Part / Kabartmalı** — a `normal_part` extruded along the surface normal so
  the letters add 2–4 distinct top layers (~0.4–0.8 mm).
* **Modifier / Pürüzsüz (Gömülü)** — a `modifier_part` that occupies the same
  Z band as the host skin. Studio slices only the intersection, so the inlay
  prints flush with a second AMS slot and does not raise the part.

Curved models (cups, pots, rounded tags) use a cylindrical UV map plus a
closest-point snap so glyph vertices sit on the real contour ("Çevreleyen
Yüzey") instead of floating on a tangent plane.
"""

from __future__ import annotations

import logging
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import numpy as np
import trimesh
from PIL import Image, ImageDraw, ImageFont
from scipy import spatial

from slicer_pipeline.constants import AMS_SLOT_CAP
from slicer_pipeline.mesh_parser import MeshAssembly, MeshPart

LOGGER = logging.getLogger("auto_slicer")

EMBOSS_HEIGHT_MM = 0.6
FLUSH_DEPTH_MM = 0.8
TEXT_PITCH_MM = 0.14
TEXT_MAX_CHARS = 48
TEXT_MAX_LINES = 4
DEFAULT_TEXT_COLOR = "#1C1C1CFF"

FLUSH_EXPLANATION_TR = (
    "Pürüzsüz (Gömülü) Seçildi: Yazı modelin üst katmanlarına gömülür, "
    "çıkıntı yapmaz ve sürtünmeye dayanıklı dümdüz bir yüzey sağlar."
)
EMBOSS_EXPLANATION_TR = (
    "Kabartmalı Seçildi: Yazı model yüzeyinden {height:.1f} mm dışarı "
    "taşırılarak belirgin 3D dokunsal derinlik kazandırılır."
)
WRAP_EXPLANATION_TR = (
    "Çevreleyen Yüzey Aktif: Yazı kavisli/silindirik modelin eğimini "
    "otomatik takip ederek yüzeye tam oturur."
)
PLANAR_EXPLANATION_TR = (
    "Düzlem projeksiyon: Yazı hedef düzleme (genelde üst yüzey veya ön teğet) "
    "oturtulur; kavis takip edilmez."
)

_FONT_CANDIDATES = (
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    Path("/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"),
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    Path("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"),
    Path("/usr/share/fonts/truetype/freefont/FreeSansBold.ttf"),
    Path("/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf"),
)

_STYLE_FLUSH = "flush"
_STYLE_EMBOSSED = "embossed"
_MODE_PLANAR = "planar"
_MODE_CURVED = "curved"
_MODE_AUTO = "auto"


def _unit(vec: np.ndarray, fallback: Optional[np.ndarray] = None) -> np.ndarray:
    arr = np.asarray(vec, dtype=np.float64).reshape(3)
    n = float(np.linalg.norm(arr))
    if n < 1e-12:
        return np.array([0.0, 0.0, 1.0] if fallback is None else fallback, dtype=np.float64)
    return arr / n


def normalize_color_hex(value: Optional[str], default: str = DEFAULT_TEXT_COLOR) -> str:
    raw = str(value or "").strip()
    if not raw:
        return default
    if not raw.startswith("#"):
        raw = f"#{raw}"
    hex_body = raw[1:]
    if len(hex_body) == 6:
        hex_body += "FF"
    if len(hex_body) != 8:
        return default
    try:
        int(hex_body, 16)
    except ValueError:
        return default
    return f"#{hex_body.upper()}"


def sanitize_text(content: str) -> str:
    text = (content or "").replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[^\S\n]+", " ", text)
    lines = [line.strip() for line in text.split("\n")]
    lines = [line for line in lines if line][:TEXT_MAX_LINES]
    clipped: list[str] = []
    remaining = TEXT_MAX_CHARS
    for line in lines:
        if remaining <= 0:
            break
        clipped.append(line[:remaining])
        remaining -= len(clipped[-1])
    return "\n".join(clipped).strip()


def resolve_font_path() -> Optional[Path]:
    for path in _FONT_CANDIDATES:
        if path.is_file():
            return path
    return None


@dataclass
class SurfaceAnalysis:
    """Planar vs cylindrical read of the host mesh."""

    kind: str
    wrap_recommended: bool
    plane_point: np.ndarray
    plane_normal: np.ndarray
    plane_u: np.ndarray
    plane_v: np.ndarray
    cylinder_center: np.ndarray
    cylinder_axis: np.ndarray
    cylinder_radius: float
    cylinder_height: float
    note: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "wrap_recommended": self.wrap_recommended,
            "cylinder_radius_mm": round(float(self.cylinder_radius), 3),
            "cylinder_height_mm": round(float(self.cylinder_height), 3),
            "note": self.note,
        }


@dataclass
class TextSpec:
    content: str
    style: str = _STYLE_FLUSH
    surface_mode: str = _MODE_AUTO
    height_mm: float = EMBOSS_HEIGHT_MM
    inlay_depth_mm: float = FLUSH_DEPTH_MM
    size_mm: Optional[float] = None
    color_hex: str = DEFAULT_TEXT_COLOR
    extruder: int = 2
    filament_id: Optional[int] = None

    def __post_init__(self) -> None:
        self.content = sanitize_text(self.content)
        style = self.style
        if hasattr(style, "value"):
            style = style.value
        style = str(style or _STYLE_FLUSH).lower()
        self.style = _STYLE_EMBOSSED if style in {_STYLE_EMBOSSED, "part", "relief", "raised"} else _STYLE_FLUSH
        mode = self.surface_mode
        if hasattr(mode, "value"):
            mode = mode.value
        mode = str(mode or _MODE_AUTO).lower()
        if mode in {_MODE_CURVED, "wrap", "cevreleyen", "surrounding"}:
            self.surface_mode = _MODE_CURVED
        elif mode == _MODE_PLANAR:
            self.surface_mode = _MODE_PLANAR
        else:
            self.surface_mode = _MODE_AUTO
        self.height_mm = float(np.clip(self.height_mm or EMBOSS_HEIGHT_MM, 0.4, 0.8))
        self.inlay_depth_mm = float(np.clip(self.inlay_depth_mm or FLUSH_DEPTH_MM, 0.4, 1.2))
        self.color_hex = normalize_color_hex(self.color_hex)
        self.extruder = int(np.clip(int(self.extruder or 2), 1, AMS_SLOT_CAP))
        if self.size_mm is not None:
            self.size_mm = float(np.clip(self.size_mm, 3.0, 48.0))

    @property
    def enabled(self) -> bool:
        return bool(self.content)

    @property
    def subtype(self) -> str:
        return "modifier_part" if self.style == _STYLE_FLUSH else "normal_part"

    @property
    def thickness_mm(self) -> float:
        return self.inlay_depth_mm if self.style == _STYLE_FLUSH else self.height_mm


@dataclass
class TextBuildResult:
    mesh: trimesh.Trimesh
    spec: TextSpec
    surface: SurfaceAnalysis
    wrap_applied: bool
    letter_height_mm: float
    host_bounds: np.ndarray
    explanations: dict[str, str] = field(default_factory=dict)

    @property
    def subtype(self) -> str:
        return self.spec.subtype


def analyze_target_surface(mesh: trimesh.Trimesh) -> SurfaceAnalysis:
    """Classify the printable skin as planar, cylindrical, or freeform-curved."""
    host = mesh if isinstance(mesh, trimesh.Trimesh) else trimesh.Trimesh(mesh)
    bounds = np.asarray(host.bounds, dtype=np.float64)
    extents = bounds[1] - bounds[0]
    center = (bounds[0] + bounds[1]) * 0.5

    plane_normal = np.array([0.0, 0.0, 1.0], dtype=np.float64)
    plane_point = np.array([center[0], center[1], bounds[1, 2]], dtype=np.float64)
    try:
        normals = np.asarray(host.face_normals, dtype=np.float64)
        areas = np.asarray(host.area_faces, dtype=np.float64)
        if len(normals) and len(areas) == len(normals):
            up = normals[:, 2] > 0.85
            if np.any(up) and float(areas[up].sum()) > 1e-3:
                weights = areas[up]
                plane_normal = _unit(np.average(normals[up], axis=0, weights=weights))
                verts = np.asarray(host.vertices, dtype=np.float64)
                faces = np.asarray(host.faces, dtype=np.int64)[up]
                plane_point = verts[faces.reshape(-1)].mean(axis=0)
    except Exception as exc:  # noqa: BLE001
        LOGGER.debug("Top-plane fit failed: %s", exc)

    world_z = np.array([0.0, 0.0, 1.0], dtype=np.float64)
    plane_u = _unit(np.cross(world_z, plane_normal), fallback=np.array([1.0, 0.0, 0.0]))
    if float(np.linalg.norm(np.cross(world_z, plane_normal))) < 0.15:
        plane_u = np.array([1.0, 0.0, 0.0], dtype=np.float64)
    plane_v = _unit(np.cross(plane_normal, plane_u), fallback=np.array([0.0, 1.0, 0.0]))

    cylinder_axis = np.array([0.0, 0.0, 1.0], dtype=np.float64)
    cylinder_center = np.array([center[0], center[1], center[2]], dtype=np.float64)
    cylinder_radius = 0.5 * float(max(extents[0], extents[1], 1e-3))
    cylinder_height = float(extents[2])

    verts = np.asarray(host.vertices, dtype=np.float64)
    kind = "planar"
    wrap = False
    note = "Üst yüzey düzlem; yazı düz projeksiyonla oturtulur."
    if len(verts) >= 24:
        z = verts[:, 2]
        zspan = max(float(extents[2]), 1e-6)
        band = (z > bounds[0, 2] + 0.12 * zspan) & (z < bounds[1, 2] - 0.08 * zspan)
        sample = verts[band] if int(band.sum()) >= 40 else verts
        xy = sample[:, :2]
        cyl_c = np.median(xy, axis=0)
        radii = np.linalg.norm(xy - cyl_c, axis=1)
        r_med = float(np.median(radii))
        mad = float(np.median(np.abs(radii - r_med)))
        rel = (1.4826 * mad) / max(r_med, 1e-6)
        inlier = float(np.mean(np.abs(radii - r_med) < 0.16 * max(r_med, 1e-6)))
        cylinder_center = np.array([cyl_c[0], cyl_c[1], center[2]], dtype=np.float64)
        cylinder_radius = r_med
        if r_med >= 4.0 and inlier >= 0.62 and rel <= 0.18 and zspan >= 8.0:
            kind = "cylindrical"
            wrap = True
            note = (
                f"Silindirik gövde (r≈{r_med:.1f} mm). Çevreleyen yüzey sargısı önerilir."
            )
        else:
            try:
                nrm = np.asarray(host.face_normals, dtype=np.float64)
                var = float(np.mean(1.0 - np.abs(nrm[:, 2]))) if len(nrm) else 0.0
            except Exception:  # noqa: BLE001
                var = 0.0
            side_extent = float(min(extents[0], extents[1]))
            if var > 0.28 and zspan > 0.7 * side_extent and r_med >= 5.0:
                kind = "curved"
                wrap = True
                note = "Kavisli yüzey tespit edildi; yazı konturu çevreleyen sargı ile takip eder."
            else:
                note = "Hedef bölge düzlem (üst yüzey / rozet yüzü)."

    return SurfaceAnalysis(
        kind=kind,
        wrap_recommended=wrap,
        plane_point=plane_point,
        plane_normal=plane_normal,
        plane_u=plane_u,
        plane_v=plane_v,
        cylinder_center=cylinder_center,
        cylinder_axis=cylinder_axis,
        cylinder_radius=cylinder_radius,
        cylinder_height=cylinder_height,
        note=note,
    )


def auto_letter_height_mm(mesh: trimesh.Trimesh, surface: SurfaceAnalysis, text: str) -> float:
    lines = sanitize_text(text).split("\n") or ["A"]
    nlines = max(len(lines), 1)
    longest = max(len(line) for line in lines)
    extents = np.asarray(mesh.extents, dtype=np.float64)
    if surface.wrap_recommended and surface.cylinder_radius >= 4.0:
        arc = surface.cylinder_radius * math.pi * 0.55
        height_budget = max(surface.cylinder_height * 0.22, 6.0)
        char_h = min(height_budget / nlines, arc / max(longest * 0.72, 1.0))
    else:
        span = float(min(max(extents[0], 1.0), max(extents[1], 1.0)))
        char_h = min(span * 0.22 / nlines, span * 0.62 / max(longest * 0.72, 1.0))
    return float(np.clip(char_h, 4.0, 28.0))


def _load_font(px: int) -> ImageFont.ImageFont:
    path = resolve_font_path()
    if path is not None:
        try:
            return ImageFont.truetype(str(path), size=max(10, int(px)))
        except OSError:
            LOGGER.warning("Failed to load font %s", path)
    return ImageFont.load_default()


def _rasterize_text(text: str, letter_height_mm: float, pitch: float) -> tuple[np.ndarray, float]:
    target_px = max(18, int(round(letter_height_mm / max(pitch, 0.05))))
    font = _load_font(target_px)
    dummy = ImageDraw.Draw(Image.new("L", (8, 8)))
    probe = dummy.textbbox((0, 0), "Hğ", font=font) if hasattr(dummy, "textbbox") else (0, 0, target_px, target_px)
    probe_h = max(int(probe[3] - probe[1]), 1)
    if probe_h > 0 and abs(probe_h - target_px) > 2 and resolve_font_path() is not None:
        scaled = max(10, int(round(target_px * target_px / probe_h)))
        font = _load_font(scaled)

    lines = text.split("\n")
    widths: list[int] = []
    heights: list[int] = []
    for line in lines:
        box = dummy.textbbox((0, 0), line, font=font)
        widths.append(max(int(box[2] - box[0]), 1))
        heights.append(max(int(box[3] - box[1]), 1))
    line_gap = max(int(round(0.22 * max(heights or [target_px]))), 2)
    img_w = max(widths) + 12
    img_h = sum(heights) + line_gap * (len(lines) - 1) + 12
    image = Image.new("L", (img_w, img_h), 0)
    draw = ImageDraw.Draw(image)
    y = 6
    for line, w, h in zip(lines, widths, heights):
        x = 6 + (max(widths) - w) // 2
        draw.text((x, y), line, fill=255, font=font)
        y += h + line_gap
    mask = np.asarray(image, dtype=np.uint8)
    mask = np.flipud(mask) > 96
    if not np.any(mask):
        raise ValueError("Yazı geometrisi üretilemedi.")
    return mask, pitch


def _extrude_mask(mask: np.ndarray, pitch: float, thickness: float) -> trimesh.Trimesh:
    """Watertight 2.5D extrusion that preserves holes (A, O, B, 8)."""
    solid = np.pad(mask.astype(bool), 1, constant_values=False)
    h, w = mask.shape
    key_to_i: dict[tuple[int, int, int], int] = {}
    verts: list[list[float]] = []
    faces: list[list[int]] = []

    def vid(ix: int, iy: int, iz: int) -> int:
        key = (ix, iy, iz)
        existing = key_to_i.get(key)
        if existing is not None:
            return existing
        idx = len(verts)
        key_to_i[key] = idx
        verts.append([ix * pitch, iy * pitch, iz * thickness])
        return idx

    def quad(a: int, b: int, c: int, d: int) -> None:
        faces.append([a, b, c])
        faces.append([a, c, d])

    for y in range(h):
        for x in range(w):
            if not mask[y, x]:
                continue
            py, px = y + 1, x + 1
            v000, v100 = vid(x, y, 0), vid(x + 1, y, 0)
            v010, v110 = vid(x, y + 1, 0), vid(x + 1, y + 1, 0)
            v001, v101 = vid(x, y, 1), vid(x + 1, y, 1)
            v011, v111 = vid(x, y + 1, 1), vid(x + 1, y + 1, 1)
            quad(v001, v101, v111, v011)  # top
            quad(v000, v010, v110, v100)  # bottom
            if not solid[py, px + 1]:
                quad(v100, v110, v111, v101)
            if not solid[py, px - 1]:
                quad(v000, v001, v011, v010)
            if not solid[py + 1, px]:
                quad(v010, v011, v111, v110)
            if not solid[py - 1, px]:
                quad(v000, v100, v101, v001)

    mesh = trimesh.Trimesh(
        vertices=np.asarray(verts, dtype=np.float64),
        faces=np.asarray(faces, dtype=np.int64),
        process=False,
    )
    mesh.merge_vertices()
    mesh.remove_unreferenced_vertices()
    try:
        mesh.fix_normals()
    except Exception:  # noqa: BLE001
        pass
    if mesh.bounds is not None:
        c = (mesh.bounds[0] + mesh.bounds[1]) * 0.5
        mesh.apply_translation([-c[0], -c[1], -mesh.bounds[0, 2]])
    return mesh


def _build_glyph_mesh(text: str, letter_height_mm: float, thickness: float) -> trimesh.Trimesh:
    pitch = min(TEXT_PITCH_MM, max(0.08, letter_height_mm / 56.0))
    mask, pitch = _rasterize_text(text, letter_height_mm, pitch)
    mesh = _extrude_mask(mask, pitch, thickness)
    block_h = float(mesh.extents[1]) if mesh.extents is not None else 0.0
    if block_h > 1e-6:
        nlines = max(len(text.split("\n")), 1)
        target = letter_height_mm if nlines == 1 else letter_height_mm * nlines + 0.22 * letter_height_mm * (nlines - 1)
        scale = target / block_h
        mesh.vertices[:, 0] *= scale
        mesh.vertices[:, 1] *= scale
    if mesh.bounds is not None:
        c = (mesh.bounds[0] + mesh.bounds[1]) * 0.5
        mesh.apply_translation([-c[0], -c[1], -mesh.bounds[0, 2]])
    return mesh


def _should_wrap(spec: TextSpec, surface: SurfaceAnalysis) -> bool:
    if spec.surface_mode == _MODE_PLANAR:
        return False
    if spec.surface_mode == _MODE_CURVED:
        return surface.cylinder_radius >= 3.0
    return bool(surface.wrap_recommended)


def _snap_to_skin(host: trimesh.Trimesh, query: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Nearest surface point + outward normal, without requiring rtree/embree."""
    try:
        closest, _dist, tri = trimesh.proximity.closest_point(host, query)
        normals = np.asarray(host.face_normals, dtype=np.float64)
        tri = np.clip(np.asarray(tri, dtype=np.int64), 0, max(len(normals) - 1, 0))
        nrm = normals[tri]
        if np.all(np.isfinite(closest)) and np.all(np.isfinite(nrm)):
            to_query = query - closest
            sign = np.sign(np.einsum("ij,ij->i", nrm, to_query))
            sign[sign == 0] = 1.0
            return closest, nrm * sign.reshape(-1, 1)
    except Exception as exc:  # noqa: BLE001
        LOGGER.debug("trimesh proximity unavailable (%s); using vertex KD-tree", exc)

    verts = np.asarray(host.vertices, dtype=np.float64)
    try:
        normals = np.asarray(host.vertex_normals, dtype=np.float64)
    except Exception:  # noqa: BLE001
        normals = None
    if normals is None or len(normals) != len(verts):
        normals = np.zeros_like(verts)
        normals[:, 2] = 1.0
    tree = spatial.cKDTree(verts)
    _d, idx = tree.query(query, k=1)
    idx = np.asarray(idx, dtype=np.int64)
    closest = verts[idx]
    nrm = normals[idx]
    to_query = query - closest
    sign = np.sign(np.einsum("ij,ij->i", nrm, to_query))
    sign[sign == 0] = 1.0
    nrm = nrm * sign.reshape(-1, 1)
    lengths = np.linalg.norm(nrm, axis=1, keepdims=True)
    lengths[lengths < 1e-9] = 1.0
    return closest, nrm / lengths


def _project_vertices(
    host: trimesh.Trimesh,
    local: np.ndarray,
    spec: TextSpec,
    surface: SurfaceAnalysis,
    wrap: bool,
) -> np.ndarray:
    """Map glyph vertices onto the host skin.

    ``local`` is centered in XY with Z in ``[0, thickness]``. Query points sit
    *outside* the mesh; we snap to the nearest skin, then offset along the
    outward normal so flush glyphs stay coplanar and embossed glyphs rise.
    """
    thickness = spec.thickness_mm
    z = local[:, 2]
    if spec.style == _STYLE_FLUSH:
        offset = z - thickness + 0.05
    else:
        offset = z + 0.04

    if wrap:
        radius = max(float(surface.cylinder_radius), 3.0)
        center = np.asarray(surface.cylinder_center, dtype=np.float64)
        theta = local[:, 0] / radius
        # x=0 faces +Y (front of the bed-aligned model).
        theta = (math.pi / 2.0) + theta
        radial = np.column_stack([np.cos(theta), np.sin(theta), np.zeros_like(theta)])
        query = np.column_stack(
            [
                center[0] + radial[:, 0] * (radius + 8.0),
                center[1] + radial[:, 1] * (radius + 8.0),
                center[2] + local[:, 1],
            ]
        )
        fallback = np.column_stack(
            [
                center[0] + radial[:, 0] * (radius + offset),
                center[1] + radial[:, 1] * (radius + offset),
                center[2] + local[:, 1],
            ]
        )
    else:
        u, v, n = surface.plane_u, surface.plane_v, surface.plane_normal
        origin = np.asarray(surface.plane_point, dtype=np.float64)
        query = origin + local[:, 0:1] * u + local[:, 1:2] * v + n * 8.0
        fallback = origin + local[:, 0:1] * u + local[:, 1:2] * v + n * offset.reshape(-1, 1)

    if not wrap:
        return fallback
    closest, nrm = _snap_to_skin(host, query)
    snapped = closest + nrm * offset.reshape(-1, 1)
    if not np.all(np.isfinite(snapped)):
        return fallback
    return snapped


def build_text_volume(
    host: trimesh.Trimesh,
    spec: TextSpec,
    surface: Optional[SurfaceAnalysis] = None,
) -> TextBuildResult:
    if not spec.enabled:
        raise ValueError("Yazı metni boş.")
    surface = surface or analyze_target_surface(host)
    letter_h = spec.size_mm or auto_letter_height_mm(host, surface, spec.content)
    glyph = _build_glyph_mesh(spec.content, letter_h, spec.thickness_mm)
    wrap = _should_wrap(spec, surface)
    world = _project_vertices(
        host,
        np.asarray(glyph.vertices, dtype=np.float64),
        spec,
        surface,
        wrap,
    )
    placed = trimesh.Trimesh(vertices=world, faces=np.asarray(glyph.faces), process=False)
    try:
        placed.remove_unreferenced_vertices()
        placed.fix_normals()
    except Exception:  # noqa: BLE001
        pass

    explanations = {
        "flush": FLUSH_EXPLANATION_TR,
        "embossed": EMBOSS_EXPLANATION_TR.format(height=spec.height_mm),
        "wrap": WRAP_EXPLANATION_TR,
        "planar": PLANAR_EXPLANATION_TR,
        "surface": surface.note,
    }
    return TextBuildResult(
        mesh=placed,
        spec=spec,
        surface=surface,
        wrap_applied=wrap,
        letter_height_mm=float(letter_h),
        host_bounds=np.asarray(host.bounds, dtype=np.float64),
        explanations=explanations,
    )


def _next_free_extruder(assembly: MeshAssembly, requested: int) -> int:
    used = {int(p.extruder) for p in assembly.parts if int(getattr(p, "extruder", 1) or 1) >= 1}
    want = int(np.clip(requested, 1, AMS_SLOT_CAP))
    if want not in used:
        return want
    for slot in range(1, AMS_SLOT_CAP + 1):
        if slot not in used:
            return slot
    return min(want, AMS_SLOT_CAP)


def apply_text_to_assembly(assembly: MeshAssembly, spec: TextSpec) -> TextBuildResult:
    """Append a text volume to the assembly (host bodies stay intact)."""
    if not spec.enabled:
        raise ValueError("Yazı metni boş.")
    host = assembly.combined_mesh()
    result = build_text_volume(host, spec)
    extruder = _next_free_extruder(assembly, spec.extruder)
    result.spec.extruder = extruder
    label = re.sub(r"\s+", " ", spec.content).strip()[:28] or "Text"
    part = MeshPart(
        name=f"Text {label}",
        mesh=result.mesh,
        color_hex=spec.color_hex,
        extruder=extruder,
        object_id="text",
        subtype=spec.subtype,
        lock_extruder=True,
    )
    palette = list(assembly.materials or [])
    while len(palette) < extruder:
        palette.append(spec.color_hex)
    palette[extruder - 1] = spec.color_hex
    assembly.materials = palette[:AMS_SLOT_CAP]
    assembly.parts.append(part)
    return result


def spec_from_mapping(data: Optional[dict[str, Any]]) -> Optional[TextSpec]:
    if not data:
        return None
    content = sanitize_text(str(data.get("content") or data.get("text") or ""))
    if not content or not data.get("enabled", True):
        return None
    size = data.get("size_mm")
    style = data.get("style")
    if hasattr(style, "value"):
        style = style.value
    mode = data.get("surface_mode")
    if hasattr(mode, "value"):
        mode = mode.value
    return TextSpec(
        content=content,
        style=str(style or _STYLE_FLUSH),
        surface_mode=str(mode or _MODE_AUTO),
        height_mm=float(data.get("height_mm") or EMBOSS_HEIGHT_MM),
        inlay_depth_mm=float(data.get("inlay_depth_mm") or FLUSH_DEPTH_MM),
        size_mm=None if size in (None, "", 0, 0.0) else float(size),
        color_hex=str(data.get("color_hex") or DEFAULT_TEXT_COLOR),
        extruder=int(data.get("extruder") or 2),
        filament_id=data.get("filament_id"),
    )


def mesh_to_preview_payload(mesh: trimesh.Trimesh, max_triangles: int = 12000) -> dict[str, Any]:
    faces = np.asarray(mesh.faces, dtype=np.int64)
    verts = np.asarray(mesh.vertices, dtype=np.float64)
    if len(faces) > max_triangles:
        step = int(math.ceil(len(faces) / max_triangles))
        faces = faces[::step]
    return {
        "vertices": np.round(verts, 4).tolist(),
        "faces": faces.tolist(),
        "triangle_count": int(len(faces)),
        "vertex_count": int(len(verts)),
    }
