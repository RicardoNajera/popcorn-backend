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

# Declaramos la aplicación FastAPI antes de usar cualquier ruta con @app
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

@app.get("/api/buscar")
def buscar(
    q: str = Query(""),
    tipo: str = Query("Televisión")
):
    query = q.strip().lower()
    seccion = catalogo_global.get(tipo, {})
    if not seccion:
        return []

    resultados = []

    if tipo == "Televisión":
        for subcat, canales in seccion.items():
            if isinstance(canales, list):
                for canal in canales:
                    titulo = str(canal.get("title", ""))
                    if not query or query in titulo.lower():
                        resultados.append({
                            "subcategoria": subcat,
                            "title": titulo,
                            "logo": canal.get("logo", ""),
                            "url": canal.get("url", "")
                        })
    else:
        for item in seccion:
            titulo = str(item.get("title", ""))
            if not query or query in titulo.lower():
                resultados.append({
                    "subcategoria": tipo,
                    "title": titulo,
                    "logo": item.get("logo", ""),
                    "url": item.get("url", "")
                })

    return resultados[:200]
