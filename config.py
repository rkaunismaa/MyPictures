import os
from pathlib import Path


def _load_env():
    env_file = Path(__file__).parent / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                os.environ.setdefault(key.strip(), value.strip())

_load_env()


SCAN_PATHS = [
    "~/Data/Drive1/Pictures",
    "~/Data/Drive2/Photos",
]

DB_HOST = os.environ.get("DB_HOST", "localhost")
DB_PORT = int(os.environ.get("DB_PORT", 5432))
DB_NAME = os.environ.get("DB_NAME", "mypictures")
DB_USER = os.environ.get("DB_USER", "postgres")
DB_PASSWORD = os.environ.get("DB_PASSWORD", "")

CLIP_MODEL = "ViT-L-14"
CLIP_PRETRAINED = "laion2b_s32b_b82k"
BATCH_SIZE = 32

IMAGE_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tiff", ".tif",
    ".heic", ".heif", ".webp", ".cr2", ".cr3", ".nef", ".arw",
    ".dng", ".orf", ".rw2", ".pef",
}
