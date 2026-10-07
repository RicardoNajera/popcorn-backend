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

def vectorizar_texto_seguro(texto: str):
    if not gemini_client or not texto.strip():
        return None
    try:
        res = gemini_client.models.embed_content(
            model="gemini-embedding-001",
            contents=texto.strip(),
            config=types.EmbedContentConfig(
                task_type="RETRIEVAL_QUERY",
                output_dimensionality=768
            )
        )
        valores = res.embeddings[0].values
        vec = np.array(valores, dtype=np.float32)
        if len(vec) > 768:
            vec = vec[:768]
        norm = np.linalg.norm(vec)
        return (vec / norm) if norm > 0 else vec
    except Exception as e:
        print(f"Aviso al vectorizar '{texto}': {e}")
        return None

def obtener_titulo_exacto_con_gemini(query: str):
    """Pide a Gemini UNA SOLA película o serie más precisa posible."""
    if not gemini_client:
        return query, "Gemini no inicializado"
    try:
        prompt = (
            f"El usuario busca: '{query}'. "
            "Piensa cuál es la película, serie o programa exacto al que se refiere. "
            "Responde ÚNICAMENTE con el título oficial de esa obra (en su idioma original o el más conocido), "
            "sin explicaciones, sin listas, sin comas extras y sin texto adicional."
        )
        response = gemini_client.models.generate_content(
            model="gemini-3.5-flash",
            contents=prompt,
        )
        titulo_sugerido = response.text.strip().replace('"', '').replace("'", "")
        return titulo_sugerido, titulo_sugerido
    except Exception as e:
        return query, f"Error Gemini: {str(e)}"

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
def buscar(q: str = Query("")):
    query = q.strip()
    if not query or not catalogo_metadatos or matriz_vectores is None:
        return {"gemini_debug": "Catálogo no listo o query vacía", "titulos_interpretados": [], "resultados": []}

    # 1. Gemini nos da UN SOLO título exacto
    titulo_exacto, debug_gemini = obtener_titulo_exacto_con_gemini(query)

    # 2. Vectorizar ese único título exacto
    similitudes_totales = np.zeros(len(catalogo_metadatos), dtype=np.float32)
    v_query = vectorizar_texto_seguro(titulo_exacto)
    
    if v_query is not None:
        similitudes_totales = np.dot(matriz_vectores, v_query)
    
    # Si por alguna razón falló el vector, usamos el query original
    if np.max(similitudes_totales) == 0:
        v_original = vectorizar_texto_seguro(query)
        if v_original is not None:
            similitudes_totales = np.dot(matriz_vectores, v_original)

    # 3. Impulso extra para nombres directos de la búsqueda
    palabras_query = [p.lower() for p in re.findall(r'\w+', query) if len(p) > 2]
    for idx, item in enumerate(catalogo_metadatos):
        titulo_lower = str(item.get("title", "")).lower()
        for palabra in palabras_query:
            if palabra in titulo_lower:
                similitudes_totales[idx] += 0.35

    # 4. Obtener EXACTAMENTE los mejores 10 resultados
    top_10_indices = np.argsort(similitudes_totales)[::-1][:10]
    if len(top_10_indices) == 0:
        return {"gemini_debug": debug_gemini, "titulos_interpretados": [titulo_exacto], "resultados": []}

    max_score = float(similitudes_totales[top_10_indices[0]])
    min_score = float(similitudes_totales[top_10_indices[-1]])
    rango = (max_score - min_score) if max_score > min_score else 1.0

    resultados = []
    for idx in top_10_indices:
        sim_val = float(similitudes_totales[idx])
        
        if max_score > 0:
            pct = round(max(0.0, min(100.0, ((sim_val - min_score) / rango) * 100 if rango > 0 else 100.0)), 1)
            if sim_val == max_score:
                pct = 100.0
        else:
            pct = 0.0

        obra = dict(catalogo_metadatos[idx])
        obra["score_coseno"] = round(sim_val, 4)
        obra["porcentaje"] = pct
        resultados.append(obra)

    return {
        "gemini_debug": debug_gemini,
        "titulos_interpretados": [titulo_exacto],
        "resultados": resultados
    }
