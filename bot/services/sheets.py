import os
import json
from typing import Optional, List

import gspread
from google.oauth2.service_account import Credentials

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

def _gspread_client():
    sa_file = os.environ.get("GOOGLE_SERVICE_ACCOUNT_FILE", "").strip()
    sa_json = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
    if sa_file:
        if not os.path.exists(sa_file):
            raise RuntimeError(f"GOOGLE_SERVICE_ACCOUNT_FILE no existe: {sa_file}")
        creds = Credentials.from_service_account_file(sa_file, scopes=SCOPES)
        return gspread.authorize(creds)
    if sa_json:
        try:
            info = json.loads(sa_json)
        except json.JSONDecodeError as e:
            raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_JSON no es JSON válido.") from e
        creds = Credentials.from_service_account_info(info, scopes=SCOPES)
        return gspread.authorize(creds)
    raise RuntimeError("Falta GOOGLE_SERVICE_ACCOUNT_FILE o GOOGLE_SERVICE_ACCOUNT_JSON")

def _open_spreadsheet():
    gsid = os.environ.get("GSHEET_ID")
    if not gsid:
        raise RuntimeError("Falta GSHEET_ID")
    return _gspread_client().open_by_key(gsid)

def _open_sheet():
    return _open_spreadsheet().sheet1  # principal

def _ensure_worksheet(title: str, headers: Optional[List[str]] = None):
    """Abre o crea (si no existe) una worksheet con el título indicado."""
    sh = _open_spreadsheet()
    try:
        ws = sh.worksheet(title)
    except gspread.exceptions.WorksheetNotFound:
        ws = sh.add_worksheet(title=title, rows=1000, cols=max(5, len(headers or [])))
        if headers:
            ws.update(values=[headers], range_name="A1")
    return ws

