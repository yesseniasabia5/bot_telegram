from typing import Dict

from bot.config import SHEET_ALLOWED, SHEET_ADMINS, USE_SHEETS
from .sheets import _ensure_worksheet

def _read_ids_and_names_from_sheet(title: str) -> Dict[int, str]:
    """
    Lee IDs/nombres (encabezados 'user_id','name' en A1:B1) y devuelve {id: name}.
    Crea la hoja si no existe.
    """
    ws = _ensure_worksheet(title, headers=["user_id", "name"])
    vals = ws.get_all_values()
    out: Dict[int, str] = {}
    for row in (vals[1:] if vals else []):
        if not row:
            continue
        uid_str = (row[0] or "").strip()
        name = (row[1] or "").strip() if len(row) > 1 else ""
        if uid_str.isdigit():
            out[int(uid_str)] = name
    return out

def _append_id_name_to_sheet(title: str, uid: int, name: str = "") -> None:
    ws = _ensure_worksheet(title, headers=["user_id", "name"])
    registry = _read_ids_and_names_from_sheet(title)
    if uid in registry:
        # Si ya existe, actualizamos el nombre si viene uno no vacío
        if name and registry[uid] != name:
            vals = ws.get_all_values()
            for i, row in enumerate(vals[1:], start=2):
                if row and (row[0] or "").strip().isdigit() and int(row[0].strip()) == uid:
                    ws.update(values=[[str(uid), name]], range_name=f"A{i}:B{i}")
                    return
        return
    ws.append_row([str(uid), name])

def _remove_id_from_sheet(title: str, uid: int) -> bool:
    ws = _ensure_worksheet(title, headers=["user_id", "name"])
    vals = ws.get_all_values()
    if not vals:
        return False
    for i, row in enumerate(vals[1:], start=2):
        uid_str = (row[0] or "").strip()
        if uid_str.isdigit() and int(uid_str) == uid:
            ws.delete_rows(i)
            return True
    return False

def get_admins_map() -> Dict[int, str]:
    import os
    env_admins = {int(x): "" for x in os.environ.get("ADMIN_USER_IDS", "").split(",") if x.strip().isdigit()}
    sheet_admins = _read_ids_and_names_from_sheet(SHEET_ADMINS) if USE_SHEETS else {}
    env_admins.update(sheet_admins)
    return env_admins

def get_allowed_map() -> Dict[int, str]:
    """Allowed = Admins ∪ AllowedSheet ∪ ALLOWED_USER_IDS (.env)."""
    import os
    env_allowed = {int(x): "" for x in os.environ.get("ALLOWED_USER_IDS", "").split(",") if x.strip().isdigit()}
    sheet_allowed = _read_ids_and_names_from_sheet(SHEET_ALLOWED) if USE_SHEETS else {}
    all_allowed = get_admins_map()
    all_allowed.update(sheet_allowed)
    for k, v in env_allowed.items():
        if k not in all_allowed:
            all_allowed[k] = v
    return all_allowed

def get_admin_ids() -> set[int]:
    return set(get_admins_map().keys())

def get_allowed_ids() -> set[int]:
    return set(get_allowed_map().keys())

