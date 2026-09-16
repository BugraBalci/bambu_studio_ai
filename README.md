# Bambu P2S Akıllı Baskı Asistanı

Local web uygulaması: STL yükle → amaç / sağlamlık seç → filament + baskı ayarı önerisi al.

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

## Çalıştırma

Tek komut (Windows): `start_app.bat` veya `start_app.ps1`

Linux / macOS — Terminal 1, API:

```bash
./run.sh api
# eşdeğeri:
cd backend
source .venv/bin/activate
export PYTHONPATH="$PWD/..:$PWD"
python -m uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

`main:app` `backend/main.py` üzerinden `app` nesnesini yükler (`from app.main import app`).
`python -m uvicorn app.main:app` de aynı uygulamayı açar.

Sağlık kontrolü: http://127.0.0.1:8000/api/health → `{"status":"ok",...}`

Terminal 2 — UI:

```bash
./run.sh ui
# eşdeğeri:
cd frontend
npm run dev
```

Tarayıcı: http://127.0.0.1:5173  
Vite `/api` isteklerini `http://127.0.0.1:8000` adresine proxy'ler.

## API

| Endpoint | Açıklama |
|----------|----------|
| `GET /` ve `GET /api/health` | Servis sağlık kontrolü |
| `POST /api/analyze` | STL yükle, geometri metrikleri |
| `POST /api/recommend` | Amaç + sağlamlık → baskı önerisi |
| `POST /api/recommend/export-profile` | Faz B için profil JSON indir |
| `GET/POST/PATCH/DELETE /api/filaments` | Filament envanteri |

## Fazlar

- **A (şimdi):** öneri + envanter
- **B:** `slicer_hints` → Bambu/Orca CLI ile `.gcode.3mf`
- **C:** AMS MQTT + yazıcıya gönderim
