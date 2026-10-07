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

# Aquí vivirá toda tu estructura JSON (Televisión, Películas, Series) en RAM
catalogo_global = {}

@asynccontextmanager
async def lifespan(app: FastAPI):
    global catalogo_global

    print("⏳ Conectando con Cloudflare R2 para descargar la lista...")
    try:
        s3 = boto3.client(
            service_name="s3",
            endpoint_url=R2_ENDPOINT,
            aws_access_key_id=R2_ACCESS_KEY,
            aws_secret_access_key=R2_SECRET_KEY
        )

        # Descargamos tu archivo JSON estructurado desde R2
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

@app.get("/api/catalogo")
def obtener_catalogo():
    """Devuelve todo el JSON estructurado para que la app lo navegue de forma local o por secciones."""
    return catalogo_global

@app.get("/api/buscar")
def buscar(
    q: str = Query(""),
    tipo: str = Query("Televisión")
):
    """
    Busca de forma instantánea y ligera dentro de la categoría seleccionada (Televisión, Películas o Series).
    """
    query = q.strip().lower()
    
    # Seleccionamos la categoría principal del JSON
    seccion = catalogo_global.get(tipo, {})
    if not seccion:
        return []

    resultados = []

    # Si es Televisión (viene por subcategorías/carpetas)
    if tipo == "Televisión":
        for subcategoria, canales in seccion.items():
            for canal in canales:
                if not query or query in canal.get("title", "").lower():
                    resultados.append({
                        "subcategoria": subcategoria,
                        "title": canal.get("title"),
                        "logo": canal.get("logo"),
                        "url": canal.get("url")
                    })
    
    # Si son Películas o Series (vienen agrupadas por nombre)
    else:
        for nombre, contenido in seccion.items():
            if not query or query in nombre.lower():
                resultados.append({
                    "nombre": nombre,
                    "contenido": contenido
                })

    # Limitamos para que la tele no procese de más de golpe
    return resultados[:100]
