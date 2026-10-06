import os
import gc
import json
import boto3
import urllib.request
import urllib.parse
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
    """Convierte la descripción o frase del usuario a un vector de 768 dimensiones usando la API REST directa."""
    if not GEMINI_API_KEY or not texto.strip():
        print("⚠️ No hay GEMINI_API_KEY o el texto está vacío.")
        return None

    url = f"https://generativelanguage.googleapis.com/v1beta/models/text-embedding-004:embedContent?key={GEMINI_API_KEY}"
    
    payload = json.dumps({
        "model": "models/text-embedding-004",
        "content": {
            "parts": [{"text": texto.strip()}]
        },
        "taskType": "RETRIEVAL_QUERY"
    }).encode("utf-8")

    try:
        req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=8) as response:
            data = json.loads(response.read().decode("utf-8"))
            valores = data.get("embedding", {}).get("values", [])
            if valores:
                vec = np.array(valores, dtype=np.float32)
                norm = np.linalg.norm(vec)
                return (vec / norm) if norm > 0 else vec
    except Exception as e:
        print(f"❌ Error al vectorizar frase con Google API: {e}")
        return None

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

        print("📥 Descargando metadatos.json y vectores.npz...")
        s3.download_file(R2_BUCKET, "metadatos.json", "/tmp/metadatos.json")
        s3.download_file(R2_BUCKET, "vectores.npz", "/tmp/vectores.npz")

        with open("/tmp/metadatos.json", "r", encoding="utf-8") as f:
            catalogo_metadatos = json.load(f)

        with np.load("/tmp/vectores.npz") as loaded:
            matriz_vectores = loaded["vectors"].astype(np.float32)

        # Normalizar matriz en memoria si no estuviera normalizada
        normas = np.linalg.norm(matriz_vectores, axis=1, keepdims=True)
        normas[normas == 0] = 1.0
        matriz_vectores = matriz_vectores / normas

        if os.path.exists("/tmp/metadatos.json"): os.remove("/tmp/metadatos.json")
        if os.path.exists("/tmp/vectores.npz"): os.remove("/tmp/vectores.npz")

        gc.collect()
        print(f"✅ R2 listo: {len(catalogo_metadatos)} obras y matriz {matriz_vectores.shape} cargada en RAM.")
    except Exception as e:
        print(f"❌ Error al iniciar R2: {e}")
    yield

app = FastAPI(lifespan=lifespan)

# CORS libre para conectar desde web, simulador o Smart TV
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
        "servicio": "Popcorn Semantic Vector Engine",
        "obras_en_ram": len(catalogo_metadatos),
        "matriz_cargada": matriz_vectores is not None
    }

@app.get("/api/buscar")
def buscar_por_concepto(q: str = Query("", description="Frase o descripción semántica")):
    query = q.strip()
    if not query or not catalogo_metadatos or matriz_vectores is None:
        return []

    print(f"🔍 Buscando concepto semántico: '{query}'")

    # 1. Obtener el vector de 768 números de la frase del usuario
    v_query = vectorizar_frase(query)
    if v_query is None:
        print("⚠️ No se pudo generar vector de consulta. Retornando vacío.")
        return []

    # 2. Producto punto contra las 24,272 obras (Similitud Coseno pura en C++)
    similitudes = np.dot(matriz_vectores, v_query)

    # 3. Extraer los 300 índices más cercanos
    top_300_indices = np.argsort(similitudes)[::-1][:300]
    if len(top_300_indices) == 0:
        return []

    # El resultado más cercano marca la referencia máxima
    max_sim = float(similitudes[top_300_indices[0]])
    min_sim = float(similitudes[top_300_indices[-1]])
    rango = (max_sim - min_sim) if max_sim > min_sim else 1.0

    resultados = []
    for idx in top_300_indices:
        sim_val = float(similitudes[idx])
        
        # Porcentaje relativo donde la #1 más cercana es 100% y de ahí degrada
        pct = round(max(0.0, min(100.0, ((sim_val - min_sim) / rango) * 100)), 1)

        obra = dict(catalogo_metadatos[idx])
        obra["score_coseno"] = round(sim_val, 4)
        obra["porcentaje"] = pct
        resultados.append(obra)

    print(f"🎯 Encontradas {len(resultados)} obras. Coincidencia #1: {resultados[0].get('title')} ({max_sim:.4f})")
    return resultados
