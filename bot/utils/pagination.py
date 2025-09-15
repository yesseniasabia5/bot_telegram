from typing import List
import re

from bot.config import CSV_HEADERS, IDX
from bot.services.lista import _pad_row

def _clean_estado_for_display(est: str) -> str:
    if not est:
        return est
    s = est.strip()
    # Casos corruptos: "En contacto - (6415..., Update(...))" o "En contacto - 6415..., Update(...)"
    m = re.match(r"^En contacto\s*[-–—]\s*\((\d{5,})\b.*", s)
    if m:
        return f"En contacto - {m.group(1)}"
    m = re.match(r"^En contacto\s*[-–—]\s*(\d{5,})\b.*", s)
    if m:
        return f"En contacto - {m.group(1)}"
    if s.startswith("En contacto") and "Update(" in s:
        m = re.search(r"\b(\d{5,})\b", s)
        return f"En contacto - {m.group(1)}" if m else "En contacto"
    # Normal: "En contacto - quien" lo dejamos igual
    return s

def _chunk_rows(rows, size=10):
    for i in range(0, len(rows), size):
        yield rows[i:i+size]

def _format_persona(row: List[str]) -> str:
    try:
        row = _pad_row(row, len(CSV_HEADERS))
        tel = row[IDX["Teléfono"]]
        nom = row[IDX["Nombre"]]
        ape = row[IDX["Apellido"]]
        est = _clean_estado_for_display(row[IDX["Estado"]])
        obs = row[IDX["Observación"]]
        tail = f" - {est}" if est else ""
        if est.startswith("Contactar Luego") and obs:
            tail += f" ({obs})"
        return f"{tel}: {nom}, {ape}{tail}"
    except Exception:
        return "Fila inválida"
