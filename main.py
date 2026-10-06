import os
import gc
import json
import boto3
import numpy as np
from datetime import datetime
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

cache_filas_curadas = {}
ultimo_timestamp_curacion = {}

def obtener_vector_texto(texto: str):
    if not gemini_client or not texto.strip():
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
        print(f"Error vectorizando texto '{texto}': {e}")
        return None

def buscar_por_vector(vector_query, indices_disponibles, k=15):
    if vector_query is None or len(indices_disponibles) == 0:
        return []
    sub_vectores = matriz_vectores[indices_disponibles]
    similitudes = np.dot(sub_vectores.astype(np.float32), vector_query.astype(np.float32))
    ranking = np.argsort(similitudes)[::-1]
    return [indices_disponibles[p] for p in ranking[:k]]

def consultar_tendencias_gemini(tipo: str):
    if not gemini_client:
        return None
    fecha_str = datetime.now().strftime("%d de %B de %Y")
    prompt = f"""
    Eres el director de programación de una plataforma de streaming premium en México. Hoy es {fecha_str}.
    Genera exactamente 20 filas temáticas muy atractivas y diversas para la categoría '{tipo}'.
    Responde ÚNICAMENTE con un JSON válido en este formato exacto:
    [{{"titulo": "Título atractivo de la fila", "query": "conceptos clave y temática de búsqueda"}}]
    """
    try:
        res = gemini_client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
            config=types.GenerateContentConfig(response_mime_type="application/json")
        )
        data = json.loads(res.text)
        if isinstance(data, list) and len(data) >= 5:
            return data
    except Exception as e:
        print(f"Error consultando tendencias en Gemini: {e}")
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

        # Limpieza de temporales en disco
        if os.path.exists("/tmp/metadatos.json"): os.remove("/tmp/metadatos.json")
        if os.path.exists("/tmp/vectores.npz"): os.remove("/tmp/vectores.npz")

        gc.collect()
        print(f"✅ R2 listo en RAM: {len(catalogo_metadatos)} obras y vectores cargados.")
    except Exception as e:
        print(f"❌ Error al iniciar R2: {e}")
    yield

app = FastAPI(lifespan=lifespan)

# CORS TOTAL: Permite peticiones sin bloqueo desde cualquier navegador o dispositivo
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
        "servicio": "Popcorn Smart TV Broker",
        "obras_disponibles": len(catalogo_metadatos)
    }

@app.get("/api/buscar")
def feed_ia(
    tipo: str = Query("peliculas"),
    offset: int = Query(0, ge=0),
    limit: int = Query(15, ge=1, le=50)
):
    if not catalogo_metadatos or matriz_vectores is None:
        return []

    # Normalizar parámetro de categoría
    tipo_solicitado = tipo.lower()
    if "pelicula" in tipo_solicitado:
        cat_filtro = "pelicula"
    elif "serie" in tipo_solicitado:
        cat_filtro = "series"
    elif "tv" in tipo_solicitado or "vivo" in tipo_solicitado:
        cat_filtro = "tv"
    else:
        cat_filtro = tipo_solicitado

    indices_categoria = [
        i for i, item in enumerate(catalogo_metadatos)
        if cat_filtro in item.get("tipo", "").lower()
    ]
    if not indices_categoria:
        indices_categoria = list(range(len(catalogo_metadatos)))

    ahora = datetime.now()
    ultimo_tiempo = ultimo_timestamp_curacion.get(cat_filtro)
    
    # Caché de 1 hora por categoría
    if (cat_filtro not in cache_filas_curadas) or (ultimo_tiempo is None) or ((ahora - ultimo_tiempo).total_seconds() > 3600):
        filas_dinamicas = consultar_tendencias_gemini(cat_filtro)
        if filas_dinamicas:
            cache_filas_curadas[cat_filtro] = filas_dinamicas
            ultimo_timestamp_curacion[cat_filtro] = ahora

    filas_a_procesar = cache_filas_curadas.get(cat_filtro, [
        {"titulo": "Tendencias del Momento", "query": "estrenos populares aclamadas"},
        {"titulo": "Acción y Adrenalina", "query": "acción persecuciones combate adrenalina"},
        {"titulo": "Terror y Misterio", "query": "terror horror suspenso paranormal miedo"},
        {"titulo": "Comedia y Humor", "query": "comedia risas diversión sátira"},
        {"titulo": "Ciencia Ficción y Fantasía", "query": "espacio futuro tecnología magia"}
    ])

    sub_filas = filas_a_procesar[offset : offset + limit]
    resultado = []
    usados = set()

    for f in sub_filas:
        query_texto = f.get("query", f.get("titulo", ""))
        vector_query = obtener_vector_texto(query_texto)
        disp = [i for i in indices_categoria if i not in usados] or indices_categoria
        
        idxs = buscar_por_vector(vector_query, disp, k=20)
        
        items = []
        for i in idxs:
            usados.add(i)
            items.append(catalogo_metadatos[i])

        resultado.append({
            "tituloFila": f["titulo"],
            "items": items
        })

    return resultado
