import os
import gc
import json
import boto3
import numpy as np
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from google import genai
from google.genai import types

R2_ENDPOINT = os.getenv("R2_ENDPOINT")
R2_ACCESS_KEY = os.getenv("R2_ACCESS_KEY")
R2_SECRET_KEY = os.getenv("R2_SECRET_KEY")
R2_BUCKET = os.getenv("R2_BUCKET", "popcorn-cloud")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

catalogo_metadatos = []
matriz_vectores = None
gemini_client = None

def obtener_vector_query(texto: str):
    if not gemini_client or not texto or not texto.strip():
        return None
    try:
        res = gemini_client.models.embed_content(
            model="text-embedding-004",
            contents=texto.strip(),
            config=types.EmbedContentConfig(task_type="RETRIEVAL_QUERY")
        )
        vec = np.array(res.embedding.values, dtype=np.float16)
        norm = np.linalg.norm(vec)
        return (vec / norm) if norm > 0 else vec
    except Exception as e:
        print(f"Error vectorizando query '{texto}': {e}")
        return None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global catalogo_metadatos, matriz_vectores, gemini_client

    if GEMINI_API_KEY:
        gemini_client = genai.Client(api_key=GEMINI_API_KEY)

    print("⏳ Conectando con Cloudflare R2...")
    try:
        s3 = boto3.client(
            service_name="s3",
            endpoint_url=R2_ENDPOINT,
            aws_access_key_id=R2_ACCESS_KEY,
            aws_secret_access_key=R2_SECRET_KEY
        )

        print("📥 Descargando metadatos.json y vectores.npz...")
        s3.download_file(R2_BUCKET, "metadatos.json", "/tmp/metadatos.json")
        s3.download_file(R2_BUCKET, "vectores.npz", "/tmp/vectores.npz")

        with open("/tmp/metadatos.json", "r", encoding="utf-8") as f:
            catalogo_metadatos = json.load(f)

        with np.load("/tmp/vectores.npz") as loaded:
            matriz_vectores = loaded["vectors"]

        if os.path.exists("/tmp/metadatos.json"):
            os.remove("/tmp/metadatos.json")
        if os.path.exists("/tmp/vectores.npz"):
            os.remove("/tmp/vectores.npz")

        gc.collect()
        print(f"✅ R2 listo: {len(catalogo_metadatos)} obras y matriz vectorial cargada en RAM.")
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
        "servicio": "Popcorn Vector Search Engine",
        "obras_disponibles": len(catalogo_metadatos)
    }

@app.get("/api/buscar")
def buscar_vectorial(q: str = Query("", description="Texto de búsqueda")):
    query = q.strip()
    if not query or not catalogo_metadatos:
        return []

    # 1. Si no hay vectores cargados, fallback por coincidencia de texto
    if matriz_vectores is None:
        coincidencias = [
            dict(item, porcentaje=100.0) 
            for item in catalogo_metadatos 
            if query.lower() in str(item.get("title", "")).lower()
        ]
        return coincidencias[:300]

    # 2. Vectorizar la consulta
    v_query = obtener_vector_query(query)
    if v_query is None:
        coincidencias = [
            dict(item, porcentaje=100.0) 
            for item in catalogo_metadatos 
            if query.lower() in str(item.get("title", "")).lower()
        ]
        return coincidencias[:300]

    # 3. Similitud coseno contra las 24,272 obras
    similitudes = np.dot(matriz_vectores.astype(np.float32), v_query.astype(np.float32))

    # Top 300
    top_indices = np.argsort(similitudes)[::-1][:300]
    if len(top_indices) == 0:
        return []

    max_sim = float(similitudes[top_indices[0]])
    min_sim = float(similitudes[top_indices[-1]])
    rango = max_sim - min_sim if max_sim > min_sim else 1.0

    resultados = []
    for idx in top_indices:
        sim_val = float(similitudes[idx])
        
        # Escala: El resultado #1 siempre es 100%, y va degradando hacia abajo según la distancia
        if max_sim > 0:
            porcentaje = round(max(0.0, min(100.0, ((sim_val - min_sim) / rango) * 100)), 1)
        else:
            porcentaje = 0.0

        obra = dict(catalogo_metadatos[idx])
        obra["similitud_raw"] = round(sim_val, 4)
        obra["porcentaje"] = porcentaje
        resultados.append(obra)

    return resultados
