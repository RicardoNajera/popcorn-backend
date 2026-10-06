import os
import gc
import json
import re
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

def vectorizar_frase(texto: str):
    """Obtiene el embedding nativo de 768 dimensiones."""
    if not gemini_client:
        return "ERROR: Falta configurar GEMINI_API_KEY en Render."
        
    try:
        res = gemini_client.models.embed_content(
            model="gemini-embedding-001",
            contents=texto.strip(),
            config=types.EmbedContentConfig(
                task_type="RETRIEVAL_QUERY",
                output_dimensionality=768
            )
        )
        
        if hasattr(res, 'embeddings') and res.embeddings:
            valores = res.embeddings[0].values
        elif hasattr(res, 'embedding') and res.embedding:
            valores = res.embedding.values
        else:
            valores = res[0].values

        vec = np.array(valores, dtype=np.float32)
        if len(vec) > 768:
            vec = vec[:768]

        norm = np.linalg.norm(vec)
        return (vec / norm) if norm > 0 else vec
    except Exception as e:
        return f"ERROR GEMINI: {str(e)}"

@asynccontextmanager
async def lifespan(app: FastAPI):
    global catalogo_metadatos, matriz_vectores, gemini_client

    if GEMINI_API_KEY:
        try:
            gemini_client = genai.Client(api_key=GEMINI_API_KEY)
        except Exception as e:
            print(f"Error iniciando Gemini: {e}")

    print("⏳ Conectando con Cloudflare R2...")
    try:
        s3 = boto3.client(
            service_name="s3",
            endpoint_url=R2_ENDPOINT,
            aws_access_key_id=R2_ACCESS_KEY,
            aws_secret_access_key=R2_SECRET_KEY
        )

        s3.download_file(R2_BUCKET, "metadatos.json", "/tmp/metadatos.json")
        s3.download_file(R2_BUCKET, "vectores.npz", "/tmp/vectores.npz")

        with open("/tmp/metadatos.json", "r", encoding="utf-8") as f:
            catalogo_metadatos = json.load(f)

        with np.load("/tmp/vectores.npz") as loaded:
            matriz_vectores = loaded["vectors"].astype(np.float32)

        # Normalizar matriz en memoria
        normas = np.linalg.norm(matriz_vectores, axis=1, keepdims=True)
        normas[normas == 0] = 1.0
        matriz_vectores = matriz_vectores / normas

        if os.path.exists("/tmp/metadatos.json"): os.remove("/tmp/metadatos.json")
        if os.path.exists("/tmp/vectores.npz"): os.remove("/tmp/vectores.npz")
        gc.collect()
        print(f"✅ Catálogo listo: {len(catalogo_metadatos)} obras y matriz {matriz_vectores.shape} en RAM.")
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
    return {"status": "online", "matriz_lista": matriz_vectores is not None}

@app.get("/api/buscar")
def buscar_por_concepto(q: str = Query("")):
    query = q.strip()
    if not query or not catalogo_metadatos or matriz_vectores is None:
        return []

    # 1. Vectorizar la frase del usuario
    v_query = vectorizar_frase(query)
    
    if isinstance(v_query, str):
        return [{
            "title": v_query,
            "poster": "https://images.unsplash.com/photo-1594322436404-5a0526db4d13?w=300",
            "porcentaje": 0
        }]

    if len(v_query) != 768:
        v_query = v_query[:768]
        norm = np.linalg.norm(v_query)
        v_query = (v_query / norm) if norm > 0 else v_query

    # 2. Similitud Coseno Pura (Producto punto)
    similitudes = np.dot(matriz_vectores, v_query)

    # 3. Refuerzo Híbrido por palabras clave explícitas (ej. "evelyn", "momia")
    palabras_clave = [p.lower() for p in re.findall(r'\w+', query) if len(p) > 3]
    
    for idx, item in enumerate(catalogo_metadatos):
        titulo_lower = str(item.get("title", "")).lower()
        # Si el título contiene alguna palabra clave importante de la búsqueda, le damos un empujón matemático
        for palabra in palabras_clave:
            if palabra in titulo_lower:
                similitudes[idx] += 0.25 # Impulso de relevancia

    # 4. Obtener el Top 300 real ordenado
    top_300_indices = np.argsort(similitudes)[::-1][:300]
    if len(top_300_indices) == 0:
        return []

    resultados = []
    for idx in top_300_indices:
        sim_val = float(similitudes[idx])
        
        # Porcentaje real basado en el coseno (del 0% al 100% de afinidad geométrica real)
        # El coseno puro suele oscilar entre -0.1 y 0.85 en estos espacios vectoriales
        pct_real = round(max(0.0, min(100.0, ((sim_val + 0.1) / 0.95) * 100)), 1)

        obra = dict(catalogo_metadatos[idx])
        obra["score_coseno"] = round(sim_val, 4)
        obra["porcentaje"] = pct_real
        resultados.append(obra)

    return resultados
