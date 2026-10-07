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

        # Nombre actualizado exactamente al que subiste a R2
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

    tipo_limpio = tipo.strip().lower()
    seccion = None
    
    for k, v in catalogo_global.items():
        k_limpio = k.strip().lower()
        if k_limpio == tipo_limpio or tipo_limpio in k:
            seccion = v
            break
            
    if not seccion and catalogo_global:
        primera_key = list(catalogo_global.keys())[0]
        seccion = catalogo_global[primera_key]

    resultado_normalizado = {}

    if isinstance(seccion, dict):
        primera_val = next(iter(seccion.values())) if seccion else None
        
        if isinstance(primera_val, list):
            for row_name, items in seccion.items():
                lista_limpia = []
                if isinstance(items, list):
                    for item in items:
                        if isinstance(item, dict):
                            lista_limpia.append({
                                "title": str(item.get("title", "")),
                                "logo": str(item.get("logo", "")),
                                "url": str(item.get("url", ""))
                            })
                if lista_limpia:
                    resultado_normalizado[str(row_name)] = lista_limpia
                    
        elif isinstance(primera_val, dict):
            for serie_name, temporadas in seccion.items():
                if isinstance(temporadas, dict):
                    for temp_name, eps in temporadas.items():
                        if isinstance(eps, list):
                            row_title = f"{serie_name} - {temp_name}"
                            lista_eps = []
                            for ep in eps:
                                if isinstance(ep, dict):
                                    lista_eps.append({
                                        "title": str(ep.get("title", "")),
                                        "logo": str(ep.get("logo", "")),
                                        "url": str(ep.get("url", ""))
                                    })
                            if lista_eps:
                                resultado_normalizado[row_title] = lista_eps
    elif isinstance(seccion, list):
        lista_limpia = []
        for item in seccion:
            if isinstance(item, dict):
                lista_limpia.append({
                    "title": str(item.get("title", "")),
                    "logo": str(item.get("logo", "")),
                    "url": str(item.get("url", ""))
                })
        if lista_limpia:
            resultado_normalizado[tipo] = lista_limpia

    return resultado_normalizado
