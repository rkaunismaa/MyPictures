#!/usr/bin/env python3
"""
Create the mypictures database, enable pgvector, and set up the photos schema.

PostgreSQL setup (if not already installed):
    sudo apt install -y postgresql postgresql-contrib
    sudo systemctl enable --now postgresql

pgvector (build from source — apt package may not be available for your PG version):
    sudo apt install -y build-essential postgresql-server-dev-14
    git clone https://github.com/pgvector/pgvector.git
    cd pgvector && make && sudo make install

DBeaver (GUI browser):
    sudo snap install dbeaver-ce
    Connect to: localhost:5432 / database: mypictures
"""

import sys
import psycopg
from psycopg.rows import dict_row
from config import DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD


def get_conn_str(dbname="postgres"):
    parts = [f"host={DB_HOST}", f"port={DB_PORT}", f"dbname={dbname}"]
    if DB_USER:
        parts.append(f"user={DB_USER}")
    if DB_PASSWORD:
        parts.append(f"password={DB_PASSWORD}")
    return " ".join(parts)


def check_postgres():
    try:
        conn = psycopg.connect(get_conn_str(), connect_timeout=5)
        conn.close()
        return True
    except psycopg.OperationalError as e:
        print("ERROR: Cannot connect to PostgreSQL.")
        print(f"  {e}")
        print()
        print("To install and start PostgreSQL:")
        print("  sudo apt install -y postgresql postgresql-contrib")
        print("  sudo systemctl enable --now postgresql")
        print()
        print("If PostgreSQL is installed but not running:")
        print("  sudo systemctl start postgresql")
        print()
        print("If you need to set a password for the postgres user:")
        print("  sudo -u postgres psql")
        print("  ALTER USER postgres PASSWORD 'yourpassword';")
        print("Then set DB_USER=postgres and DB_PASSWORD=yourpassword in config.py or env vars.")
        return False


def create_database(conn):
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (DB_NAME,))
        if cur.fetchone():
            print(f"Database '{DB_NAME}' already exists.")
        else:
            cur.execute(f"CREATE DATABASE {DB_NAME}")
            print(f"Created database '{DB_NAME}'.")


def setup_schema():
    with psycopg.connect(get_conn_str(DB_NAME), row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            # Enable pgvector
            cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
            print("pgvector extension enabled.")

            # Create photos table
            cur.execute("""
                CREATE TABLE IF NOT EXISTS photos (
                    id              SERIAL PRIMARY KEY,
                    file_path       TEXT UNIQUE NOT NULL,
                    file_name       TEXT,
                    file_size       BIGINT,
                    file_hash       TEXT,
                    width           INTEGER,
                    height          INTEGER,
                    format          TEXT,
                    date_taken      TIMESTAMPTZ,
                    date_modified   TIMESTAMPTZ,
                    date_indexed    TIMESTAMPTZ DEFAULT NOW(),
                    camera_make     TEXT,
                    camera_model    TEXT,
                    lens_model      TEXT,
                    iso             INTEGER,
                    aperture        REAL,
                    shutter_speed   TEXT,
                    focal_length    REAL,
                    flash           TEXT,
                    gps_latitude    DOUBLE PRECISION,
                    gps_longitude   DOUBLE PRECISION,
                    gps_altitude    DOUBLE PRECISION,
                    embedding       vector(768)
                )
            """)
            print("Table 'photos' ready.")

            # IVFFlat index on embedding (requires data to be present first;
            # safe to create now — will be used once rows are inserted)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS photos_embedding_idx
                ON photos
                USING ivfflat (embedding vector_cosine_ops)
                WITH (lists = 100)
            """)
            print("IVFFlat index on embedding ready.")

            # Index on file_hash for dedup lookups
            cur.execute("""
                CREATE INDEX IF NOT EXISTS photos_hash_idx
                ON photos (file_hash)
            """)

            # Index on date_taken for date-range filters
            cur.execute("""
                CREATE INDEX IF NOT EXISTS photos_date_taken_idx
                ON photos (date_taken)
            """)

        conn.commit()
        print("Schema setup complete.")


def main():
    print("=== MyPictures DB Setup ===")

    if not check_postgres():
        sys.exit(1)

    print(f"Connecting to PostgreSQL at {DB_HOST}:{DB_PORT}...")
    with psycopg.connect(get_conn_str()) as conn:
        create_database(conn)

    print(f"Setting up schema in '{DB_NAME}'...")
    setup_schema()

    print()
    print("All done! Next steps:")
    print(f"  python indexer.py   # scan and index your photos")
    print(f"  python search.py \"a dog playing outside\"")


if __name__ == "__main__":
    main()
