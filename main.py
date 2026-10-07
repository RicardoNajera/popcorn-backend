from fastapi import FastAPI, Query

@app.get("/api/buscar")
def buscar(q: str = "", tipo: str = "Televisión"):
    print(f"📥 Petición recibida -> q: '{q}', tipo: '{tipo}'")
    
    # Si por alguna razón el catálogo global se quedó vacío, devolvemos un arreglo vacío en vez de fallar
    if not catalogo_global:
        print("⚠️ El catálogo global está vacío.")
        return []

    # Buscamos la sección de forma flexible
    tipo_limpio = tipo.strip().lower()
    seccion = None
    
    for k, v in catalogo_global.items():
        k_limpio = k.strip().lower()
        if k_limpio == tipo_limpio or tipo_limpio in k_limpio:
            seccion = v
            break
            
    # Si no encuentra coincidencia exacta, toma la primera sección disponible por defecto
    if not seccion and len(catalogo_global) > 0:
        primera_key = list(catalogo_global.keys())[0]
        seccion = catalogo_global[primera_key]

    resultados = []

    if isinstance(seccion, dict):
        for subcat, canales in seccion.items():
            if isinstance(canales, list):
                for canal in canales:
                    titulo = str(canal.get("title", ""))
                    if not q or q.lower() in titulo.lower():
                        resultados.append({
                            "subcategoria": subcat,
                            "title": titulo,
                            "logo": canal.get("logo", ""),
                            "url": canal.get("url", "")
                        })
    elif isinstance(seccion, list):
        for item in seccion:
            titulo = str(item.get("title", ""))
            if not q or q.lower() in titulo.lower():
                resultados.append({
                    "subcategoria": tipo,
                    "title": titulo,
                    "logo": item.get("logo", ""),
                    "url": item.get("url", "")
                })

    return resultados[:200]
