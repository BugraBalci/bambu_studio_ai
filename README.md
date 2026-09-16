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

### What makes the exported `.3mf` a project archive

Bambu Studio does not read `Metadata/project_settings.config` as a profile. On import it
splits that JSON into a process preset, N filament presets and a printer preset, then
re-binds each one to an *installed* system preset. Two vectors drive that, both sized
`N + 2` and ordered `[process, filament_1..filament_N, printer]`:

| Key | Role |
|-----|------|
| `inherits_group` | the system preset each split preset inherits from |
| `different_settings_to_system` | the keys Studio keeps as project overrides; anything omitted is reset to the base preset's value |

The printer entry of `different_settings_to_system` is intentionally empty so Studio
resets every machine key to the stock P2S values rather than keeping the bed shape and
G-code inherited from the A1 template the exporter starts from.

`ProjectPackager` writes the entries in a fixed order — `[Content_Types].xml`,
`_rels/.rels`, `3D/3dmodel.model`, `Metadata/project_settings.config`,
`Metadata/model_settings.config`, `Metadata/slice_info.config` — because the plate that
`slice_info.config` references is only known once `model_settings.config` has declared
it. `verify_project_archive()` enforces this on every export.

**Preset names must exist.** An `inherits` naming a preset Studio cannot resolve behaves
exactly like having no base at all, which is what makes a project open under the
last-used profile. There is no `0.28mm Standard @BBL P2S`: on a 0.4 nozzle the coarsest
stock P2S process preset is `0.24mm Standard @BBL P2S`. A calculated 0.28 mm project
therefore inherits from that preset and carries `layer_height` as a listed diff, so
Studio shows `0.24mm Standard @BBL P2S` marked as modified with 0.28 mm in the parameter
panel. `slicer_pipeline/studio_profile.py` holds the per-nozzle tables of presets that
actually ship in `resources/profiles/BBL`.

## Çalıştırma

```bash
./run.sh both
```

Or separately:

```bash
./run.sh api    # http://127.0.0.1:8000
./run.sh ui     # http://127.0.0.1:5173
```

## Windows One-Click Launch

Use these helpers on Windows 10/11 so you do not have to open PowerShell and type commands.

**First-time setup** (same as [Kurulum](#kurulum), in `cmd` or PowerShell):

```bat
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

cd ..\frontend
npm install
```

**Optional desktop shortcut** (run once from the repo root):

```bat
powershell -ExecutionPolicy Bypass -File .\setup_desktop_shortcut.ps1
```

That creates **Bambu AI Studio** on your Desktop, pointing at `start_app.bat` with the working directory set to this repo.

**Start both servers** — double-click `start_app.bat` (or the Desktop shortcut). It checks for `backend\.venv` and `frontend\node_modules`, opens titled consoles for the API (`http://127.0.0.1:8000`) and UI (`http://127.0.0.1:5173`), then launches the default browser.

**Stop** — close those two consoles, or double-click `stop_app.bat` to free ports 8000 and 5173.

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

