"""Geometry → Bambu Studio process key updates."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from slicer_pipeline.constants import (
    COG_XY_SKEW,
    COG_Z_TOP_HEAVY,
    HIGH_NORMAL_VARIANCE,
    HIGH_VERTEX_DENSITY,
    HOLE_COMPENSATION_MM,
    LARGE_FLAT_BOTTOM_MM2,
    LARGE_VOLUME_CM3,
    NARROW_TOP_AREA_MM2,
    OVERHANG_AREA_RATIO,
    TALL_ASPECT_RATIO,
)
from slicer_pipeline.geometry import GeometryMetrics

LOGGER = logging.getLogger("auto_slicer")


@dataclass
class RuleResult:
    name: str
    triggered: bool
    reason: str
    updates: dict[str, Any] = field(default_factory=dict)


class RuleEngine:
    """Evaluate geometry metrics and produce Bambu Studio JSON key updates."""

    def evaluate(self, metrics: GeometryMetrics) -> list[RuleResult]:
        results = [
            self.rule_overhang(metrics),
            self.rule_thin_tall(metrics),
            self.rule_large_flat(metrics),
            self.rule_dense_detail(metrics),
            self.rule_stability(metrics),
            self.rule_hole_tolerance(metrics),
        ]
        for r in results:
            level = logging.INFO if r.triggered else logging.DEBUG
            LOGGER.log(level, "%s", r.reason)
        return results

    def rule_overhang(self, m: GeometryMetrics) -> RuleResult:
        triggered = bool(getattr(m, "support_required", False) or m.overhang_area_ratio > OVERHANG_AREA_RATIO)
        stype = getattr(m, "recommended_support_type", None) or "tree(auto)"
        if stype in ("none", "", None):
            stype = "tree(auto)"
        reason = (
            f"Overhang area calculated as {m.overhang_area_ratio * 100:.1f}% "
            f"(threshold {OVERHANG_AREA_RATIO * 100:.0f}%)"
        )
        extra = getattr(m, "support_reason", "") or ""
        if extra:
            reason += f" | {extra}"
        if triggered:
            reason += f" -> Triggering Overhang Rule ({stype})"
            updates = {
                "cooling_fan_speed_max": "100",
                "fan_max_speed": ["100"],
                "outer_wall_speed": ["40"],
                "outer_wall_line_width": "0.45",
                "support_top_z_distance": "0.2",
                "support_type": stype,
                "enable_support": "1",
            }
        else:
            reason += " -> Overhang Rule skipped"
            updates = {}
        return RuleResult("overhang_bridge", triggered, reason, updates)

    def rule_thin_tall(self, m: GeometryMetrics) -> RuleResult:
        narrow = m.top_cross_section_mm2 < NARROW_TOP_AREA_MM2
        triggered = m.aspect_ratio_z > TALL_ASPECT_RATIO and narrow
        reason = (
            f"Tall aspect ratio={m.aspect_ratio_z:.2f} "
            f"(need >{TALL_ASPECT_RATIO}), top cross-section="
            f"{m.top_cross_section_mm2:.2f} mm² (narrow <{NARROW_TOP_AREA_MM2})"
        )
        if triggered:
            reason += " -> Triggering Thin/Tall (Sword/Tower) Rule"
            updates = {
                "layer_height": "0.08",
                "fan_cooling_layer_time": ["8"],
                "default_acceleration": "2500",
                "outer_wall_acceleration": ["1000"],
            }
        else:
            reason += " -> Thin/Tall Rule skipped"
            updates = {}
        return RuleResult("thin_tall", triggered, reason, updates)

    def rule_large_flat(self, m: GeometryMetrics) -> RuleResult:
        triggered = (
            m.volume_cm3 > LARGE_VOLUME_CM3
            and m.flat_bottom_area_mm2 > LARGE_FLAT_BOTTOM_MM2
        )
        reason = (
            f"Volume={m.volume_cm3:.1f} cm³ (need >{LARGE_VOLUME_CM3}), "
            f"flat bottom={m.flat_bottom_area_mm2:.0f} mm² "
            f"(need >{LARGE_FLAT_BOTTOM_MM2})"
        )
        if triggered:
            reason += " -> Triggering Large/Flat Structural Rule"
            updates = {
                "layer_height": "0.28",
                "wall_loops": "5",
                "sparse_infill_pattern": "gyroid",
                "sparse_infill_density": "20%",
                "initial_layer_speed": "50",
                "outer_wall_speed": ["300"],
            }
        else:
            reason += " -> Large/Flat Rule skipped"
            updates = {}
        return RuleResult("large_flat", triggered, reason, updates)

    def rule_dense_detail(self, m: GeometryMetrics) -> RuleResult:
        density_hit = m.vertex_density > HIGH_VERTEX_DENSITY
        variance_hit = m.normal_variance > HIGH_NORMAL_VARIANCE
        triggered = density_hit
        reason = (
            f"Vertex density={m.vertex_density:.3f}/mm² "
            f"(high >{HIGH_VERTEX_DENSITY}), "
            f"normal variance={m.normal_variance:.3f} "
            f"(info; high >{HIGH_NORMAL_VARIANCE})"
        )
        if variance_hit and density_hit:
            reason += " [variance also elevated]"
        if triggered:
            reason += " -> Triggering Dense Surface Detail Rule"
            updates = {
                "wall_generator": "arachne",
                "elefant_foot_compensation": "0.15",
                "elephant_foot_compensation": "0.15",
                "bottom_surface_pattern": "monotonic",
            }
        else:
            reason += " -> Dense Detail Rule skipped"
            updates = {}
        return RuleResult("dense_detail", triggered, reason, updates)

    def rule_stability(self, m: GeometryMetrics) -> RuleResult:
        triggered = m.tip_over_risk
        reason = (
            f"CoG z-ratio={m.cog_z_ratio:.3f} "
            f"(top-heavy >{COG_Z_TOP_HEAVY}), "
            f"XY offset={m.cog_xy_offset_ratio:.3f} "
            f"(skew >{COG_XY_SKEW}), aspect Z={m.aspect_ratio_z:.2f}"
        )
        if triggered:
            reason += " -> Triggering Center-of-Mass Stability Rule"
            updates = {
                "bottom_shell_layers": "8",
                "bottom_shell_thickness": "2.5",
            }
        else:
            reason += " -> Stability Rule skipped"
            updates = {}
        return RuleResult("center_of_mass_stability", triggered, reason, updates)

    def rule_hole_tolerance(self, m: GeometryMetrics) -> RuleResult:
        triggered = m.has_mechanical_holes
        diameters = ", ".join(f"{d:.1f}" for d in m.hole_diameters_mm[:6])
        if m.mechanical_hole_count > 6:
            diameters += ", ..."
        reason = (
            f"Mechanical holes detected: {m.mechanical_hole_count} "
            f"(loop hits={m.hole_count}"
            + (f", diameters mm: {diameters}" if diameters else "")
            + ")"
        )
        if triggered:
            reason += " -> Triggering Hole & Tolerance Compensation Rule"
            updates = {"xy_hole_compensation": HOLE_COMPENSATION_MM}
        else:
            reason += " -> Hole Tolerance Rule skipped"
            updates = {}
        return RuleResult("hole_tolerance", triggered, reason, updates)
