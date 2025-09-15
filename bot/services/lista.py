import os
import csv
import re
import unicodedata
from typing import List

from bot.config import CSV_DEFAULT, CSV_HEADERS, IDX, USE_SHEETS
from .sheets import _open_sheet

def _norm(s: str) -> str:
    s = s.strip()
    s = "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))
    return s.lower()

def _clean_phone(s: str) -> str:
    return s.strip().replace(" ", "").replace("-", "")

def _read_csv_rows(path: str) -> List[List[str]]:
    if not os.path.exists(path):
        return []
    with open(path, mode="r", encoding="utf-8-sig") as f:
        return list(csv.reader(f))

def _write_csv_rows(path: str, rows: List[List[str]]):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f, lineterminator="\n")
        writer.writerows(rows)

def _pad_row(row: List[str], n: int) -> List[str]:
    if len(row) < n:
        return row + [""] * (n - len(row))
    return row[:n]

def read_lista_any() -> List[List[str]]:
    if USE_SHEETS:
        ws = _open_sheet()
        vals = ws.get_all_values()
        body = [_pad_row(r, len(CSV_HEADERS)) for r in (vals[1:] if vals else [])]
        return body
    else:
        rows = _read_csv_rows(CSV_DEFAULT)
        body = [_pad_row(r, len(CSV_HEADERS)) for r in (rows[1:] if rows else [])]
        return body

def set_lista_any(rows: List[List[str]]):
    rows = [_pad_row(r, len(CSV_HEADERS)) for r in rows]
    if USE_SHEETS:
        ws = _open_sheet()
        ws.clear()
        ws.update(values=[CSV_HEADERS] + rows, range_name="A1")
    else:
        _write_csv_rows(CSV_DEFAULT, [CSV_HEADERS] + rows)

def append_contact_any(row: List[str]) -> str:
    """Inserta o actualiza por Teléfono/DNI. Devuelve 'new' o 'updated'."""
    row = _pad_row(row, len(CSV_HEADERS))
    if USE_SHEETS:
        ws = _open_sheet()
        vals = ws.get_all_values()
        if not vals:
            ws.update(values=[CSV_HEADERS], range_name="A1")
            ws.append_row(row)
            return "new"
        body = [_pad_row(r, len(CSV_HEADERS)) for r in vals[1:]]
        for i, r in enumerate(body):
            if r[IDX["Teléfono"]] == row[IDX["Teléfono"]] or (row[IDX["DNI"]] and r[IDX["DNI"]] == row[IDX["DNI"]]):
                ws.update(values=[row], range_name=f"A{i+2}:F{i+2}")  # 6 columnas
                return "updated"
        ws.append_row(row)
        return "new"
    else:
        rows = read_lista_any()
        for i, r in enumerate(rows):
            if r[IDX["Teléfono"]] == row[IDX["Teléfono"]] or (row[IDX["DNI"]] and r[IDX["DNI"]] == row[IDX["DNI"]]):
                rows[i] = row
                set_lista_any(rows)
                return "updated"
        rows.append(row)
        set_lista_any(rows)
        return "new"

def filter_by_status(rows: List[List[str]], estado: str) -> List[List[str]]:
    return [r for r in rows if len(r) > IDX["Estado"] and r[IDX["Estado"]] == estado]

def _col_number_from_idx(idx0: int) -> int:
    return idx0 + 1

def _find_by_keys_fallback(all_rows: List[List[str]], target: List[str]) -> int:
    target = _pad_row(target, len(CSV_HEADERS))
    tel = target[IDX["Teléfono"]].strip()
    dni = target[IDX["DNI"]].strip()
    for i, r in enumerate(all_rows):
        r = _pad_row(r, len(CSV_HEADERS))
        if (r[IDX["Teléfono"]].strip() == tel) or (dni and r[IDX["DNI"]].strip() == dni):
            return i
    return -1

def update_estado_by_row_index(abs_index: int, nuevo_estado: str, base_rows: List[List[str]], observacion: str = "") -> None:
    """Actualiza Estado (y Observación si aplica) en la fila real correspondiente."""
    if USE_SHEETS:
        all_rows = read_lista_any()
        target = _pad_row(base_rows[abs_index], len(CSV_HEADERS))
        try:
            real_idx = next(i for i, r in enumerate(all_rows) if _pad_row(r, len(CSV_HEADERS)) == target)
        except StopIteration:
            real_idx = _find_by_keys_fallback(all_rows, target)
        if real_idx < 0:
            raise RuntimeError("No se encontró la fila a actualizar.")
        ws = _open_sheet()
        row = real_idx + 2  # header +1
        ws.update_cell(row, _col_number_from_idx(IDX["Estado"]), nuevo_estado)
        if nuevo_estado == "Contactar Luego":
            ws.update_cell(row, _col_number_from_idx(IDX["Observación"]), observacion or "")
        elif nuevo_estado == "Pendiente" or nuevo_estado.startswith("En contacto"):
            ws.update_cell(row, _col_number_from_idx(IDX["Observación"]), "")
    else:
        rows = read_lista_any()
        target = _pad_row(base_rows[abs_index], len(CSV_HEADERS))
        try:
            real_idx = next(i for i, r in enumerate(rows) if _pad_row(r, len(CSV_HEADERS)) == target)
        except StopIteration:
            real_idx = _find_by_keys_fallback(rows, target)
        if 0 <= real_idx < len(rows):
            r = _pad_row(rows[real_idx], len(CSV_HEADERS))
            r[IDX["Estado"]] = nuevo_estado
            if nuevo_estado == "Contactar Luego":
                r[IDX["Observación"]] = observacion or ""
            elif nuevo_estado == "Pendiente" or nuevo_estado.startswith("En contacto"):
                r[IDX["Observación"]] = ""
            rows[real_idx] = r
            set_lista_any(rows)

