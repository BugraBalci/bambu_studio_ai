# Bambu P2S Akıllı Baskı Asistanı

Local pipeline: drop a Meshy `.3mf` / `.glb` / `.obj` (or `.stl`) → geometry analysis (`trimesh` + `scipy`) → ready-to-slice Bambu Studio project `.3mf`.

Meshy `.3mf` exports already include native color and multi-body separation (no slicer settings). This tool keeps that hierarchy, runs the rule engine on the combined assembly, and injects P2S Combo profiles. No Blender / `bpy` step.

## Gereksinimler

- Python 3.10+
- Node.js 20+
- (Opsiyonel) OpenAI API anahtarı — yoksa kural tabanlı öneri çalışır

## Kurulum

```bash
cp .env.example .env
# .env içine OPENAI_API_KEY ekleyebilirsin

cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cd ../frontend
npm install
```

## Pipeline

1. Drop a native Meshy `.3mf` (or `.glb` / `.obj` / `.stl` / `.gltf`) into `uploads/`, or upload it in the UI.
2. `MeshParser` loads every sub-mesh via `trimesh.load()` **without flattening**, and recovers 3MF colors / object hierarchy from the archive XML.
3. `GeometryAnalyzer` + `RuleEngine` run on the combined assembly (overhang, thin/tall, Arachne density, CoM).
4. `BambuConfigEngine` + `ProjectPackager` write a Bambu Studio project `{stem}_ready_to_print.3mf` with P2S settings embedded.

```bash
# from repo root, with backend/.venv activated
python auto_slicer.py input_from_meshy.3mf --output output_ready_to_print.3mf
python auto_slicer.py --watch            # default: ./uploads
python auto_slicer.py model.glb -o out.json -v
```

## Çalıştırma

```bash
./run.sh both
```

Or separately:

```bash
./run.sh api    # http://127.0.0.1:8000
./run.sh ui     # http://127.0.0.1:5173
```

## API

| Endpoint | Açıklama |
|----------|----------|
| `POST /api/analyze` | `.3mf` / `.glb` / `.gltf` / `.obj` / `.stl` yükle, geometri metrikleri |
| `POST /api/recommend` | Amaç + sağlamlık → baskı önerisi |
| `POST /api/recommend/export-profile` | Faz B için profil JSON indir |
| `POST /api/recommend/export-3mf` | Bambu Studio proje `.3mf` (renk/gövde korunur) |
| `GET/POST/PATCH/DELETE /api/filaments` | Filament envanteri |

## Fazlar

- **A (şimdi):** geometri analizi + öneri + envanter + Meshy `.3mf` → Studio project
- **B:** `slicer_hints` → Bambu/Orca CLI ile `.gcode.3mf`
- **C:** AMS MQTT + yazıcıya gönderim

