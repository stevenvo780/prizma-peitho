#!/usr/bin/env python3
"""
Publicador de Instagram para Prizma (ex Steven Vallejo).

Levanta un servidor HTTP temporal + ngrok para servir imágenes,
luego publica los 8 productos via Instagram Content Publishing API.

v2 — Mejoras:
  - Captions generados desde config.PRODUCTOS (fuente de verdad).
  - Descubrimiento dinámico de imágenes feed_1x1 (glob).
  - Imports centralizados desde config.py.
  - Logging estructurado.
  - Retry con backoff exponencial.
"""

import os
import sys
import glob
import json
import time
import requests
import subprocess
import threading
import http.server
import socketserver
from dotenv import load_dotenv

from config import (
    get_logger, GRAPH_API_BASE, PRODUCTOS, IMAGES_DIR,
    META_PAGE_TOKEN, META_INSTAGRAM_ID,
    MAX_IG_CONTAINER_RETRIES, IG_CONTAINER_POLL_INTERVAL,
    generar_caption_ig, retry,
)

load_dotenv()

logger = get_logger("publicar_instagram")

PAGE_TOKEN = META_PAGE_TOKEN or os.getenv("META_PAGE_TOKEN")
IG_ACCOUNT_ID = META_INSTAGRAM_ID or os.getenv("META_INSTAGRAM_ID")
HTTP_PORT = 8765


def descubrir_imagen_feed(producto_key: str) -> str | None:
    """
    Descubre dinámicamente la imagen feed_1x1 más reciente para un producto.
    Busca en IMAGES_DIR/<producto_key>/ archivos *feed_1x1*.png.
    """
    patron = os.path.join(str(IMAGES_DIR), producto_key, "*feed_1x1*.png")
    archivos = sorted(glob.glob(patron), reverse=True)

    if archivos:
        return os.path.relpath(archivos[0], str(IMAGES_DIR))

    # Fallback: cualquier imagen 1x1 en el directorio del producto
    patron_alt = os.path.join(str(IMAGES_DIR), producto_key, "*1x1*.png")
    archivos_alt = sorted(glob.glob(patron_alt), reverse=True)
    if archivos_alt:
        return os.path.relpath(archivos_alt[0], str(IMAGES_DIR))

    return None


def start_http_server():
    """Inicia un servidor HTTP sirviendo las imágenes."""
    abs_images = os.path.abspath(str(IMAGES_DIR))
    os.chdir(abs_images)
    handler = http.server.SimpleHTTPRequestHandler
    httpd = socketserver.TCPServer(("", HTTP_PORT), handler)
    httpd.serve_forever()


def get_ngrok_url():
    """Obtiene la URL pública de ngrok."""
    try:
        r = requests.get("http://localhost:4040/api/tunnels", timeout=5)
        tunnels = r.json().get("tunnels", [])
        for t in tunnels:
            if t.get("proto") == "https":
                return t["public_url"]
        if tunnels:
            return tunnels[0]["public_url"]
    except Exception:
        pass
    return None


@retry(max_attempts=2, base_delay=5.0, exceptions=(requests.RequestException,), logger_name="publicar_instagram")
def publicar_en_ig(caption: str, image_url: str) -> dict:
    """Publica una imagen en Instagram via Content Publishing API."""
    # Paso 1: Crear container
    r1 = requests.post(
        f"{GRAPH_API_BASE}/{IG_ACCOUNT_ID}/media",
        data={
            "image_url": image_url,
            "caption": caption,
            "access_token": PAGE_TOKEN,
        }
    )
    result1 = r1.json()
    if "id" not in result1:
        return {"error": f"Container error: {result1}"}

    container_id = result1["id"]
    logger.info("Container creado: %s", container_id)

    # Paso 2: Esperar que el container esté listo
    for attempt in range(MAX_IG_CONTAINER_RETRIES):
        sr = requests.get(
            f"{GRAPH_API_BASE}/{container_id}",
            params={"fields": "status_code", "access_token": PAGE_TOKEN}
        )
        status = sr.json().get("status_code", "")
        if status == "FINISHED":
            break
        elif status == "ERROR":
            return {"error": f"Container ERROR: {sr.json()}"}
        logger.debug("Container status: %s (intento %d/%d)", status, attempt + 1, MAX_IG_CONTAINER_RETRIES)
        time.sleep(IG_CONTAINER_POLL_INTERVAL)

    # Paso 3: Publicar
    r2 = requests.post(
        f"{GRAPH_API_BASE}/{IG_ACCOUNT_ID}/media_publish",
        data={
            "creation_id": container_id,
            "access_token": PAGE_TOKEN,
        }
    )
    result2 = r2.json()
    if "id" in result2:
        return {"success": True, "media_id": result2["id"]}
    else:
        return {"error": f"Publish error: {result2}"}


def main():
    logger.info("=" * 60)
    logger.info("PUBLICADOR DE INSTAGRAM - Prizma v2")
    logger.info("=" * 60)

    # Verificar credenciales
    if not PAGE_TOKEN or not IG_ACCOUNT_ID:
        logger.error("Faltan credenciales en .env (META_PAGE_TOKEN, META_INSTAGRAM_ID)")
        sys.exit(1)

    # Descubrir imágenes y generar captions desde PRODUCTOS (fuente de verdad)
    publicaciones = {}
    for key in PRODUCTOS:
        imagen_rel = descubrir_imagen_feed(key)
        if not imagen_rel:
            logger.warning("No se encontró imagen feed_1x1 para '%s' — saltando", key)
            continue
        caption = generar_caption_ig(key)
        if not caption:
            logger.warning("No se pudo generar caption para '%s' — saltando", key)
            continue
        publicaciones[key] = {"image": imagen_rel, "caption": caption}

    if not publicaciones:
        logger.error("No se encontraron imágenes para publicar")
        sys.exit(1)

    logger.info("Productos listos: %s", list(publicaciones.keys()))

    # Iniciar servidor HTTP en background
    logger.info("Iniciando servidor HTTP en puerto %d...", HTTP_PORT)
    server_thread = threading.Thread(target=start_http_server, daemon=True)
    server_thread.start()
    time.sleep(1)

    # Iniciar ngrok
    logger.info("Iniciando túnel ngrok...")
    ngrok_proc = subprocess.Popen(
        ["ngrok", "http", str(HTTP_PORT), "--log=stdout"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )
    time.sleep(4)

    ngrok_url = get_ngrok_url()
    if not ngrok_url:
        logger.error("No se pudo obtener URL de ngrok")
        ngrok_proc.terminate()
        sys.exit(1)

    logger.info("Ngrok URL: %s", ngrok_url)

    # Publicar cada producto
    results = {}
    for nombre, datos in publicaciones.items():
        image_public_url = f"{ngrok_url}/{datos['image']}"
        logger.info("─" * 50)
        logger.info("Publicando: %s", nombre.upper())

        result = publicar_en_ig(datos["caption"], image_public_url)

        if result.get("success"):
            logger.info("Publicado! Media ID: %s", result["media_id"])
            results[nombre] = result["media_id"]
        else:
            logger.error("Error en %s: %s", nombre, result.get("error", "desconocido"))
            results[nombre] = f"ERROR: {result.get('error', '')}"

        time.sleep(5)

    # Resumen
    logger.info("=" * 60)
    logger.info("RESUMEN DE PUBLICACIONES EN INSTAGRAM")
    exitosos = sum(1 for v in results.values() if not str(v).startswith("ERROR"))
    for nombre, media_id in results.items():
        st = "OK" if not str(media_id).startswith("ERROR") else "FAIL"
        logger.info("  %s %s: %s", st, nombre, media_id)
    logger.info("Total: %d/%d publicaciones exitosas", exitosos, len(publicaciones))

    # Guardar resultados
    results_path = os.path.join(str(IMAGES_DIR), "..", "instagram_results.json")
    with open(results_path, "w") as f:
        json.dump(results, f, indent=2)
    logger.info("Resultados guardados en: %s", results_path)

    ngrok_proc.terminate()
    logger.info("Ngrok cerrado. ¡Proceso completado!")


if __name__ == "__main__":
    main()
