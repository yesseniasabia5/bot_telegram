import requests
import csv

async def descargarCSV(url, archivo_salida):
    print("\nDescargando archivo...\n")
    consulta = requests.get(url)
    contenido = consulta.content

    print("\nGuardando archivo...\n")
    # Abrir conexion en modo escritura
    with open(archivo_salida, "w", encoding="utf-8") as archivo:
        # Escribir el contenido de la consulta
        archivo.write(contenido.decode("utf-8"))

    print(f"\n¡Archivo descargado en {archivo_salida}\n")

headers = [
    "Nombre",
    "Apellido",
    "Teléfono",
    "DNI",
    "Estado",
]

indices = {header: idx for idx, header in enumerate(headers)}

async def readLista(archivo='example/random.csv'):
    Postulantes = []
    lista = open(archivo, mode="r")
    reader = csv.reader(lista)
    for i in reader:
        if i[indices["Nombre"]] == "Nombre":
            pass
        else:
            Postulantes.append(i)
    return Postulantes

async def setLista(lista, archivo='example/random.csv'):
    with open(archivo, "w", newline='') as destino:
        writer = csv.writer(destino, delimiter=',', quotechar='"', quoting=csv.QUOTE_MINIMAL)
        writer.writerows(lista)

async def getPendientes(archivo='example/random.csv'):
    Pendientes  = []
    lista = open(archivo, mode="r")
    reader = csv.reader(lista)
    for i in reader:
        if i[indices["Estado"]] == 'Pendiente':
            Pendientes.append(i)
    return Pendientes

async def getAceptados(archivo='example/random.csv'):
    Aceptados  = []
    lista = open(archivo, mode="r")
    reader = csv.reader(lista)
    for i in reader:
        if i[indices["Estado"]] == 'Aceptado':
            Aceptados.append(i)
    return Aceptados

async def getRechazados(archivo='example/random.csv'):
    Rechazados  = []
    lista = open(archivo, mode="r")
    reader = csv.reader(lista)
    for i in reader:
        if i[indices["Estado"]] == 'Rechazado':
            Rechazados.append(i)
    return Rechazados

#randomLista('example/random_new.csv')

