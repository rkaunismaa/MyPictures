# MyPictures — Claude Code Instructions

## Environment
- Python venv: `../.mypictures/` (Python 3.11) — always use this venv
- Install packages with: `uv pip install <package> --python ../.mypictures/bin/python`
- Run scripts from the repo root with the venv activated: `source ../.mypictures/bin/activate`
- Node >= 18 required for frontend (system default is v12 — use `nvm use 20`)

## Project Structure
```
MyPictures/
├── config.py        # Scan paths, DB settings, CLIP model config; loads .env
├── setup_db.py      # Creates DB, enables pgvector, creates photos table + indexes
├── indexer.py       # Scans images, extracts EXIF, computes CLIP embeddings, upserts to DB
├── search.py        # CLI semantic search
├── app.py           # FastAPI backend
├── frontend/        # React 18 + Vite 5 frontend
│   ├── src/App.jsx  # All UI and CSS
│   └── ...
├── pyproject.toml
└── .env             # DB credentials (gitignored)
```

## Stack
- **Embeddings:** OpenCLIP ViT-L/14 (`laion2b_s32b_b82k`) — 768-dim vectors
- **DB:** PostgreSQL 14 + pgvector (built from source), psycopg3
- **Backend:** FastAPI + uvicorn
- **Frontend:** React 18 + Vite 5, no TypeScript, no UI framework

## Database
- Host: localhost:5432, DB: `mypictures`, User: postgres
- Credentials in `.env` (loaded by `config.py` at import time)
- Table: `photos` with `embedding vector(768)`, HNSW cosine index
- `migrate_embedding_dim.py` — migration script for switching CLIP models (deletes rows, resizes column, recreates index)

## Common Commands

### Initial setup
```bash
python setup_db.py
python indexer.py
```

### CLI search
```bash
python search.py "a dog playing outside"
python search.py "sunset" --limit 10 --after 2022-01-01
```

### Run web app (dev)
```bash
# Terminal 1 — backend
python -m uvicorn app:app --host 0.0.0.0 --port 8000

# Terminal 2 — frontend (Node 20 required)
cd frontend && npm install && npm run dev
# Open http://localhost:5173
```

### Run web app (production)
```bash
cd frontend && npm run build
python -m uvicorn app:app --host 0.0.0.0 --port 8000
# Open http://localhost:8000
```

## Key Config (config.py)
- `SCAN_PATHS` — directories to index (edit to add/remove photo locations)
- `CLIP_MODEL` / `CLIP_PRETRAINED` / `EMBEDDING_DIM` — change to swap CLIP variant
- All DB settings overridable via environment variables or `.env`

## Switching CLIP models
1. Update `CLIP_MODEL`, `CLIP_PRETRAINED`, and `EMBEDDING_DIM` in `config.py`
2. Run `python migrate_embedding_dim.py` (drops all rows, resizes column, recreates HNSW index)
3. Run `python indexer.py` to re-embed all photos
- ViT-H/14 (1024-dim) was tested but did not improve over ViT-L/14 (768-dim); reverted

## Search accuracy notes
- **HNSW index is critical** — IVFFlat with default `probes=1` only searches ~1% of data, giving terrible recall. HNSW gives ~99% recall out of the box. Never use IVFFlat without tuning probes.
- **CLIP prompt engineering** — short queries (<=3 words) are auto-prefixed with "a photo of" in `app.py`, which significantly improves CLIP accuracy (e.g. "cat" → "a photo of cat")
- **Min similarity filter** — UI slider (default 20%) filters low-relevance results; adjustable per search

## Notes
- pgvector was built from source — the apt package `postgresql-14-pgvector` is unavailable in default repos
- The CLIP model loads on CUDA if available; expect ~10s startup time on first launch
- `/api/image` validates that requested paths fall under `SCAN_PATHS` before serving
