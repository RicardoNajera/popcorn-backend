import os
import gc
import json
import boto3
import urllib.request
import urllib.error
import numpy as np
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

R2_ENDPOINT = os.getenv("R2_ENDPOINT")
R2_ACCESS_KEY = os.getenv("R2_ACCESS_KEY")
R2_SECRET_KEY = os.getenv("R2_SECRET_KEY")
R2_BUCKET = os.getenv("R2_BUCKET", "popcorn-cloud")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

catalogo_metadatos = []
matriz_vectores = None

def vectorizar_frase(texto: str):
    """Llama a Gemini. Si falla, retorna un TEXTO de error para mostrarlo en pantalla."""
    if not GEMINI_API_KEY:
        return "ERROR CRÍTICO: No agregaste la variable GEMINI_API_KEY en Render."
        
    url = f"https://generativelanguage.googleapis.com/v1beta/models/text-embedding-004:embedContent?key={GEMINI_API_KEY}"
    payload = json.dumps({
        "model": "models/text-embedding-004",
        "content": {
            "parts": [{"text": texto.strip()}]
        }
    }).encode("utf-8")
    
    try:
        req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode("utf-8"))
            valores = data.get("embedding", {}).get("values", [])
            if not valores:
                return "ERROR: Gemini respondió pero no entregó los números."
            vec = np.array(valores, dtype=np.float32)
            norm = np.linalg.norm(vec)
            return (vec / norm) if norm > 0 else vec
            
    except urllib.error.HTTPError as e:
        err_msg = e.read().decode("utf-8")
        return f"RECHAZO DE GEMINI (HTTP {e.code}): {err_msg}"
    except Exception as e:
        return f"ERROR INTERNO AL CONTACTAR GEMINI: {str(e)}"

@asynccontextmanager
async def lifespan(app: FastAPI):
    global catalogo_metadatos, matriz_vectores
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

        # Normalizar para garantizar matemática precisa
        normas = np.linalg.norm(matriz_vectores, axis=1, keepdims=True)
        normas[normas == 0] = 1.0
        matriz_vectores = matriz_vectores / normas

        if os.path.exists("/tmp/metadatos.json"): os.remove("/tmp/metadatos.json")
        if os.path.exists("/tmp/vectores.npz"): os.remove("/tmp/vectores.npz")
        gc.collect()
        print(f"✅ R2 listo: {len(catalogo_metadatos)} obras en memoria RAM.")
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

    # 1. Obtener los 768 números de tu frase
    v_query = vectorizar_frase(query)
    
    # 🚨 AQUÍ ESTÁ LA MAGIA DEL DEBUGGER VISUAL 🚨
    # Si la variable es un texto, significa que falló. Lo mandamos a la pantalla.
    if isinstance(v_query, str):
        return [{
            "title": v_query,
            "poster": "https://images.unsplash.com/photo-1594322436404-5a0526db4d13?w=300",
            "porcentaje": 0
        }]

    # 2. Si no falló, hace la multiplicación matemática contra las 24,000 películas
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
        pct = round(max(0.0, min(100.0, ((sim_val - min_sim) / rango) * 100)), 1)
        obra = dict(catalogo_metadatos[idx])
        obra["score_coseno"] = round(sim_val, 4)
        obra["porcentaje"] = pct
        resultados.append(obra)

    return resultados
