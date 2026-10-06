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

catalogo_metadatos = []

@asynccontextmanager
async def lifespan(app: FastAPI):
    global catalogo_metadatos

    print("⏳ Conectando con Cloudflare R2...")
    try:
        s3 = boto3.client(
            service_name="s3",
            endpoint_url=R2_ENDPOINT,
            aws_access_key_id=R2_ACCESS_KEY,
            aws_secret_access_key=R2_SECRET_KEY
        )

        print("📥 Descargando metadatos.json...")
        s3.download_file(R2_BUCKET, "metadatos.json", "/tmp/metadatos.json")

        with open("/tmp/metadatos.json", "r", encoding="utf-8") as f:
            catalogo_metadatos = json.load(f)

        if os.path.exists("/tmp/metadatos.json"):
            os.remove("/tmp/metadatos.json")

        gc.collect()
        print(f"✅ R2 listo: {len(catalogo_metadatos)} obras cargadas en memoria.")
    except Exception as e:
        print(f"❌ Error al iniciar R2: {e}")
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
        "servicio": "Popcorn Direct Engine",
        "obras_disponibles": len(catalogo_metadatos)
    }

@app.get("/api/buscar")
def feed_directo(tipo: str = Query("peliculas")):
    if not catalogo_metadatos:
        return []

    # 1. Separar por categorías base
    canales_tv = [item for item in catalogo_metadatos if "tv" in str(item.get("tipo", "")).lower()]
    peliculas = [item for item in catalogo_metadatos if "pelicula" in str(item.get("tipo", "")).lower()]
    series = [item for item in catalogo_metadatos if "serie" in str(item.get("tipo", "")).lower()]

    if not canales_tv:
        canales_tv = catalogo_metadatos[:100]
    if not peliculas:
        peliculas = catalogo_metadatos[100:500]
    if not series:
        series = catalogo_metadatos[500:900]

    # Fila 1: Canales familiares de México
    palabras_mx = ["mexico", "azteca", "estrellas", "canal 5", "canal 7", "adn", "imagen", "distrito", "las estrellas", "tlnovelas", "cinema"]
    tv_mx = [c for c in canales_tv if any(p in str(c.get("title", "")).lower() for p in palabras_mx)]
    for c in canales_tv:
        if len(tv_mx) >= 30:
            break
        if c not in tv_mx:
            tv_mx.append(c)
    fila_tv = tv_mx[:30]

    # Fila 2: Películas de Terror
    palabras_terror = ["terror", "miedo", "exorcista", "demonio", "paranormal", "conjuro", "annabelle", "saw", "silent hill", "noche", "siniestro", "insidious", "muertos", "zombie", "evil"]
    pelis_terror = [p for p in peliculas if any(t in str(p.get("title", "")).lower() for t in palabras_terror)]
    for p in peliculas:
        if len(pelis_terror) >= 30:
            break
        if p not in pelis_terror:
            pelis_terror.append(p)
    fila_terror = pelis_terror[:30]

    # Fila 3: Series más populares y actuales
    series_populares = sorted(series, key=lambda s: str(s.get("ano", "")), reverse=True)[:30]
    if len(series_populares) < 30:
        for s in series:
            if len(series_populares) >= 30:
                break
            if s not in series_populares:
                series_populares.append(s)

    return [
        {
            "tituloFila": "Canales de México Más Vistos en Familia",
            "items": fila_tv
        },
        {
            "tituloFila": "30 Películas de Terror Para No Ver Solo",
            "items": fila_terror
        },
        {
            "tituloFila": "Series Más Populares del Momento",
            "items": series_populares
        }
    ]
