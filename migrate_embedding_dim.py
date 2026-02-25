#!/usr/bin/env python3
"""
Migrate the photos table embedding column to match the current EMBEDDING_DIM
in config.py. Clears all existing embeddings (re-index required afterward).

Usage:
    python migrate_embedding_dim.py
"""

import sys
import psycopg
from config import DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD, EMBEDDING_DIM


def get_conn_str():
    parts = [f"host={DB_HOST}", f"port={DB_PORT}", f"dbname={DB_NAME}"]
    if DB_USER:
        parts.append(f"user={DB_USER}")
    if DB_PASSWORD:
        parts.append(f"password={DB_PASSWORD}")
    return " ".join(parts)


def main():
    print(f"Migrating embedding column to vector({EMBEDDING_DIM})...")

    try:
        conn = psycopg.connect(get_conn_str())
    except psycopg.OperationalError as e:
        print(f"ERROR: Cannot connect to database: {e}")
        sys.exit(1)

    conn.autocommit = True
    cur = conn.cursor()

    print("  Dropping embedding index...")
    cur.execute("DROP INDEX IF EXISTS photos_embedding_idx")

    print("  Deleting all rows (re-index required)...")
    cur.execute("DELETE FROM photos")

    print(f"  Resizing column to vector({EMBEDDING_DIM})...")
    cur.execute(f"ALTER TABLE photos ALTER COLUMN embedding TYPE vector({EMBEDDING_DIM})")

    print("  Recreating HNSW index...")
    cur.execute("""
        CREATE INDEX photos_embedding_idx
        ON photos USING hnsw (embedding vector_cosine_ops)
    """)

    conn.close()
    print()
    print("Done. All rows deleted and column resized.")
    print("Next step: python indexer.py")


if __name__ == "__main__":
    main()
