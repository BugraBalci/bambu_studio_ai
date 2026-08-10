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

Terminal 1 — API:

```bash
cd backend
source .venv/bin/activate
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Terminal 2 — UI:

```bash
cd frontend
npm run dev
```

Tarayıcı: http://127.0.0.1:5173

## API

| Endpoint | Açıklama |
|----------|----------|
| `POST /api/analyze` | STL yükle, geometri metrikleri |
| `POST /api/recommend` | Amaç + sağlamlık → baskı önerisi |
| `POST /api/recommend/export-profile` | Faz B için profil JSON indir |
| `GET/POST/PATCH/DELETE /api/filaments` | Filament envanteri |

## Fazlar

- **A (şimdi):** öneri + envanter
- **B:** `slicer_hints` → Bambu/Orca CLI ile `.gcode.3mf`
- **C:** AMS MQTT + yazıcıya gönderim
