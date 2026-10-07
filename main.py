import os
import gc
import json
import boto3
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

R2_ENDPOINT = os.getenv("R2_ENDPOINT")
R2_ACCESS_KEY = os.getenv("R2_ACCESS_KEY")
R2_SECRET_KEY = os.getenv("R2_SECRET_KEY")
R2_BUCKET = os.getenv("R2_BUCKET", "popcorn-cloud")

catalogo_global = {}

@asynccontextmanager
async def lifespan(app: FastAPI):
    global catalogo_global

    print("⏳ Conectando con Cloudflare R2 para descargar la lista maestra...")
    try:
        s3 = boto3.client(
            service_name="s3",
            endpoint_url=R2_ENDPOINT,
            aws_access_key_id=R2_ACCESS_KEY,
            aws_secret_access_key=R2_SECRET_KEY
        )

        s3.download_file(R2_BUCKET, "iptv_database_structured.json", "/tmp/iptv_database_structured.json")

        with open("/tmp/iptv_database_structured.json", "r", encoding="utf-8") as f:
            catalogo_global = json.load(f)

        if os.path.exists("/tmp/iptv_database_structured.json"):
            os.remove("/tmp/iptv_database_structured.json")
            
        gc.collect()
        print(f"✅ ¡Catálogo cargado en RAM exitosamente! Secciones: {list(catalogo_global.keys())}")
    except Exception as e:
        print(f"❌ Error al cargar el archivo desde R2: {e}")
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
    return {"status": "online", "categorias_disponibles": list(catalogo_global.keys())}

@app.get("/api/seccion")
def obtener_seccion(tipo: str = "Televisión"):
    print(f"📥 Petición de sección -> tipo: '{tipo}'")
    if not catalogo_global:
        return {}

    # Mapeo directo y seguro de llaves exactas para evitar bucles lentos
    tipo_limpio = tipo.strip().lower()
    seccion = None
    
    for k, v in catalogo_global.items():
        if k.strip().lower() == tipo_limpio:
            seccion = v
            break
            
    if not seccion:
        # Fallback a la primera sección disponible si no coincide exacto
        primera_key = list(catalogo_global.keys())[0]
        seccion = catalogo_global[primera_key]

    # Retorno directo sin procesamiento pesado al vuelo (el JSON ya viene estructurado de origen)
    return seccion if isinstance(seccion, dict) else {tipo: seccion}
