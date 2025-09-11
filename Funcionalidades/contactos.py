import csv

google_headers = [
    "Given Name",
    "Family Name",
    "Phone 1 - Value",
    "Labels",
    "Nickname",
    "Notes",
    ]

google_indices = {header: idx for idx, header in enumerate(google_headers)}

trad_columna = {
    "Nombre":   "Given Name",
    "Apellido": "Family Name",
    "Teléfono": "Phone 1 - Value",
    "Estado":   "Labels",
    "DNI":      "Nickname",
}

async def genContacts(archivo='example/random.csv', destino='example/contacts.csv'):
    Postulantes = []
    origen = open(archivo, "r")
    reader = csv.reader(origen)
    headers = next(reader)
    
    input_indices = {header: idx for idx, header in enumerate(headers)}
    
    for row in reader:
        new = [""] * len(google_headers)
        for excel_header, google_header in trad_columna.items():
            if excel_header in input_indices:
                new[google_indices[google_header]] = row[input_indices[excel_header]]
        Postulantes.append(new)
    
    with open(destino, "w", encoding="utf-8-sig", newline="") as contactos:
        writer = csv.writer(contactos, lineterminator="\n")
        writer.writerow(google_headers)
        writer.writerows(Postulantes)
    
    print(f"Archivo escrito: {destino}")