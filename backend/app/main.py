from __future__ import annotations

import shutil
import uuid
from pathlib import Path

from fastapi import Depends, FastAPI, File, HTTPException, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.config import ROOT_DIR, get_settings
from app.database import get_db, init_db
from app.models import Filament
from app.schemas import (
    FilamentCreate,
    FilamentOut,
    FilamentUpdate,
    GeometryMetrics,
    RecommendRequest,
    RecommendResponse,
)
from app.services.geometry import analyze_stl
from app.services.phase_b import recommendation_to_cli_overlay
from app.services.recommend import recommend

settings = get_settings()
UPLOAD_ROOT = Path(settings.upload_dir)
META_SUFFIX = ".meta.json"

app = FastAPI(title="Bambu P2S Smart Print Assistant", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _sqlite_path() -> Path | None:
    url = settings.database_url
    if not url.startswith("sqlite:///"):
        return None
    raw = url.removeprefix("sqlite:///")
    path = Path(raw)
    if not path.is_absolute():
        path = ROOT_DIR / path
    return path


@app.on_event("startup")
def on_startup() -> None:
    UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)
    db_path = _sqlite_path()
    if db_path is not None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
    init_db()


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "printer": "Bambu Lab P2S"}


def _meta_path(file_id: str) -> Path:
    return UPLOAD_ROOT / f"{file_id}{META_SUFFIX}"


def _load_geometry(file_id: str) -> GeometryMetrics:
    meta = _meta_path(file_id)
    if not meta.exists():
        raise HTTPException(status_code=404, detail="Analiz bulunamadı. Önce STL yükleyin.")
    return GeometryMetrics.model_validate_json(meta.read_text(encoding="utf-8"))


@app.post("/api/analyze", response_model=GeometryMetrics)
async def analyze(file: UploadFile = File(...)) -> GeometryMetrics:
    name = file.filename or "model.stl"
    if not name.lower().endswith((".stl", ".obj")):
        raise HTTPException(status_code=400, detail="Yalnızca .stl veya .obj desteklenir.")

    file_id = uuid.uuid4().hex
    dest = UPLOAD_ROOT / f"{file_id}_{Path(name).name}"
    with dest.open("wb") as out:
        shutil.copyfileobj(file.file, out)

    try:
        metrics = analyze_stl(dest, original_filename=name, file_id=file_id)
    except Exception as exc:  # noqa: BLE001
        dest.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=f"STL analiz edilemedi: {exc}") from exc

    _meta_path(file_id).write_text(metrics.model_dump_json(indent=2), encoding="utf-8")
    # Keep path reference for Phase B
    (UPLOAD_ROOT / f"{file_id}.path").write_text(str(dest), encoding="utf-8")
    return metrics


@app.get("/api/analyze/{file_id}", response_model=GeometryMetrics)
def get_analysis(file_id: str) -> GeometryMetrics:
    return _load_geometry(file_id)


@app.get("/api/filaments", response_model=list[FilamentOut])
def list_filaments(db: Session = Depends(get_db)) -> list[Filament]:
    return db.query(Filament).order_by(Filament.id).all()


@app.post("/api/filaments", response_model=FilamentOut, status_code=201)
def create_filament(payload: FilamentCreate, db: Session = Depends(get_db)) -> Filament:
    row = Filament(**payload.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@app.patch("/api/filaments/{filament_id}", response_model=FilamentOut)
def update_filament(
    filament_id: int, payload: FilamentUpdate, db: Session = Depends(get_db)
) -> Filament:
    row = db.get(Filament, filament_id)
    if not row:
        raise HTTPException(status_code=404, detail="Filament bulunamadı")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(row, key, value)
    db.commit()
    db.refresh(row)
    return row


@app.delete("/api/filaments/{filament_id}", status_code=204)
def delete_filament(filament_id: int, db: Session = Depends(get_db)) -> Response:
    row = db.get(Filament, filament_id)
    if not row:
        raise HTTPException(status_code=404, detail="Filament bulunamadı")
    db.delete(row)
    db.commit()
    return Response(status_code=204)

@app.post("/api/recommend", response_model=RecommendResponse)
def recommend_settings(payload: RecommendRequest, db: Session = Depends(get_db)) -> RecommendResponse:
    geometry = _load_geometry(payload.file_id)
    recommendation, used_llm, baseline = recommend(
        db=db,
        geometry=geometry,
        purpose=payload.purpose,
        strength=payload.strength,
        color_preference=payload.color_preference,
        notes=payload.notes,
    )
    return RecommendResponse(
        geometry=geometry,
        recommendation=recommendation,
        used_llm=used_llm,
        rule_baseline=baseline,
    )


@app.get("/api/recommend/{file_id}/export")
def export_recommendation_schema() -> JSONResponse:
    """Document Phase B bridge schema (static example)."""
    example = {
        "schema_version": "1.0",
        "slicer_hints": {
            "filament_type": "PETG",
            "nozzle_diameter": 0.4,
            "layer_height": 0.2,
            "wall_loops": 3,
            "sparse_infill_density": 20,
            "sparse_infill_pattern": "grid",
            "nozzle_temperature": 245,
            "bed_temperature": 80,
            "enable_support": False,
            "brim_width": 0,
            "printer_model": "Bambu Lab P2S",
        },
        "note": "POST /api/recommend returns PrintRecommendation with slicer_hints for CLI mapping.",
    }
    return JSONResponse(example)


@app.post("/api/recommend/export-profile")
def export_profile(payload: RecommendRequest, db: Session = Depends(get_db)) -> JSONResponse:
    """Download-ready profile JSON for Phase B (machine/process/filament overlay)."""
    geometry = _load_geometry(payload.file_id)
    recommendation, used_llm, _ = recommend(
        db=db,
        geometry=geometry,
        purpose=payload.purpose,
        strength=payload.strength,
        color_preference=payload.color_preference,
        notes=payload.notes,
    )
    profile = {
        "schema_version": recommendation.schema_version,
        "printer_model": "Bambu Lab P2S",
        "recommendation": recommendation.model_dump(),
        "used_llm": used_llm,
        "cli_ready": recommendation_to_cli_overlay(recommendation),
    }
    return JSONResponse(
        content=profile,
        headers={"Content-Disposition": 'attachment; filename="p2s_profile.json"'},
    )
