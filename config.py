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

# Upload & Temp folders
UPLOAD_FOLDER = BASE_DIR / "uploads"
TEMP_FOLDER = BASE_DIR / "temp"

# Ensure directories exist
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(TEMP_FOLDER, exist_ok=True)

# Application Settings
MAX_CONTENT_LENGTH = int(os.getenv("MAX_FILE_SIZE", 50 * 1024 * 1024))  # Default 50MB for RAG uploads
COMBINER_MAX_CONTENT_LENGTH = int(os.getenv("COMBINER_MAX_FILE_SIZE", 2 * 1024 * 1024 * 1024))  # 2GB for combiner
ALLOWED_EXTENSIONS = {"pdf"}

# Server Settings
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", 5000))
DEBUG = os.getenv("FLASK_ENV", "development") == "development"

# OCR & PDF Extraction Settings
DEFAULT_DPI = int(os.getenv("OCR_DPI", 300))
DEFAULT_OCR_LANG = os.getenv("OCR_LANG", "eng")

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
