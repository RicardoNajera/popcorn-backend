import os
import json
import boto3
import numpy as np
from datetime import datetime
from fastapi import FastAPI, Query
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
ultimo_timestamp_curacion = None

def obtener_vector_texto(texto: str):
    if not gemini_client or not texto.strip():
        return None
    try:
        res = gemini_client.models.embed_content(
            model="text-embedding-004",
            contents=texto.strip(),
            config=types.EmbedContentConfig(task_type="RETRIEVAL_QUERY")
        )
        vec = np.array(res.embedding.values, dtype=np.float32)
        norm = np.linalg.norm(vec)
        return (vec / norm) if norm > 0 else vec
    except Exception as e:
        print(f"Error vectorizando: {e}")
        return None

def buscar_por_vector(vector_query, indices_disponibles, k=15):
    if vector_query is None or len(indices_disponibles) == 0:
        return []
    sub_vectores = matriz_vectores[indices_disponibles]
    similitudes = np.dot(sub_vectores, vector_query)
    ranking = np.argsort(similitudes)[::-1]
    mejores_pos = ranking[:k]
    return [indices_disponibles[p] for p in mejores_pos]

def consultar_tendencias_gemini(tipo: str):
    global gemini_client
    if not gemini_client:
        return None

    ahora = datetime.now()
    fecha_str = ahora.strftime("%d de %B de %Y")

    prompt_curaduria = f"""
    Eres el director de programación de una plataforma de streaming en México. Hoy es {fecha_str}.
    Analiza las tendencias actuales de consumo de medios, fechas destacadas y gustos de la audiencia mexicana.
    
    Genera exactamente 30 filas temáticas para la categoría '{tipo}'.
    Requisitos indispensables:
    1. Fila 1: Lo más relevante según el calendario, festividades o eventos del momento en México.
    2. Progresión para Películas/Series: Iniciar con géneros de alta demanda (terror, misterio o suspenso), transicionar por curiosidades, ciencia ficción, tecnología e historias de impacto, y concluir hacia temáticas más ligeras o familiares.
    3. Para Televisión: Priorizar deportes, señales en directo e informativas antes de pasar a entretenimiento general.
    
    Responde ÚNICAMENTE en formato JSON con la siguiente estructura (sin bloques markdown adicionales):
    [
      {{"titulo": "Título atractivo para la fila en pantalla", "query": "descripción semántica detallada para buscar coincidencias"}}
    ]
    """

    try:
        response = gemini_client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt_curaduria,
            config=types.GenerateContentConfig(
                response_mime_type="application/json"
            )
        )
        data = json.loads(response.text)
        if isinstance(data, list) and len(data) >= 10:
            return data
    except Exception as e:
        print(f"Error al consultar curaduría en tiempo real: {e}")
    return None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global catalogo_metadatos, matriz_vectores, gemini_client

    if GEMINI_API_KEY:
        gemini_client = genai.Client(api_key=GEMINI_API_KEY)

    print("⏳ Conectando a Cloudflare R2...")
    try:
        s3 = boto3.client(
            service_name="s3",
            endpoint_url=R2_ENDPOINT,
            aws_access_key_id=R2_ACCESS_KEY,
            aws_secret_access_key=R2_SECRET_KEY
        )
        print("📥 Descargando catálogo vectorizado desde R2...")
        obj = s3.get_object(Bucket=R2_BUCKET, Key="M3U Vectorizado.json")
        data = json.loads(obj["Body"].read().decode("utf-8"))

        vectores = []
        for item in data:
            catalogo_metadatos.append({
                "title": item.get("title", "Sin título"),
                "poster": item.get("poster", ""),
                "url": item.get("url", item.get("stream_url", "")),
                "tipo": item.get("tipo", "peliculas")
            })
            vectores.append(item.get("vector", []))

        matriz_vectores = np.array(vectores, dtype=np.float32)
        normas = np.linalg.norm(matriz_vectores, axis=1, keepdims=True)
        normas[normas == 0] = 1.0
        matriz_vectores /= normas
        print(f"✅ R2 listo: {len(catalogo_metadatos)} obras y vectores en memoria.")
    except Exception as e:
        print(f"❌ Error cargando R2: {e}")
    yield

app = FastAPI(lifespan=lifespan)

@app.get("/")
def home():
    return {
        "status": "online",
        "servicio": "Popcorn Smart TV Broker",
        "obras_disponibles": len(catalogo_metadatos)
    }

@app.get("/api/buscar")
def feed_ia_tendencias(
    tipo: str = Query("peliculas"),
    offset: int = Query(0, ge=0),
    limit: int = Query(30, ge=1, le=50)
):
    global cache_filas_curadas, ultimo_timestamp_curacion

    if not catalogo_metadatos or matriz_vectores is None or len(matriz_vectores) == 0:
        return []

    tipo_req = tipo.lower()
    indices_categoria = [
        idx for idx, obra in enumerate(catalogo_metadatos)
        if tipo_req in obra.get("tipo", "").lower()
    ]

    if not indices_categoria:
        indices_categoria = list(range(len(catalogo_metadatos)))

    ahora = datetime.now()
    debe_reconsultar = (
        tipo_req not in cache_filas_curadas or
        ultimo_timestamp_curacion is None or
        (ahora - ultimo_timestamp_curacion).total_seconds() > 3600
    )

    if debe_reconsultar:
        filas_dinamicas = consultar_tendencias_gemini(tipo_req)
        if filas_dinamicas:
            cache_filas_curadas[tipo_req] = filas_dinamicas
            ultimo_timestamp_curacion = ahora

    filas_a_procesar = cache_filas_curadas.get(tipo_req, [])

    if not filas_a_procesar:
        filas_a_procesar = [
            {"titulo": "Tendencias del Momento en México", "query": "lo más visto estrenos populares cine mexicano y streaming"},
            {"titulo": "Terror y Misterio Sobrenatural", "query": "películas de terror horror espíritus demonios suspenso miedo"},
            {"titulo": "Suspenso Psicológico y Tensión", "query": "thriller giros inesperados investigaciones oscuras crímenes"},
            {"titulo": "Curiosidades, Enigmas y lo Oculto", "query": "misterios sin resolver secretos teorías fenómenos extraños"},
            {"titulo": "Tecnología, Futuro e IA", "query": "ciencia ficción inteligencia artificial hackers robots distopías"},
            {"titulo": "Ciencia Ficción y Espacio Exterior", "query": "naves espaciales planetas desconocidos agujeros de gusano galaxias"},
            {"titulo": "Cine Ligero, Comedia y Familia", "query": "animación tierna aventuras humor risas historias optimistas"}
        ]

    filas_paginadas = filas_a_procesar[offset : offset + limit]

    respuesta_ui = []
    usados_globales = set()

    for fila in filas_paginadas:
        vector_fila = obtener_vector_texto(fila.get("query", fila.get("titulo", "")))
        
        disponibles = [idx for idx in indices_categoria if idx not in usados_globales]
        if len(disponibles) < 15:
            disponibles = indices_categoria

        mejores_indices = buscar_por_vector(vector_fila, disponibles, k=15)
        
        items_fila = []
        for idx in mejores_indices:
            usados_globales.add(idx)
            items_fila.append(catalogo_metadatos[idx])

        if len(items_fila) < 15:
            for idx in indices_categoria:
                if idx not in mejores_indices:
                    items_fila.append(catalogo_metadatos[idx])
                    if len(items_fila) == 15:
                        break

        respuesta_ui.append({
            "tituloFila": fila["titulo"],
            "items": items_fila
        })

    return respuesta_ui
