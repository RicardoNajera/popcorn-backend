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

    print("⏳ Conectando con Cloudflare R2 para descargar la lista...")
    try:
        s3 = boto3.client(
            service_name="s3",
            endpoint_url=R2_ENDPOINT,
            aws_access_key_id=R2_ACCESS_KEY,
            aws_secret_access_key=R2_SECRET_KEY
        )

        s3.download_file(R2_BUCKET, "lista_sin_subcategorias.json", "/tmp/lista_sin_subcategorias.json")

        with open("/tmp/lista_sin_subcategorias.json", "r", encoding="utf-8") as f:
            catalogo_global = json.load(f)

        if os.path.exists("/tmp/lista_sin_subcategorias.json"):
            os.remove("/tmp/lista_sin_subcategorias.json")
            
        gc.collect()
        print(f"✅ ¡Catálogo cargado en RAM exitosamente! Secciones: {list(catalogo_global.keys())}")
    except Exception as e:
        print(f"❌ Error al cargar el archivo desde R2: {e}")
    yield

# 1. Instanciación de FastAPI y su lifespan
app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 2. Definición de rutas
@app.get("/")
def home():
    return {"status": "online", "categorias_disponibles": list(catalogo_global.keys())}

@app.get("/api/seccion")
def obtener_seccion(tipo: str = "Televisión"):
    print(f"📥 Petición de sección completa -> tipo: '{tipo}'")
    if not catalogo_global:
        return {}

    tipo_limpio = tipo.strip().lower()
    for k, v in catalogo_global.items():
        k_limpio = k.strip().lower()
        if k_limpio == tipo_limpio or tipo_limpio in k_limpio:
            return v  # Devuelve la estructura jerárquica exacta de la sección

    # Por defecto si no coincide exacto, devuelve la primera sección disponible
    if catalogo_global:
        primera_key = list(catalogo_global.keys())[0]
        return catalogo_global[primera_key]
    return {}

@app.get("/api/buscar")
def buscar(q: str = "", tipo: str = "Televisión"):
    print(f"📥 Petición de búsqueda recibida -> q: '{q}', tipo: '{tipo}'")
    
    if not catalogo_global:
        print("⚠️ El catálogo global está vacío.")
        return []

    tipo_limpio = tipo.strip().lower()
    seccion = None
    
    for k, v in catalogo_global.items():
        k_limpio = k.strip().lower()
        if k_limpio == tipo_limpio or tipo_limpio in k_limpio:
            seccion = v
            break
            
    if not seccion and len(catalogo_global) > 0:
        primera_key = list(catalogo_global.keys())[0]
        seccion = catalogo_global[primera_key]

    resultados = []

    if isinstance(seccion, dict):
        for subcat, canales in seccion.items():
            if isinstance(canales, list):
                for canal in canales:
                    titulo = str(canal.get("title", ""))
                    if not q or q.lower() in titulo.lower():
                        resultados.append({
                            "subcategoria": subcat,
                            "title": titulo,
                            "logo": canal.get("logo", ""),
                            "url": canal.get("url", "")
                        })
    elif isinstance(seccion, list):
        for item in seccion:
            titulo = str(item.get("title", ""))
            if not q or q.lower() in titulo.lower():
                resultados.append({
                    "subcategoria": tipo,
                    "title": titulo,
                    "logo": item.get("logo", ""),
                    "url": item.get("url", "")
                })

    return resultados[:200]
