import os
import json
import boto3
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

R2_ENDPOINT = os.getenv("R2_ENDPOINT")
R2_ACCESS_KEY = os.getenv("R2_ACCESS_KEY")
R2_SECRET_KEY = os.getenv("R2_SECRET_KEY")
R2_BUCKET = os.getenv("R2_BUCKET", "popcorn-cloud")

# Guardaremos únicamente el manifiesto ligero en la RAM (pesa unos cuantos bytes)
manifest_global = {}

@asynccontextmanager
async def lifespan(app: FastAPI):
    global manifest_global

    print("⏳ Conectando con Cloudflare R2 para descargar el índice maestro de bloques...")
    try:
        s3 = boto3.client(
            service_name="s3",
            endpoint_url=R2_ENDPOINT,
            aws_access_key_id=R2_ACCESS_KEY,
            aws_secret_access_key=R2_SECRET_KEY
        )

        # Descargamos el index_manifest.json generado por tu herramienta
        s3.download_file(R2_BUCKET, "M3U600/index_manifest.json", "/tmp/index_manifest.json")

        with open("/tmp/index_manifest.json", "r", encoding="utf-8") as f:
            manifest_global = json.load(f)

        if os.path.exists("/tmp/index_manifest.json"):
            os.remove("/tmp/index_manifest.json")
            
        print(f"✅ ¡Manifiesto de bloques cargado en RAM exitosamente! Secciones: {list(manifest_global.keys())}")
    except Exception as e:
        print(f"❌ Error al cargar el manifiesto desde R2: {e}")
    yield

app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def home():
    return {
        "status": "online",
        "arquitectura": "Bloques de 600 elementos (30x20)",
        "manifest": manifest_global
    }

@app.get("/api/bloque")
def obtener_bloque_json(tipo: str = "peliculas", pagina: int = 1):
    """
    Despacha el bloque exacto de 600 elementos pedido por el Roku.
    tipo: 'television', 'peliculas', o 'series'
    pagina: número de bloque (1, 2, 3...)
    """
    tipo_limpio = tipo.strip().lower()
    
    # Mapeo de carpetas en R2 dentro de M3U600
    carpeta_r2 = ""
    if "pelicul" in tipo_limpio:
        carpeta_r2 = "peliculas"
    elif "serie" in tipo_limpio:
        carpeta_r2 = "series"
    elif "television" in tipo_limpio or "tv" in tipo_limpio:
        carpeta_r2 = "television"
    else:
        return {"error": "Tipo de sección no válido"}

    file_path_r2 = f"M3U600/{carpeta_r2}/page_{pagina}.json"

    print(f"📥 Roku pidiendo bloque -> tipo: '{carpeta_r2}', página: {pagina}")

    try:
        s3 = boto3.client(
            service_name="s3",
            endpoint_url=R2_ENDPOINT,
            aws_access_key_id=R2_ACCESS_KEY,
            aws_secret_access_key=R2_SECRET_KEY
        )

        # Descargamos temporalmente el bloque de 600 elementos desde R2
        local_tmp = f"/tmp/page_{carpeta_r2}_{pagina}.json"
        s3.download_file(R2_BUCKET, file_path_r2, local_tmp)

        with open(local_tmp, "r", encoding="utf-8") as f:
            data_bloque = json.load(f)

        if os.path.exists(local_tmp):
            os.remove(local_tmp)

        return {
            "tipo": carpeta_r2,
            "pagina": pagina,
            "elementos": len(data_bloque),
            "data": data_bloque
        }

    except Exception as e:
        print(f"❌ Error al obtener el bloque {pagina} de {carpeta_r2}: {e}")
        return {"error": "Bloque no encontrado o fuera de rango", "detalles": str(e)}
