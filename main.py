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

def vectorizar_frase(texto: str):
    """Convierte la frase del usuario a 768 números lidiando con los cambios de nombre de Google."""
    if not gemini_client:
        return "ERROR: La variable GEMINI_API_KEY no está configurada o es inválida."
        
    try:
        # Intento 1: Nombre original
        res = gemini_client.models.embed_content(
            model="text-embedding-004",
            contents=texto.strip(),
            config=types.EmbedContentConfig(task_type="RETRIEVAL_QUERY")
        )
        valores = res.embeddings[0].values
        vec = np.array(valores, dtype=np.float32)
        norm = np.linalg.norm(vec)
        return (vec / norm) if norm > 0 else vec
        
    except Exception as e:
        error_str = str(e)
        # Si Google nos da un 404, cambiamos de inmediato al nombre moderno
        if "404" in error_str or "not found" in error_str.lower():
            try:
                res = gemini_client.models.embed_content(
                    model="gemini-embedding-001",
                    contents=texto.strip(),
                    config=types.EmbedContentConfig(task_type="RETRIEVAL_QUERY")
                )
                valores = res.embeddings[0].values
                vec = np.array(valores, dtype=np.float32)
                norm = np.linalg.norm(vec)
                return (vec / norm) if norm > 0 else vec
            except Exception as e2:
                return f"ERROR CRÍTICO (Gemini rechazó ambos modelos): {str(e2)}"
        return f"ERROR GEMINI: {error_str}"

@asynccontextmanager
async def lifespan(app: FastAPI):
    global catalogo_metadatos, matriz_vectores, gemini_client

    if GEMINI_API_KEY:
        try:
            gemini_client = genai.Client(api_key=GEMINI_API_KEY)
        except Exception as e:
            print(f"Error iniciando cliente Gemini: {e}")

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

        # Garantizar matemática precisa (Módulo 1)
        normas = np.linalg.norm(matriz_vectores, axis=1, keepdims=True)
        normas[normas == 0] = 1.0
        matriz_vectores = matriz_vectores / normas

        if os.path.exists("/tmp/metadatos.json"): os.remove("/tmp/metadatos.json")
        if os.path.exists("/tmp/vectores.npz"): os.remove("/tmp/vectores.npz")
        gc.collect()
        print(f"✅ Catálogo listo: {len(catalogo_metadatos)} obras y matriz vectorial en RAM.")
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

    # 1. Convierte el concepto a 768 números
    v_query = vectorizar_frase(query)
    
    # 🚨 Chivato Visual de Errores 🚨
    if isinstance(v_query, str):
        return [{
            "title": v_query,
            "poster": "https://images.unsplash.com/photo-1594322436404-5a0526db4d13?w=300",
            "porcentaje": 0
        }]

    # 2. Búsqueda instantánea en RAM (El milagro matemático de 0.05 segundos)
    similitudes = np.dot(matriz_vectores, v_query)
    
    # 3. Trae el Top 300
    top_300_indices = np.argsort(similitudes)[::-1][:300]
    if len(top_300_indices) == 0:
        return []

    max_sim = float(similitudes[top_300_indices[0]])
    min_sim = float(similitudes[top_300_indices[-1]])
    rango = (max_sim - min_sim) if max_sim > min_sim else 1.0

    resultados = []
    for idx in top_300_indices:
        sim_val = float(similitudes[idx])
        # Escala: 100% la más precisa, hacia abajo el resto
        pct = round(max(0.0, min(100.0, ((sim_val - min_sim) / rango) * 100)), 1)
        
        obra = dict(catalogo_metadatos[idx])
        obra["score_coseno"] = round(sim_val, 4)
        obra["porcentaje"] = pct
        resultados.append(obra)

    return resultados
