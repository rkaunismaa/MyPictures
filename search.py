#!/usr/bin/env python3
"""
Semantic photo search via CLIP text embeddings + pgvector.

Usage:
    python search.py "a dog playing outside"
    python search.py "sunset over mountains" --limit 10
    python search.py "birthday party" --after 2022-01-01 --before 2023-01-01
"""

import argparse
import sys
from datetime import datetime, timezone

import numpy as np
import psycopg
import torch
import open_clip
from pgvector.psycopg import register_vector

from config import (
    DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD,
    CLIP_MODEL, CLIP_PRETRAINED,
)


def get_conn_str():
    parts = [f"host={DB_HOST}", f"port={DB_PORT}", f"dbname={DB_NAME}"]
    if DB_USER:
        parts.append(f"user={DB_USER}")
    if DB_PASSWORD:
        parts.append(f"password={DB_PASSWORD}")
    return " ".join(parts)


def load_clip(device):
    model, _, _ = open_clip.create_model_and_transforms(
        CLIP_MODEL, pretrained=CLIP_PRETRAINED, device=device
    )
    model.eval()
    tokenizer = open_clip.get_tokenizer(CLIP_MODEL)
    return model, tokenizer


def encode_text(model, tokenizer, query: str, device) -> list[float]:
    tokens = tokenizer([query]).to(device)
    with torch.no_grad():
        features = model.encode_text(tokens)
        features = features / features.norm(dim=-1, keepdim=True)
    return features.cpu().float().squeeze().tolist()


def search(conn, embedding: list[float], limit: int,
           after: datetime | None,
           before: datetime | None) -> list[dict]:
    register_vector(conn)

    date_conditions = []
    date_params = []

    if after:
        date_conditions.append("date_taken >= %s")
        date_params.append(after)
    if before:
        date_conditions.append("date_taken <= %s")
        date_params.append(before)

    where_clause = ("WHERE " + " AND ".join(date_conditions)) if date_conditions else ""

    # embedding appears twice (%s #1 in SELECT, %s #last in ORDER BY)
    query = f"""
        SELECT
            file_path,
            file_name,
            date_taken,
            camera_model,
            gps_latitude,
            gps_longitude,
            1 - (embedding <=> %s) AS similarity
        FROM photos
        {where_clause}
        ORDER BY embedding <=> %s
        LIMIT %s
    """
    vec = np.array(embedding, dtype=np.float32)
    params = [vec] + date_params + [vec, limit]

    with conn.cursor() as cur:
        cur.execute(query, params)
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]


def print_results(results: list[dict]):
    if not results:
        print("No results found.")
        return

    # Header
    print()
    print(f"{'#':<4} {'Score':<7} {'Date':<20} {'Camera':<20} {'Path'}")
    print("-" * 100)

    for i, r in enumerate(results, 1):
        score = f"{r['similarity']:.4f}" if r["similarity"] is not None else "  n/a"
        date = r["date_taken"].strftime("%Y-%m-%d %H:%M") if r["date_taken"] else "unknown"
        camera = (r["camera_model"] or "")[:19]
        path = r["file_path"]

        # Truncate long paths for display
        if len(path) > 60:
            path = "..." + path[-57:]

        gps = ""
        if r["gps_latitude"] and r["gps_longitude"]:
            gps = f"  [{r['gps_latitude']:.4f}, {r['gps_longitude']:.4f}]"

        print(f"{i:<4} {score:<7} {date:<20} {camera:<20} {path}{gps}")

    print()
    print(f"{len(results)} result(s)")


def parse_date(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=timezone.utc)


def main():
    parser = argparse.ArgumentParser(description="Semantic photo search")
    parser.add_argument("query", help="Text description to search for")
    parser.add_argument("--limit", type=int, default=20, help="Max results (default 20)")
    parser.add_argument("--after", metavar="YYYY-MM-DD", help="Only photos taken after this date")
    parser.add_argument("--before", metavar="YYYY-MM-DD", help="Only photos taken before this date")
    args = parser.parse_args()

    after = parse_date(args.after) if args.after else None
    before = parse_date(args.before) if args.before else None

    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"Loading CLIP model ({device})...", end=" ", flush=True)
    model, tokenizer = load_clip(device)
    print("done.")

    print(f"Encoding query: \"{args.query}\"...", end=" ", flush=True)
    embedding = encode_text(model, tokenizer, args.query, device)
    print("done.")

    try:
        conn = psycopg.connect(get_conn_str())
    except psycopg.OperationalError as e:
        print(f"ERROR: Cannot connect to database: {e}")
        print("Run python setup_db.py first.")
        sys.exit(1)

    results = search(conn, embedding, args.limit, after=after, before=before)
    conn.close()

    print_results(results)


if __name__ == "__main__":
    main()
