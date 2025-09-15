import os
import re
from typing import List

from bot.config import GOOGLE_HEADERS, CSV_HEADERS, IDX
from .lista import read_lista_any, _pad_row

def gen_contacts_any(output_csv: str) -> str:
    body = read_lista_any()
    out_rows = [GOOGLE_HEADERS]
    for row in body:
        row = _pad_row(row, len(CSV_HEADERS))
        given, family, phone, dni, labels = (
            row[IDX["Nombre"]],
            row[IDX["Apellido"]],
            row[IDX["Teléfono"]],
            row[IDX["DNI"]],
            row[IDX["Estado"]],
        )
        out_rows.append([given, family, phone, labels, dni, row[IDX["Observación"]]])
    os.makedirs(os.path.dirname(output_csv) or ".", exist_ok=True)
    # simple CSV writer to avoid importing writer again
    import csv as _csv
    with open(output_csv, "w", encoding="utf-8", newline="") as f:
        _csv.writer(f, lineterminator="\n").writerows(out_rows)
    return output_csv

def gen_vcard_from_rows(rows: List[List[str]], output_vcf: str, etiqueta: str = "General") -> str:
    count = 0
    os.makedirs(os.path.dirname(output_vcf) or ".", exist_ok=True)
    with open(output_vcf, "w", encoding="utf-8", newline="") as f:
        for row in rows:
            row = _pad_row(row, len(CSV_HEADERS))
            nombre = row[IDX["Nombre"]].strip()
            telefono = row[IDX["Teléfono"]].strip()
            if not telefono:
                continue
            count += 1
            telefono_uri = re.sub(r"[^\d+]", "", telefono)
            display = f"Fiscal {etiqueta} {nombre}" if nombre else f"Fiscal {etiqueta} {count}"
            f.write("BEGIN:VCARD\n")
            f.write("VERSION:4.0\n")
            f.write(f"FN:{display}\n")
            f.write(f"TEL;TYPE=CELL;VALUE=uri:tel:{telefono_uri}\n")
            f.write("END:VCARD\n")
    return output_vcf

def gen_vcard_any(output_vcf: str, etiqueta: str = "General") -> str:
    rows = read_lista_any()
    return gen_vcard_from_rows(rows, output_vcf, etiqueta)

