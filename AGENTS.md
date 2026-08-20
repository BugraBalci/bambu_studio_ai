# AGENTS.md

## Cursor Cloud specific instructions

This repo is a local web app: a FastAPI backend (`backend/`) plus a Vite + React frontend (`frontend/`). It recommends 3D print / filament settings for a Bambu Lab P2S. Standard setup/run commands live in `README.md`; only the non-obvious caveats are captured here.

### Services

| Service | Dir | Dev run command | URL |
|---------|-----|-----------------|-----|
| API (FastAPI) | `backend/` | `./run.sh api` | http://127.0.0.1:8000 |
| UI (Vite) | `frontend/` | `./run.sh ui` | http://127.0.0.1:5173 |

`run.sh api` activates `backend/.venv` and runs `uvicorn app.main:app --reload` (needs `PYTHONPATH=backend`, which `run.sh` sets). `run.sh ui` runs `npm run dev`. Start each in its own long-lived terminal (e.g. tmux) since both are foreground dev servers. The Vite dev server proxies `/api` to the backend on port 8000, so the UI needs the API running for uploads/recommendations to work.

### Non-obvious notes

- The update script already creates the Python venv, installs backend + frontend deps, and copies `.env.example` to `.env`. No extra install steps are needed on a fresh boot.
- `python3 -m venv` requires the `python3-venv` apt package, which is not in the base image; the update script installs it. If you recreate the venv manually and it fails with an `ensurepip` error, run `sudo apt-get install -y python3-venv` first.
- No OpenAI key is required. `backend/app/services/recommend.py` falls back to the deterministic rule engine whenever `OPENAI_API_KEY` is empty or starts with `sk-your` (the `.env.example` default). Recommendations show "kaynak: kural motoru" in that mode.
- The backend does not need to be run from the repo root: `run.sh` `cd`s into `backend/` and sets `PYTHONPATH`. Running `uvicorn app.main:app` from elsewhere without `PYTHONPATH=backend` will fail to import `app`.
- SQLite DB (`data/bambu_ai.db`) and uploaded STL/OBJ files (`uploads/`) are created automatically on backend startup and are gitignored. Delete these dirs to reset state.
- `/api/recommend` enums are strict: `purpose` ∈ {`decorative`,`functional`,`outdoor`}, `strength` ∈ {`weak`,`medium`,`strong`}.
- Frontend lint is `npm run lint` (oxlint) in `frontend/`. There is no backend test suite or backend lint configured.
