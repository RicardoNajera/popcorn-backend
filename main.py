import os
import gc
import json
import re
import boto3
import numpy as np
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
        print(f"✅ R2 listo: {len(catalogo_metadatos)} obras cargadas en RAM.")
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

def limpiar_texto(t: str) -> str:
    return re.sub(r'[^a-zA-Z0-9áéíóúÁÉÍÓÚñÑ ]', ' ', t.lower()).strip()

@app.get("/")
def home():
    return {
        "status": "online",
        "obras_disponibles": len(catalogo_metadatos)
    }

@app.get("/api/buscar")
def buscar(q: str = Query("", description="Texto de búsqueda")):
    query_raw = q.strip()
    if not query_raw or not catalogo_metadatos:
        return []

    q_clean = limpiar_texto(query_raw)
    palabras_query = [p for p in q_clean.split() if len(p) > 1]
    if not palabras_query:
        palabras_query = [q_clean]

    # Calcular puntaje matemático de similitud para cada una de las 24,272 obras
    scores = np.zeros(len(catalogo_metadatos), dtype=np.float32)

    for i, item in enumerate(catalogo_metadatos):
        titulo = limpiar_texto(str(item.get("title", "")))
        tipo = limpiar_texto(str(item.get("tipo", "")))
        
        texto_completo = f"{titulo} {tipo}"
        score = 0.0

        # Coincidencia de la frase completa
        if q_clean in texto_completo:
            score += 50.0

        # Coincidencias por palabra clave
        for p in palabras_query:
            if p in titulo.split():
                score += 15.0  # Palabra exacta
            elif p in titulo:
                score += 5.0   # Subcadena

        scores[i] = score

    # Ordenar los índices de mayor a menor similitud
    ranking = np.argsort(scores)[::-1][:300]

    max_score = float(scores[ranking[0]])
    
    # Si la búsqueda no tuvo ninguna coincidencia exacta, max_score será 0
    # En ese caso se toma un valor base para no dividir entre 0
    divisor = max_score if max_score > 0 else 1.0

    resultados = []
    for idx in ranking:
        sc = float(scores[idx])
        
        if max_score > 0:
            pct = round((sc / divisor) * 100, 1)
        else:
            pct = 0.0

        obra = dict(catalogo_metadatos[idx])
        obra["porcentaje"] = pct
        resultados.append(obra)

    return resultados
