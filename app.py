#!/usr/bin/env python3
"""
FastAPI backend for MyPictures photo search.

Dev:
    uvicorn app:app --host 0.0.0.0 --port 8000 --reload

Production (after npm run build in frontend/):
    uvicorn app:app --host 0.0.0.0 --port 8000
"""

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import psycopg
import torch
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from config import SCAN_PATHS
from search import encode_text, get_conn_str, load_clip, search

DIST_DIR = Path(__file__).parent / "frontend" / "dist"
ALLOWED_ROOTS = [Path(p).expanduser().resolve() for p in SCAN_PATHS]


# ---------------------------------------------------------------------------
# Lifespan: load CLIP once
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"Loading CLIP model on {device}...", flush=True)
    loop = asyncio.get_event_loop()
    model, tokenizer = await loop.run_in_executor(None, load_clip, device)
    print("CLIP model loaded.", flush=True)
    app.state.model = model
    app.state.tokenizer = tokenizer
    app.state.device = device
    yield


app = FastAPI(title="MyPictures", lifespan=lifespan)


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

MIN_SIMILARITY = 0.2


class SearchRequest(BaseModel):
    query: str
    limit: int = 20
    after: Optional[str] = None   # "YYYY-MM-DD"
    before: Optional[str] = None  # "YYYY-MM-DD"
    min_similarity: float = MIN_SIMILARITY


def _parse_date(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# API endpoints
# ---------------------------------------------------------------------------

@app.post("/api/search")
async def api_search(req: SearchRequest):
    after = _parse_date(req.after) if req.after else None
    before = _parse_date(req.before) if req.before else None

    loop = asyncio.get_event_loop()

    # Encode text in thread pool (GPU/CPU bound)
    embedding = await loop.run_in_executor(
        None,
        encode_text,
        app.state.model,
        app.state.tokenizer,
        req.query,
        app.state.device,
    )

    # DB query in thread pool (blocking I/O)
    def _db_search():
        conn = psycopg.connect(get_conn_str())
        try:
            rows = search(conn, embedding, req.limit, after=after, before=before)
        finally:
            conn.close()
        # Filter out low-similarity results and serialise datetime objects
        filtered = []
        for row in rows:
            if row.get("similarity") is not None and row["similarity"] < req.min_similarity:
                continue
            if isinstance(row.get("date_taken"), datetime):
                row["date_taken"] = row["date_taken"].isoformat()
            filtered.append(row)
        return filtered

    try:
        results = await loop.run_in_executor(None, _db_search)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return results


@app.get("/api/image")
async def api_image(path: str = Query(..., description="Absolute path to image file")):
    resolved = Path(path).resolve()

    # Security: must be under one of the configured scan roots
    allowed = any(
        str(resolved).startswith(str(root))
        for root in ALLOWED_ROOTS
    )
    if not allowed:
        raise HTTPException(status_code=403, detail="Access denied")

    if not resolved.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    return FileResponse(str(resolved))


# ---------------------------------------------------------------------------
# Serve React SPA (production build)
# ---------------------------------------------------------------------------

if DIST_DIR.exists():
    app.mount("/assets", StaticFiles(directory=str(DIST_DIR / "assets")), name="assets")

    @app.get("/{full_path:path}")
    async def spa_fallback(full_path: str):
        index = DIST_DIR / "index.html"
        return FileResponse(str(index))
