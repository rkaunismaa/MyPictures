# MyPictures

A local photo search system. Index your photos once, then search them with natural language — "golden hour at the beach", "birthday cake", "dog in the snow" — using CLIP semantic embeddings and pgvector similarity search.

A FastAPI + React web interface provides a searchable photo grid with a lightbox viewer.

## How It Works

1. **Index** — scans configured directories, extracts EXIF metadata, computes CLIP embeddings, and stores everything in PostgreSQL with pgvector.
2. **Search** — encodes a text query with the same CLIP model and finds the most visually similar photos via cosine similarity.

## Requirements

- Python 3.10+
- PostgreSQL 14+ with [pgvector](https://github.com/pgvector/pgvector)
- CUDA GPU recommended (CPU works but is slower)
- Node.js 18+ (for the web frontend)

## Setup

### 1. Create a virtual environment

```bash
uv venv .mypictures --python 3.11
source .mypictures/bin/activate
uv pip install -e .
```

### 2. Configure

Create a `.env` file in the repo root:
```
DB_PASSWORD=yourpassword
```

Edit `config.py` to set your photo directories:
```python
SCAN_PATHS = [
    "~/Pictures",
    "~/Photos",
]
```

### 3. Set up the database

```bash
python setup_db.py
```

### 4. Index your photos

```bash
python indexer.py
```

This will scan all configured directories, compute CLIP embeddings, and populate the database. This takes a while on first run — subsequent runs only process new/changed files.

## Usage

### CLI Search

```bash
python search.py "a dog playing outside"
python search.py "sunset over mountains" --limit 10
python search.py "birthday party" --after 2022-01-01 --before 2023-01-01
```

### Web App

**Development** (two terminals):
```bash
# Terminal 1 — backend
python -m uvicorn app:app --host 0.0.0.0 --port 8000

# Terminal 2 — frontend
cd frontend && npm install && npm run dev
```
Open http://localhost:5173

**Production** (single process):
```bash
cd frontend && npm run build
python -m uvicorn app:app --host 0.0.0.0 --port 8000
```
Open http://localhost:8000

## Project Structure

```
├── config.py        # Scan paths, DB and model settings
├── setup_db.py      # Database initialisation
├── indexer.py       # Photo indexing pipeline
├── search.py        # CLI search tool
├── app.py           # FastAPI backend
├── frontend/        # React + Vite web app
│   └── src/App.jsx  # UI (search bar, grid, lightbox)
└── pyproject.toml
```

## Stack

| Layer | Technology |
|---|---|
| Embeddings | OpenCLIP ViT-L/14 (laion2b_s32b_b82k) |
| Vector DB | PostgreSQL 14 + pgvector |
| Backend | FastAPI + uvicorn |
| Frontend | React 18 + Vite 5 |
