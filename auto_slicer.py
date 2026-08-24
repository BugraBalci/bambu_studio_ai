#!/usr/bin/env python3
"""
auto_slicer.py — Geometry-driven Bambu Lab P2S Combo project generator.

Ingests Meshy (or other) meshes — including native-color `.3mf` with sub-mesh
hierarchy — runs the mathematical rule engine, and writes a ready-to-slice
Bambu Studio project `.3mf` (or a JSON profile overlay).

Usage:
    python auto_slicer.py input_from_meshy.3mf --output output_ready_to_print.3mf
    python auto_slicer.py input_model.glb
    python auto_slicer.py input_model.obj -o my_profile.json -v
    python auto_slicer.py --watch                    # daemon on ./uploads/
    python auto_slicer.py --watch --queue-dir ./inbox -v
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path
from typing import Any, Optional

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import numpy as np

from slicer_pipeline.bambu_config import BambuConfigEngine
from slicer_pipeline.constants import DEFAULT_QUEUE_DIR, P2S_BED_MM, SUPPORTED_MESH_SUFFIXES
from slicer_pipeline.geometry import GeometryAnalyzer
from slicer_pipeline.mesh_parser import MeshParser
from slicer_pipeline.project_packager import ProjectPackager
from slicer_pipeline.rules import RuleEngine

# Re-exports so `from auto_slicer import ...` keeps working.
from slicer_pipeline import (  # noqa: F401
    BambuConfigEngine as _BambuConfigEngine,
    GeometryAnalyzer as _GeometryAnalyzer,
    GeometryMetrics,
    MeshAssembly,
    MeshParser as _MeshParser,
    MeshPart,
    ProjectPackager as _ProjectPackager,
    RuleEngine as _RuleEngine,
    RuleResult,
    load_triangle_mesh,
)

LOGGER = logging.getLogger("auto_slicer")

# Backward-compatible aliases used by older call sites / tests.
BambuProfileGenerator = BambuConfigEngine
P1S_BED_MM = P2S_BED_MM


def _default_output(model: Path) -> Path:
    if model.suffix.lower() == ".3mf":
        return model.with_name(f"{model.stem}_ready_to_print.3mf")
    return Path("optimized_p2s_profile.json")


def process_model(
    model_path: Path,
    output_path: Path,
    baseline_path: Optional[Path] = None,
) -> Path:
    """Parse → analyze combined assembly → inject P2S settings → write JSON or 3MF."""
    model_path = Path(model_path)
    output_path = Path(output_path)

    parser = MeshParser()
    assembly = parser.parse(model_path)

    analyzer = GeometryAnalyzer(assembly)
    analyzer.load_and_validate()
    metrics = analyzer.analyze()

    if not metrics.fits_p2s_bed:
        LOGGER.warning(
            "Model may not fit P2S bed %s mm (extents %s)",
            P2S_BED_MM,
            tuple(np.round(metrics.extents_mm, 2)),
        )

    engine = RuleEngine()
    results = engine.evaluate(metrics)

    baseline = None
    if baseline_path:
        baseline = json.loads(Path(baseline_path).read_text(encoding="utf-8"))
        LOGGER.info("Loaded baseline profile: %s", baseline_path)

    config = BambuConfigEngine(baseline=baseline)
    config.apply_rules(results)
    config.attach_metadata(metrics, results)

    if output_path.suffix.lower() == ".3mf":
        settings = config.merge_into_template()
        settings = config.expand_filaments(settings, assembly.materials)
        return ProjectPackager().pack(
            assembly,
            settings,
            output_path,
            extra_meta={"triggered_rules": [r.name for r in results if r.triggered]},
            part_name=model_path.stem,
        )

    return config.save(output_path)


def generate_profile(
    model_path: Path,
    output_path: Path,
    baseline_path: Optional[Path] = None,
) -> Path:
    """Backward-compatible entry: JSON overlay, or a Studio project if output is `.3mf`."""
    return process_model(model_path, output_path, baseline_path)


class AutoPrintQueueWatcher:
    """
    Monitor a directory for new mesh drops and run the full analysis
    pipeline automatically (no manual CLI invocation per file).
    """

    def __init__(
        self,
        queue_dir: Path,
        output_dir: Optional[Path] = None,
        baseline_path: Optional[Path] = None,
        settle_seconds: float = 1.5,
    ) -> None:
        self.queue_dir = Path(queue_dir)
        self.output_dir = Path(output_dir) if output_dir else self.queue_dir
        self.baseline_path = baseline_path
        self.settle_seconds = settle_seconds
        self._observer: Any = None
        self._processing: set[str] = set()

    def ensure_queue_dir(self) -> Path:
        self.queue_dir.mkdir(parents=True, exist_ok=True)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        return self.queue_dir

    def process_file(self, model_path: Path) -> Optional[Path]:
        model_path = Path(model_path)
        key = str(model_path.resolve())
        if key in self._processing:
            LOGGER.debug("Already processing: %s", model_path.name)
            return None

        suffix = model_path.suffix.lower()
        if suffix not in SUPPORTED_MESH_SUFFIXES:
            LOGGER.debug("Ignoring non-mesh file: %s", model_path.name)
            return None
        if not model_path.is_file():
            return None

        self._processing.add(key)
        try:
            time.sleep(self.settle_seconds)
            if not model_path.is_file():
                return None

            if suffix == ".3mf":
                out_name = f"{model_path.stem}_ready_to_print.3mf"
            else:
                out_name = f"{model_path.stem}_optimized_p2s_profile.json"
            output_path = self.output_dir / out_name
            LOGGER.info("Queue: processing %s → %s", model_path.name, output_path.name)
            return process_model(model_path, output_path, self.baseline_path)
        except Exception as exc:  # noqa: BLE001
            LOGGER.exception("Queue failed for %s: %s", model_path.name, exc)
            return None
        finally:
            self._processing.discard(key)

    def scan_existing(self) -> list[Path]:
        written: list[Path] = []
        for pattern in (
            "*.stl",
            "*.STL",
            "*.obj",
            "*.OBJ",
            "*.glb",
            "*.GLB",
            "*.gltf",
            "*.GLTF",
            "*.3mf",
            "*.3MF",
        ):
            for path in sorted(self.queue_dir.glob(pattern)):
                result = self.process_file(path)
                if result is not None:
                    written.append(result)
        return written

    def start(self, block: bool = True) -> None:
        try:
            from watchdog.events import FileSystemEventHandler
            from watchdog.observers import Observer
        except ImportError as exc:
            raise ImportError(
                "watchdog is required for --watch mode. "
                "Install with: pip install watchdog"
            ) from exc

        self.ensure_queue_dir()
        watcher = self

        class _QueueHandler(FileSystemEventHandler):
            def on_created(self, event: Any) -> None:
                if getattr(event, "is_directory", False):
                    return
                watcher.process_file(Path(event.src_path))

            def on_moved(self, event: Any) -> None:
                if getattr(event, "is_directory", False):
                    return
                dest = getattr(event, "dest_path", None)
                if dest:
                    watcher.process_file(Path(dest))

        handler = _QueueHandler()
        self._observer = Observer()
        self._observer.schedule(handler, str(self.queue_dir.resolve()), recursive=False)
        self._observer.start()
        LOGGER.info(
            "Watching %s for new .3mf / .glb / .gltf / .obj / .stl files",
            self.queue_dir.resolve(),
        )

        existing = self.scan_existing()
        if existing:
            LOGGER.info("Processed %d existing queue file(s)", len(existing))

        if block:
            try:
                while True:
                    time.sleep(1.0)
            except KeyboardInterrupt:
                LOGGER.info("Watchdog stopped by user")
                self.stop()

    def stop(self) -> None:
        if self._observer is not None:
            self._observer.stop()
            self._observer.join(timeout=5.0)
            self._observer = None


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=(
            "Analyze a 3MF/GLB/GLTF/OBJ/STL mesh and generate an optimized Bambu Lab "
            "P2S Combo Studio project (.3mf) or JSON profile via geometric rule engine. "
            "Meshy .3mf color/sub-mesh hierarchy is preserved."
        )
    )
    p.add_argument(
        "model",
        type=Path,
        nargs="?",
        default=None,
        help="Input .3mf / .glb / .gltf / .obj / .stl (omit when using --watch)",
    )
    p.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help=(
            "Output path. Use .3mf for a Bambu Studio project, .json for a profile overlay. "
            "Default: {stem}_ready_to_print.3mf for .3mf inputs, else optimized_p2s_profile.json"
        ),
    )
    p.add_argument(
        "-b",
        "--baseline",
        type=Path,
        default=None,
        help="Optional baseline Bambu Studio JSON to patch instead of built-in defaults",
    )
    p.add_argument(
        "--watch",
        action="store_true",
        help="Run background daemon watching for new meshes in --queue-dir",
    )
    p.add_argument(
        "--queue-dir",
        type=Path,
        default=DEFAULT_QUEUE_DIR,
        help=f"Directory to watch for auto-processing (default: {DEFAULT_QUEUE_DIR})",
    )
    p.add_argument(
        "--queue-output",
        type=Path,
        default=None,
        help="Output directory in --watch mode (default: same as --queue-dir)",
    )
    p.add_argument("-v", "--verbose", action="store_true", help="DEBUG logging")
    return p


def main(argv: Optional[list[str]] = None) -> int:
    args = build_arg_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s | %(levelname)-7s | %(message)s",
        datefmt="%H:%M:%S",
    )

    if args.watch:
        watcher = AutoPrintQueueWatcher(
            queue_dir=args.queue_dir,
            output_dir=args.queue_output,
            baseline_path=args.baseline,
        )
        try:
            watcher.start(block=True)
        except ImportError as exc:
            LOGGER.error("%s", exc)
            return 2
        except Exception as exc:  # noqa: BLE001
            LOGGER.exception("Watchdog failed: %s", exc)
            return 1
        return 0

    if args.model is None:
        LOGGER.error("Provide a model path or use --watch for daemon mode")
        return 2

    suffix = args.model.suffix.lower()
    if suffix not in SUPPORTED_MESH_SUFFIXES:
        LOGGER.error("Only .3mf / .glb / .gltf / .obj / .stl supported (got %s)", suffix)
        return 2

    output = args.output if args.output is not None else _default_output(args.model)
    try:
        out = process_model(args.model, output, args.baseline)
    except Exception as exc:  # noqa: BLE001
        LOGGER.exception("Failed: %s", exc)
        return 1

    print(f"OK → {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
