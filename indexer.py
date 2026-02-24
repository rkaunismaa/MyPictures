#!/usr/bin/env python3
"""
Scan image directories, extract EXIF metadata, compute CLIP embeddings,
and upsert everything into the mypictures PostgreSQL database.

Usage:
    python indexer.py
    python indexer.py --paths ~/Photos ~/Pictures   # override scan paths
"""

import argparse
import hashlib
import os
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

import piexif
import psycopg
import torch
import open_clip
from PIL import Image, UnidentifiedImageError
from tqdm import tqdm

from config import (
    SCAN_PATHS, DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD,
    CLIP_MODEL, CLIP_PRETRAINED, BATCH_SIZE, IMAGE_EXTENSIONS,
)


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def get_conn_str():
    parts = [f"host={DB_HOST}", f"port={DB_PORT}", f"dbname={DB_NAME}"]
    if DB_USER:
        parts.append(f"user={DB_USER}")
    if DB_PASSWORD:
        parts.append(f"password={DB_PASSWORD}")
    return " ".join(parts)


def fetch_existing(conn):
    """Return set of file_paths and set of file_hashes already in DB."""
    with conn.cursor() as cur:
        cur.execute("SELECT file_path, file_hash FROM photos WHERE file_hash IS NOT NULL")
        rows = cur.fetchall()
    paths = {r[0] for r in rows}
    hashes = {r[1] for r in rows if r[1]}
    return paths, hashes


def upsert_batch(conn, records):
    """Upsert a list of photo record dicts into the photos table."""
    if not records:
        return
    with conn.cursor() as cur:
        for r in records:
            cur.execute("""
                INSERT INTO photos (
                    file_path, file_name, file_size, file_hash,
                    width, height, format,
                    date_taken, date_modified, date_indexed,
                    camera_make, camera_model, lens_model,
                    iso, aperture, shutter_speed, focal_length, flash,
                    gps_latitude, gps_longitude, gps_altitude,
                    embedding
                ) VALUES (
                    %(file_path)s, %(file_name)s, %(file_size)s, %(file_hash)s,
                    %(width)s, %(height)s, %(format)s,
                    %(date_taken)s, %(date_modified)s, NOW(),
                    %(camera_make)s, %(camera_model)s, %(lens_model)s,
                    %(iso)s, %(aperture)s, %(shutter_speed)s, %(focal_length)s, %(flash)s,
                    %(gps_latitude)s, %(gps_longitude)s, %(gps_altitude)s,
                    %(embedding)s
                )
                ON CONFLICT (file_path) DO UPDATE SET
                    file_size     = EXCLUDED.file_size,
                    file_hash     = EXCLUDED.file_hash,
                    width         = EXCLUDED.width,
                    height        = EXCLUDED.height,
                    format        = EXCLUDED.format,
                    date_taken    = EXCLUDED.date_taken,
                    date_modified = EXCLUDED.date_modified,
                    date_indexed  = NOW(),
                    camera_make   = EXCLUDED.camera_make,
                    camera_model  = EXCLUDED.camera_model,
                    lens_model    = EXCLUDED.lens_model,
                    iso           = EXCLUDED.iso,
                    aperture      = EXCLUDED.aperture,
                    shutter_speed = EXCLUDED.shutter_speed,
                    focal_length  = EXCLUDED.focal_length,
                    flash         = EXCLUDED.flash,
                    gps_latitude  = EXCLUDED.gps_latitude,
                    gps_longitude = EXCLUDED.gps_longitude,
                    gps_altitude  = EXCLUDED.gps_altitude,
                    embedding     = EXCLUDED.embedding
            """, r)
    conn.commit()


# ---------------------------------------------------------------------------
# File / EXIF helpers
# ---------------------------------------------------------------------------

def md5_file(path: Path) -> str:
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _rational_to_float(rational):
    """Convert piexif rational (numerator, denominator) to float."""
    if rational is None:
        return None
    num, den = rational
    if den == 0:
        return None
    return num / den


def _gps_dms_to_decimal(dms, ref: str) -> float | None:
    """Convert GPS DMS tuple from piexif to decimal degrees."""
    if not dms or len(dms) < 3:
        return None
    degrees = _rational_to_float(dms[0])
    minutes = _rational_to_float(dms[1])
    seconds = _rational_to_float(dms[2])
    if degrees is None:
        return None
    decimal = degrees + (minutes or 0) / 60 + (seconds or 0) / 3600
    if ref in ("S", "W"):
        decimal = -decimal
    return decimal


def _decode(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace").strip("\x00").strip()
    return str(value).strip()


def extract_exif(path: Path) -> dict:
    data = {}
    try:
        exif_dict = piexif.load(str(path))
    except Exception:
        return data

    zeroth = exif_dict.get("0th", {})
    exif = exif_dict.get("Exif", {})
    gps = exif_dict.get("GPS", {})

    # Camera info
    data["camera_make"] = _decode(zeroth.get(piexif.ImageIFD.Make))
    data["camera_model"] = _decode(zeroth.get(piexif.ImageIFD.Model))

    # Lens
    data["lens_model"] = _decode(exif.get(piexif.ExifIFD.LensModel))

    # Date taken
    dt_str = _decode(exif.get(piexif.ExifIFD.DateTimeOriginal))
    if dt_str:
        try:
            data["date_taken"] = datetime.strptime(dt_str, "%Y:%m:%d %H:%M:%S").replace(
                tzinfo=timezone.utc
            )
        except ValueError:
            pass

    # Exposure
    iso_val = exif.get(piexif.ExifIFD.ISOSpeedRatings)
    if iso_val is not None:
        data["iso"] = int(iso_val) if not isinstance(iso_val, tuple) else int(iso_val[0])

    fnumber = exif.get(piexif.ExifIFD.FNumber)
    if fnumber:
        data["aperture"] = _rational_to_float(fnumber)

    exp_time = exif.get(piexif.ExifIFD.ExposureTime)
    if exp_time:
        num, den = exp_time
        if den == 0:
            pass
        elif num == 0:
            pass
        elif den % num == 0:
            data["shutter_speed"] = f"1/{den // num}"
        else:
            data["shutter_speed"] = f"{num}/{den}"

    fl = exif.get(piexif.ExifIFD.FocalLength)
    if fl:
        data["focal_length"] = _rational_to_float(fl)

    flash_val = exif.get(piexif.ExifIFD.Flash)
    if flash_val is not None:
        data["flash"] = "fired" if (flash_val & 0x1) else "not fired"

    # GPS
    if gps:
        lat_dms = gps.get(piexif.GPSIFD.GPSLatitude)
        lat_ref = _decode(gps.get(piexif.GPSIFD.GPSLatitudeRef)) or "N"
        lon_dms = gps.get(piexif.GPSIFD.GPSLongitude)
        lon_ref = _decode(gps.get(piexif.GPSIFD.GPSLongitudeRef)) or "E"
        alt = gps.get(piexif.GPSIFD.GPSAltitude)

        lat = _gps_dms_to_decimal(lat_dms, lat_ref)
        lon = _gps_dms_to_decimal(lon_dms, lon_ref)
        if lat is not None:
            data["gps_latitude"] = lat
        if lon is not None:
            data["gps_longitude"] = lon
        if alt:
            data["gps_altitude"] = _rational_to_float(alt)

    return data


# ---------------------------------------------------------------------------
# CLIP model
# ---------------------------------------------------------------------------

def load_clip(device):
    print(f"Loading CLIP model {CLIP_MODEL} ({CLIP_PRETRAINED}) on {device}...")
    model, _, preprocess = open_clip.create_model_and_transforms(
        CLIP_MODEL, pretrained=CLIP_PRETRAINED, device=device
    )
    model.eval()
    return model, preprocess


def embed_images(model, preprocess, pil_images, device):
    """Return L2-normalised embeddings as a list of Python lists."""
    tensors = torch.stack([preprocess(img) for img in pil_images]).to(device)
    with torch.no_grad():
        features = model.encode_image(tensors)
        features = features / features.norm(dim=-1, keepdim=True)
    return features.cpu().float().tolist()


# ---------------------------------------------------------------------------
# File collection
# ---------------------------------------------------------------------------

def collect_image_paths(scan_paths: list[str]) -> list[Path]:
    found = []
    for raw in scan_paths:
        root = Path(raw).expanduser().resolve()
        if not root.exists():
            print(f"  [warn] Path does not exist, skipping: {root}")
            continue
        for p in root.rglob("*"):
            if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS:
                found.append(p)
    return found


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Index photos into mypictures DB")
    parser.add_argument("--paths", nargs="*", help="Override scan paths from config")
    args = parser.parse_args()

    scan_paths = args.paths if args.paths else SCAN_PATHS

    device = "cuda" if torch.cuda.is_available() else "cpu"
    model, preprocess = load_clip(device)

    print("Connecting to database...")
    conn = psycopg.connect(get_conn_str())

    print("Fetching already-indexed paths and hashes...")
    existing_paths, existing_hashes = fetch_existing(conn)
    print(f"  {len(existing_paths)} paths already indexed.")

    print("Scanning for image files...")
    all_files = collect_image_paths(scan_paths)
    print(f"  Found {len(all_files)} image files.")

    # Filter already-indexed paths
    new_files = [p for p in all_files if str(p) not in existing_paths]
    print(f"  {len(new_files)} new files to process.")

    if not new_files:
        print("Nothing to do. All files already indexed.")
        conn.close()
        return

    n_new = 0
    n_skipped_hash = 0
    n_errors = 0

    batch_meta = []   # list of partial record dicts (no embedding yet)
    batch_imgs = []   # PIL images for CLIP

    def flush_batch():
        nonlocal n_new
        if not batch_imgs:
            return
        embeddings = embed_images(model, preprocess, batch_imgs, device)
        records = []
        for meta, emb in zip(batch_meta, embeddings):
            meta["embedding"] = emb
            records.append(meta)
        upsert_batch(conn, records)
        n_new += len(records)
        batch_meta.clear()
        batch_imgs.clear()

    pbar = tqdm(new_files, unit="img", desc="Indexing")
    for path in pbar:
        try:
            # Hash-based dedup across folders
            file_hash = md5_file(path)
            if file_hash in existing_hashes:
                n_skipped_hash += 1
                pbar.set_postfix(new=n_new, skip=n_skipped_hash, err=n_errors)
                continue
            existing_hashes.add(file_hash)

            # Open image
            try:
                img = Image.open(path).convert("RGB")
            except (UnidentifiedImageError, Exception):
                n_errors += 1
                continue

            width, height = img.size
            fmt = img.format or path.suffix.lstrip(".").upper()
            stat = path.stat()
            date_modified = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)

            exif_data = extract_exif(path)

            record = {
                "file_path": str(path),
                "file_name": path.name,
                "file_size": stat.st_size,
                "file_hash": file_hash,
                "width": width,
                "height": height,
                "format": fmt,
                "date_taken": exif_data.get("date_taken"),
                "date_modified": date_modified,
                "camera_make": exif_data.get("camera_make"),
                "camera_model": exif_data.get("camera_model"),
                "lens_model": exif_data.get("lens_model"),
                "iso": exif_data.get("iso"),
                "aperture": exif_data.get("aperture"),
                "shutter_speed": exif_data.get("shutter_speed"),
                "focal_length": exif_data.get("focal_length"),
                "flash": exif_data.get("flash"),
                "gps_latitude": exif_data.get("gps_latitude"),
                "gps_longitude": exif_data.get("gps_longitude"),
                "gps_altitude": exif_data.get("gps_altitude"),
                "embedding": None,
            }

            batch_meta.append(record)
            batch_imgs.append(img)

            if len(batch_imgs) >= BATCH_SIZE:
                flush_batch()

            pbar.set_postfix(new=n_new, skip=n_skipped_hash, err=n_errors)

        except Exception:
            n_errors += 1
            tqdm.write(f"ERROR processing {path}:\n{traceback.format_exc()}")

    flush_batch()
    pbar.close()

    conn.close()

    print()
    print("=== Indexing complete ===")
    print(f"  New images indexed : {n_new}")
    print(f"  Skipped (dup hash) : {n_skipped_hash}")
    print(f"  Errors             : {n_errors}")


if __name__ == "__main__":
    main()
