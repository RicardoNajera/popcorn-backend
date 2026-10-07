@app.get("/api/buscar")
def buscar(
    q: str = Query(""),
    tipo: str = Query("Televisión")
):
    query = q.strip().lower()
    seccion = catalogo_global.get(tipo, {})
    if not seccion:
        return []

    resultados = []

    # Si es Televisión, el JSON trae llaves como subcategorías (ej. "⭐ ESPECIAL HALLOWEEN")
    if tipo == "Televisión":
        for subcat, canales in seccion.items():
            if isinstance(canales, list):
                for canal in canales:
                    titulo = str(canal.get("title", ""))
                    if not query or query in titulo.lower():
                        resultados.append({
                            "subcategoria": subcat,
                            "title": titulo,
                            "logo": canal.get("logo", ""),
                            "url": canal.get("url", "")
                        })
    # Si son Películas o Series, vienen planas directamente
    else:
        for item in seccion:
            titulo = str(item.get("title", ""))
            if not query or query in titulo.lower():
                resultados.append({
                    "subcategoria": tipo,
                    "title": titulo,
                    "logo": item.get("logo", ""),
                    "url": item.get("url", "")
                })

    return resultados[:200]
