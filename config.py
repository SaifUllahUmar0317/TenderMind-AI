import os
from pathlib import Path

# Base directory
BASE_DIR = Path(__file__).resolve().parent

# Load .env if present
env_file = BASE_DIR / ".env"
if env_file.exists():
    with open(env_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ[k.strip()] = v.strip()

# Fix OpenBLAS / OpenMP thread pool allocation crashes on Windows
os.environ["OPENBLAS_NUM_THREADS"] = "1"
os.environ["OMP_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"
os.environ["NUMEXPR_NUM_THREADS"] = "1"
os.environ["VECLIB_MAXIMUM_THREADS"] = "1"

# Upload & Temp folders (use writable /tmp directory on Vercel serverless)
if os.getenv("VERCEL"):
    UPLOAD_FOLDER = Path("/tmp/uploads")
    TEMP_FOLDER = Path("/tmp/temp")
else:
    UPLOAD_FOLDER = BASE_DIR / "uploads"
    TEMP_FOLDER = BASE_DIR / "temp"

# Ensure directories exist
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(TEMP_FOLDER, exist_ok=True)

def _safe_int_env(key: str, default: int) -> int:
    val = os.getenv(key, "")
    if val is None or not str(val).strip():
        return default
    try:
        return int(str(val).strip())
    except (ValueError, TypeError):
        return default

# Database Settings
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()

# Application Settings
MAX_CONTENT_LENGTH = _safe_int_env("MAX_FILE_SIZE", 50 * 1024 * 1024)  # Default 50MB for RAG uploads
COMBINER_MAX_CONTENT_LENGTH = _safe_int_env("COMBINER_MAX_FILE_SIZE", 2 * 1024 * 1024 * 1024)  # 2GB for combiner
ALLOWED_EXTENSIONS = {"pdf"}

# Server Settings
HOST = os.getenv("HOST", "0.0.0.0").strip() or "0.0.0.0"
PORT = _safe_int_env("PORT", 5000)
DEBUG = (os.getenv("FLASK_ENV", "production").strip() or "production") == "development"

# OCR & PDF Extraction Settings
DEFAULT_DPI = _safe_int_env("OCR_DPI", 300)
DEFAULT_OCR_LANG = os.getenv("OCR_LANG", "eng").strip() or "eng"

# Detect Tesseract Path on Windows if not set in environment
TESSERACT_CMD = os.getenv("TESSERACT_CMD")
if not TESSERACT_CMD:
    win_tesseract = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
    if os.path.exists(win_tesseract):
        TESSERACT_CMD = win_tesseract

# Supported Languages for UI dropdown
SUPPORTED_LANGUAGES = [
    {"code": "eng", "name": "English"},
    {"code": "fra", "name": "French"},
    {"code": "deu", "name": "German"},
    {"code": "spa", "name": "Spanish"},
    {"code": "urd", "name": "Urdu"},
    {"code": "ara", "name": "Arabic"},
    {"code": "chi_sim", "name": "Chinese (Simplified)"},
    {"code": "rus", "name": "Russian"},
]
