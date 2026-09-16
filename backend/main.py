"""ASGI entry point for uvicorn (`main:app`).

The FastAPI application lives in `app.main`. This module re-exports `app` so
both of these invocations work from the `backend/` directory:

    python -m uvicorn main:app --reload --host 127.0.0.1 --port 8000
    python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
"""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent
ROOT_DIR = BACKEND_DIR.parent

for path in (str(BACKEND_DIR), str(ROOT_DIR)):
    if path not in sys.path:
        sys.path.insert(0, path)

from app.main import app  # noqa: E402

__all__ = ["app"]


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host="127.0.0.1",
        port=8000,
        reload=True,
        app_dir=str(BACKEND_DIR),
    )
