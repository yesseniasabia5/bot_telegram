import csv
import re

async def genVcard(
    archivo='example/junioAngi.csv',
    destino='example/junioAngi.vcf',
    formato='Angi'
    ):
    origen = open(archivo, "r")
    reader = csv.reader(origen)
    
    headers = [
        "Nombre",
        "Teléfono",
    ]
    
    indices = {header: idx for idx, header in enumerate(headers)}
    
    conteo = 0
    with open(destino, "w", encoding="utf-8-sig", newline="") as f:
        for row in reader:
            f.write("BEGIN:VCARD\n")
            f.write("VERSION:4.0\n")
            if row[indices["Nombre"]] == '':
                conteo += 1
                f.write(f"FN:Fiscal {formato} {conteo}\n")
            else:
                f.write(f"FN:Fiscal {formato} {row[indices["Nombre"]]}\n")
            f.write(f"TEL;TYPE=CELL;VALUE=uri:tel:+{re.sub(r'[\s-]', '', row[indices["Teléfono"]])}\n")
            f.write("END:VCARD\n")
            
    print(f"Archivo generado para {formato}: {destino}")
