import os
import logging
from dotenv import load_dotenv

# Load environment early
load_dotenv()

# Quiet noisy loggers
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("apscheduler").setLevel(logging.WARNING)

# Basic logging config
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

# CSV headers and indices
CSV_HEADERS = ["Nombre", "Apellido", "Teléfono", "DNI", "Estado", "Observación"]
IDX = {h: i for i, h in enumerate(CSV_HEADERS)}

# Google Contacts export headers
GOOGLE_HEADERS = [
    "Given Name",
    "Family Name",
    "Phone 1 - Value",
    "Labels",
    "Nickname",
    "Notes",
]

# Storage configuration
CSV_DEFAULT = os.environ.get("LISTA_CSV", "lista.csv").strip() or "lista.csv"
USE_SHEETS = os.environ.get("USE_SHEETS", "1").strip() != "0"

# Sheets tabs for roles
SHEET_ALLOWED = os.environ.get("SHEET_ALLOWED", "Usuarios permitidos").strip() or "Usuarios permitidos"
SHEET_ADMINS = os.environ.get("SHEET_ADMINS", "Admins").strip() or "Admins"

