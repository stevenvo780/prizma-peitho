#!/usr/bin/env python3
"""
campana_auto.py — Modo FULL PASS autónomo.

Ejecuta el pipeline completo sin intervención humana:
  1. Genera imágenes para todos (o los indicados) productos
  2. Evalúa con IA Critic
  3. Regenera las rechazadas hasta 3 rondas
  4. Publica en Facebook + Instagram todo lo aprobado

Uso:
  python3 run.py auto                          # todos los productos, config default
  python3 run.py auto --productos emw graf      # solo EMW y Graf
  python3 run.py auto --formatos feed_1x1       # solo feed cuadrado
  python3 run.py auto --dry-run                 # sin publicar
  python3 run.py auto --max-rondas 5            # 5 rondas de regeneración
  python3 run.py auto --skip-ig                 # solo Facebook
"""

import os
import sys
import json
import time
import shutil
import subprocess
import threading
import http.server
import socketserver
from datetime import datetime
from pathlib import Path

import requests

from config import (
    get_logger, PRODUCTOS, PRODUCTOS_ACTIVOS, IMAGES_DIR,
    CAMPAIGNS_DIR, OUTPUT_DIR, generar_caption_ig, build_utm_url,
    GRAPH_API_BASE, META_PAGE_TOKEN, META_INSTAGRAM_ID,
    MAX_IG_CONTAINER_RETRIES, IG_CONTAINER_POLL_INTERVAL,
)
from core.image_generator import ImageGenerator
from core.image_critic import ImageCritic
from social.publisher import MetaAdsManager

logger = get_logger("campana_auto")

# ------------------------------------------------------------------ #
#  COLORES
# ------------------------------------------------------------------ #

C = {
    "R": "\033[0m", "B": "\033[1m", "D": "\033[2m",
    "r": "\033[91m", "g": "\033[92m", "y": "\033[93m",
    "b": "\033[94m", "m": "\033[95m", "c": "\033[96m",
}


def _c(txt: str, color: str) -> str:
    return f"{C.get(color, '')}{txt}{C['R']}"


def _bar(titulo: str, step: int, total: int = 4):
    prog = "█" * step + "░" * (total - step)
    print(f"\n{'=' * 70}")
    print(f"  STEP {step}/{total}  [{prog}]  {titulo}")
    print(f"{'=' * 70}\n")


# ------------------------------------------------------------------ #
#  DEFAULTS
# ------------------------------------------------------------------ #

DEFAULT_FORMATOS = ["feed_1x1", "story_9x16", "banner_16x9", "promo_1x1"]
DEFAULT_MODELO = "gemini-3-pro-image-preview"
DEFAULT_UMBRAL = 70
DEFAULT_MAX_RONDAS = 3
DEFAULT_TEMATICA = "Campaña de marca — presencia digital y posicionamiento"


# ------------------------------------------------------------------ #
#  STEP 1 — GENERAR
# ------------------------------------------------------------------ #

def _step_generar(productos: list[str], formatos: list[str],
                  modelo: str, tematica: str, nombre: str) -> dict:
    """Genera imágenes para todos los productos."""
    _bar("GENERAR IMÁGENES", 1)

    total = len(productos) * len(formatos)
    print(f"  Productos: {_c(', '.join(productos), 'c')}")
    print(f"  Formatos:  {_c(', '.join(formatos), 'c')}")
    print(f"  Modelo:    {_c(modelo, 'y')}")
    print(f"  Total:     {_c(str(total), 'B')} imágenes")
    print()

    gen = ImageGenerator(model=modelo)

    campana_meta = gen.generar_campana(
        nombre_campana=nombre,
        productos=productos,
        tematica=tematica,
        formatos=formatos,
    )

    generadas = sum(len(v) for v in campana_meta.get("imagenes", {}).values())
    carpeta = campana_meta.get("carpeta", "")

    print(f"\n  {_c('✓', 'g')} {generadas}/{total} imágenes generadas")
    print(f"    Carpeta: {_c(carpeta, 'D')}")

    return {
        "nombre": nombre,
        "tematica": tematica,
        "productos": productos,
        "formatos": formatos,
        "modelo": modelo,
        "campana_meta": campana_meta,
        "carpeta": carpeta,
        "total_esperado": total,
    }


# ------------------------------------------------------------------ #
#  STEP 2 — EVALUAR + REGENERAR (hasta N rondas)
# ------------------------------------------------------------------ #

def _step_evaluar_y_regenerar(config: dict, umbral: int,
                              max_rondas: int, modelo: str) -> dict:
    """Evalúa imágenes y regenera las rechazadas hasta max_rondas veces."""
    _bar("EVALUAR + REGENERAR AUTOMÁTICO", 2)

    campana_meta = config["campana_meta"]
    carpeta = config["carpeta"]

    # Recopilar imágenes
    imagenes = []
    for prod_key, imgs in campana_meta.get("imagenes", {}).items():
        for img_info in imgs:
            ruta = img_info.get("path", "")
            fmt = img_info.get("formato", "")
            if ruta and os.path.exists(ruta):
                imagenes.append({
                    "ruta": ruta,
                    "producto": prod_key,
                    "formato": fmt,
                    "archivo": os.path.basename(ruta),
                })

    if not imagenes:
        print(f"  {_c('⚠', 'y')} No hay imágenes para evaluar.")
        config["aprobadas"] = []
        config["rechazadas_finales"] = []
        return config

    print(f"  Imágenes a evaluar: {_c(str(len(imagenes)), 'B')}")
    print(f"  Umbral: {_c(str(umbral), 'y')}/100")
    print(f"  Rondas de regeneración: máx {_c(str(max_rondas), 'y')}")
    print()

    gen = ImageGenerator(model=modelo)
    critic = ImageCritic(umbral=umbral, max_intentos=0)

    aprobadas = []
    pendientes = list(imagenes)

    for ronda in range(1, max_rondas + 1):
        if not pendientes:
            break

        print(f"  {'─' * 60}")
        print(f"  {_c(f'RONDA {ronda}/{max_rondas}', 'B')} — {len(pendientes)} imágenes pendientes")
        print()

        rechazadas_ronda = []

        for i, img in enumerate(pendientes, 1):
            nombre_prod = PRODUCTOS[img["producto"]]["nombre"]
            label = f"  [{i}/{len(pendientes)}] {nombre_prod} / {img['formato']}"
            print(f"{label}...", end=" ", flush=True)

            resultado = critic.evaluar_imagen(
                img["ruta"], img["producto"], img["formato"]
            )

            puntaje = resultado.get("puntaje_total", 0)
            veredicto = resultado.get("veredicto", "ERROR")

            if veredicto == "APROBADA":
                print(_c(f"✅ {puntaje}/100", "g"))
                aprobadas.append({
                    **img,
                    "puntaje": puntaje,
                    "estado": "aprobada",
                    "ronda": ronda,
                })
            else:
                defectos = resultado.get("defectos_criticos", [])
                motivo = defectos[0][:50] if defectos else "bajo puntaje"
                print(_c(f"❌ {puntaje}/100 — {motivo}", "r"))

                rechazadas_ronda.append({
                    **img,
                    "puntaje": puntaje,
                    "feedback": resultado.get("feedback_regeneracion", ""),
                    "defectos": defectos,
                })

        if not rechazadas_ronda:
            print(f"\n  {_c('✓', 'g')} Todas aprobadas en ronda {ronda}!")
            break

        # ¿Hay más rondas?
        if ronda >= max_rondas:
            print(f"\n  {_c('⚠', 'y')} Ronda final alcanzada. "
                  f"{len(rechazadas_ronda)} imágenes siguen rechazadas.")
            # Las que quedan rechazadas las aprobamos con score bajo
            # (el usuario pidió full pass autónomo)
            for img in rechazadas_ronda:
                aprobadas.append({
                    **img,
                    "estado": "aprobada_forzada",
                    "ronda": ronda,
                })
            break

        # Regenerar las rechazadas
        print(f"\n  {_c('🔄', 'b')} Regenerando {len(rechazadas_ronda)} imágenes...")
        nuevas_pendientes = []

        for img in rechazadas_ronda:
            nombre_prod = PRODUCTOS[img["producto"]]["nombre"]
            print(f"    🎨 {nombre_prod} / {img['formato']}...", end=" ", flush=True)

            prod_dir = os.path.join(carpeta, img["producto"])
            os.makedirs(prod_dir, exist_ok=True)

            try:
                nueva_ruta = gen._generar_formato_campana(
                    img["producto"], img["formato"],
                    config.get("tematica", ""), prod_dir
                )
                if nueva_ruta:
                    print(_c("OK", "g"))
                    nuevas_pendientes.append({
                        "ruta": nueva_ruta,
                        "producto": img["producto"],
                        "formato": img["formato"],
                        "archivo": os.path.basename(nueva_ruta),
                    })
                else:
                    print(_c("falló", "r"))
                    # Mantener la original
                    aprobadas.append({
                        **img,
                        "estado": "aprobada_forzada",
                        "ronda": ronda,
                    })
            except Exception as e:
                print(_c(f"error: {e}", "r"))
                aprobadas.append({
                    **img,
                    "estado": "aprobada_forzada",
                    "ronda": ronda,
                })

        pendientes = nuevas_pendientes

    # Resumen
    n_ok = sum(1 for a in aprobadas if a["estado"] == "aprobada")
    n_forzadas = sum(1 for a in aprobadas if a["estado"] == "aprobada_forzada")

    print(f"\n  {'─' * 60}")
    print(f"  {_c('RESUMEN EVALUACIÓN', 'B')}")
    print(f"    ✅ Aprobadas IA:       {_c(str(n_ok), 'g')}")
    print(f"    ⚠  Aprobadas forzadas: {_c(str(n_forzadas), 'y')}")
    print(f"    📊 Total listas:       {_c(str(len(aprobadas)), 'B')}")

    if aprobadas:
        prom = sum(a.get("puntaje", 0) for a in aprobadas) / len(aprobadas)
        print(f"    📈 Promedio:           {_c(f'{prom:.0f}/100', 'y')}")

    config["aprobadas"] = aprobadas
    return config


# ------------------------------------------------------------------ #
#  STEP 3 — PUBLICAR
# ------------------------------------------------------------------ #

def _step_publicar(config: dict, publicar_fb: bool, publicar_ig: bool) -> dict:
    """Publica todas las imágenes aprobadas."""
    _bar("PUBLICAR EN REDES", 3)

    aprobadas = config.get("aprobadas", [])
    publicables = [a for a in aprobadas if os.path.exists(a.get("ruta", ""))]

    if not publicables:
        print(f"  {_c('⚠', 'y')} No hay imágenes para publicar.")
        config["resultados_publicacion"] = []
        return config

    plataformas = []
    if publicar_fb:
        plataformas.append("Facebook")
    if publicar_ig:
        plataformas.append("Instagram")

    print(f"  Imágenes:     {_c(str(len(publicables)), 'B')}")
    print(f"  Plataformas:  {_c(', '.join(plataformas), 'c')}")
    print()

    # Facebook
    fb_manager = None
    if publicar_fb:
        try:
            fb_manager = MetaAdsManager()
            logger.info("MetaAdsManager inicializado")
        except Exception as e:
            print(f"  {_c('⚠', 'r')} Error Facebook: {e}")
            publicar_fb = False

    # Instagram (ngrok)
    ngrok_url = None
    if publicar_ig:
        ngrok_url = _iniciar_ngrok(config.get("carpeta", str(IMAGES_DIR)))
        if not ngrok_url:
            print(f"  {_c('⚠', 'r')} Ngrok no disponible. Instagram deshabilitado.")
            publicar_ig = False

    resultados = []

    for idx, ev in enumerate(publicables, 1):
        prod = PRODUCTOS[ev["producto"]]
        nombre = prod["nombre"]

        print(f"  [{idx}/{len(publicables)}] {_c(nombre, 'c')} / {ev['formato']}", end="")

        caption_ig = generar_caption_ig(ev["producto"])
        mensaje_fb = _generar_mensaje_fb(ev["producto"], config.get("tematica", ""))

        res = {"producto": ev["producto"], "formato": ev["formato"], "fb": None, "ig": None}

        # FB
        if publicar_fb and fb_manager:
            print(f"  📘", end="", flush=True)
            try:
                fb_r = fb_manager.publicar_con_imagen(
                    message=mensaje_fb, image_path=ev["ruta"]
                )
                if fb_r.get("success"):
                    res["fb"] = fb_r.get("photo_id")
                    print(_c("✓", "g"), end="")
                else:
                    res["fb"] = f"ERROR: {fb_r.get('error', '')}"
                    print(_c("✗", "r"), end="")
            except Exception as e:
                res["fb"] = f"ERROR: {e}"
                print(_c("✗", "r"), end="")

        # IG
        if publicar_ig and ngrok_url:
            print(f"  📸", end="", flush=True)
            try:
                carpeta_base = config.get("carpeta", str(IMAGES_DIR))
                ruta_rel = os.path.relpath(ev["ruta"], carpeta_base)
                image_url = f"{ngrok_url}/{ruta_rel}"

                page_token = META_PAGE_TOKEN or os.getenv("META_PAGE_TOKEN")
                ig_id = META_INSTAGRAM_ID or os.getenv("META_INSTAGRAM_ID")

                ig_r = _publicar_instagram(caption_ig, image_url, page_token, ig_id)
                if ig_r.get("success"):
                    res["ig"] = ig_r.get("media_id")
                    print(_c("✓", "g"), end="")
                else:
                    res["ig"] = f"ERROR: {ig_r.get('error', '')}"
                    print(_c("✗", "r"), end="")
            except Exception as e:
                res["ig"] = f"ERROR: {e}"
                print(_c("✗", "r"), end="")

        print()  # newline
        resultados.append(res)
        time.sleep(3)  # rate limit

    config["resultados_publicacion"] = resultados
    return config


# ------------------------------------------------------------------ #
#  STEP 4 — RESUMEN
# ------------------------------------------------------------------ #

def _step_resumen(config: dict):
    """Imprime resumen final y guarda metadata."""
    _bar("RESUMEN FINAL", 4)

    nombre = config.get("nombre", "")
    carpeta = config.get("carpeta", "")
    aprobadas = config.get("aprobadas", [])
    resultados = config.get("resultados_publicacion", [])

    total = config.get("total_esperado", 0)
    n_ok = sum(1 for a in aprobadas if a.get("estado") == "aprobada")
    n_forzadas = sum(1 for a in aprobadas if a.get("estado") == "aprobada_forzada")

    print(f"  📋 Campaña: {_c(nombre, 'c')}")
    print(f"  📁 Carpeta: {_c(carpeta, 'D')}")
    print()
    print(f"  ─── IMÁGENES ───")
    print(f"    Esperadas:         {total}")
    print(f"    Aprobadas IA:      {_c(str(n_ok), 'g')}")
    print(f"    Aprobadas forzada: {_c(str(n_forzadas), 'y')}")

    if aprobadas:
        prom = sum(a.get("puntaje", 0) for a in aprobadas) / len(aprobadas)
        print(f"    Promedio score:    {_c(f'{prom:.0f}/100', 'y')}")

    if resultados:
        fb_ok = sum(1 for r in resultados
                    if r.get("fb") and not str(r["fb"]).startswith("ERROR"))
        ig_ok = sum(1 for r in resultados
                    if r.get("ig") and not str(r["ig"]).startswith("ERROR"))

        print()
        print(f"  ─── PUBLICACIONES ───")
        print(f"    📘 Facebook:  {_c(str(fb_ok), 'g')}/{len(resultados)}")
        print(f"    📸 Instagram: {_c(str(ig_ok), 'g')}/{len(resultados)}")

        # Tabla
        print()
        print(f"  {'Producto':<20} {'Formato':<20} {'FB':<6} {'IG':<6}")
        print(f"  {'─' * 55}")
        for r in resultados:
            nombre_prod = PRODUCTOS[r["producto"]]["nombre"]
            fb_s = "✅" if r.get("fb") and not str(r["fb"]).startswith("ERROR") else "❌"
            ig_s = "✅" if r.get("ig") and not str(r["ig"]).startswith("ERROR") else "──"
            print(f"  {nombre_prod:<20} {r['formato']:<20} {fb_s:<6} {ig_s:<6}")

    # Guardar metadata
    if carpeta:
        meta_path = os.path.join(carpeta, "campana_auto_resultado.json")
        try:
            meta = {
                "modo": "auto_full_pass",
                "nombre": nombre,
                "tematica": config.get("tematica", ""),
                "fecha": datetime.now().isoformat(),
                "productos": config.get("productos", []),
                "formatos": config.get("formatos", []),
                "modelo": config.get("modelo", ""),
                "imagenes_total": total,
                "imagenes_aprobadas_ia": n_ok,
                "imagenes_aprobadas_forzadas": n_forzadas,
                "publicaciones": [
                    {
                        "producto": r["producto"],
                        "formato": r["formato"],
                        "fb_id": str(r.get("fb", "")) if r.get("fb") else None,
                        "ig_id": str(r.get("ig", "")) if r.get("ig") else None,
                    }
                    for r in resultados
                ],
            }
            with open(meta_path, "w", encoding="utf-8") as f:
                json.dump(meta, f, indent=2, ensure_ascii=False)
            print(f"\n  💾 Metadata: {_c(meta_path, 'D')}")
        except Exception as e:
            logger.error("Error guardando metadata: %s", e)

    duracion = config.get("_duracion", "")
    if duracion:
        print(f"  ⏱  Duración: {_c(duracion, 'y')}")

    print(f"\n  {_c('🎉 FULL PASS completado!', 'g')}\n")


# ------------------------------------------------------------------ #
#  HELPERS
# ------------------------------------------------------------------ #

def _generar_mensaje_fb(producto_key: str, tematica: str = "") -> str:
    """Genera mensaje para Facebook con UTM."""
    prod = PRODUCTOS.get(producto_key, {})
    nombre = prod.get("nombre", "")
    desc = prod.get("descripcion", "")
    slogan = prod.get("slogan", "")
    url = prod.get("url", "https://prisma-enterprice.cloud")
    precio = prod.get("precio_desde", "")

    url_utm = build_utm_url(
        url, source="facebook", medium="organic",
        campaign=f"auto_{datetime.now().strftime('%Y%m')}",
        content=f"post_{producto_key}",
    )

    tema = f"\n🎯 {tematica}\n" if tematica else ""

    if producto_key == "prizma":
        return (
            f"🚀 {slogan}{tema}\n{desc}.\n\n"
            f"Más de 60 pymes colombianas ya simplificaron su operación 💼\n\n"
            f"👉 {url_utm}\n\n"
            "#pymescolombia #softwareparapymes #transformaciondigital"
        )

    precio_line = f"Desde {precio}. " if precio and precio != "Próximamente" else ""
    return (
        f"🚀 {slogan}{tema}\n{desc}.\n{precio_line}\n"
        f"💼 Más de 60 pymes colombianas ya lo usan.\n\n"
        f"👉 {url_utm}\n\n"
        f"#{nombre.lower().replace(' ', '')} #pymescolombia #softwareparapymes"
    )


def _iniciar_ngrok(carpeta_base: str) -> str | None:
    """Inicia HTTP server + ngrok. Retorna URL pública o None."""
    port = 8765
    abs_dir = os.path.abspath(carpeta_base)

    def serve():
        os.chdir(abs_dir)
        handler = http.server.SimpleHTTPRequestHandler
        with socketserver.TCPServer(("", port), handler) as httpd:
            httpd.serve_forever()

    t = threading.Thread(target=serve, daemon=True)
    t.start()
    time.sleep(1)

    try:
        subprocess.Popen(
            ["ngrok", "http", str(port), "--log=stdout"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        time.sleep(4)
        r = requests.get("http://localhost:4040/api/tunnels", timeout=5)
        tunnels = r.json().get("tunnels", [])
        for tn in tunnels:
            if tn.get("proto") == "https":
                return tn["public_url"]
        if tunnels:
            return tunnels[0]["public_url"]
    except Exception as e:
        logger.warning("Ngrok no disponible: %s", e)
    return None


def _publicar_instagram(caption: str, image_url: str,
                        page_token: str, ig_id: str) -> dict:
    """Publica en Instagram via Content Publishing API."""
    r1 = requests.post(
        f"{GRAPH_API_BASE}/{ig_id}/media",
        data={"image_url": image_url, "caption": caption,
              "access_token": page_token},
    )
    d1 = r1.json()
    if "id" not in d1:
        return {"error": d1.get("error", {}).get("message", str(d1))}

    cid = d1["id"]

    for _ in range(MAX_IG_CONTAINER_RETRIES):
        sr = requests.get(
            f"{GRAPH_API_BASE}/{cid}",
            params={"fields": "status_code", "access_token": page_token},
        )
        st = sr.json().get("status_code", "")
        if st == "FINISHED":
            break
        if st == "ERROR":
            return {"error": f"Container ERROR: {sr.json()}"}
        time.sleep(IG_CONTAINER_POLL_INTERVAL)

    r2 = requests.post(
        f"{GRAPH_API_BASE}/{ig_id}/media_publish",
        data={"creation_id": cid, "access_token": page_token},
    )
    d2 = r2.json()
    if "id" in d2:
        return {"success": True, "media_id": d2["id"]}
    return {"error": d2.get("error", {}).get("message", str(d2))}


# ------------------------------------------------------------------ #
#  MAIN — Orquestador autónomo
# ------------------------------------------------------------------ #

def run_auto(
    productos: list[str] | None = None,
    formatos: list[str] | None = None,
    modelo: str = DEFAULT_MODELO,
    tematica: str = DEFAULT_TEMATICA,
    nombre: str | None = None,
    umbral: int = DEFAULT_UMBRAL,
    max_rondas: int = DEFAULT_MAX_RONDAS,
    publicar_fb: bool = True,
    publicar_ig: bool = True,
    dry_run: bool = False,
):
    """
    Ejecuta el pipeline completo de forma autónoma.

    Args:
        productos: Lista de keys. None = todos los activos.
        formatos: Lista de formatos. None = 4 principales.
        modelo: Modelo de generación.
        tematica: Temática de la campaña.
        nombre: Nombre. None = auto-generado.
        umbral: Puntaje mínimo para aprobar (0-100).
        max_rondas: Máximo rondas de regeneración.
        publicar_fb: Publicar en Facebook.
        publicar_ig: Publicar en Instagram.
        dry_run: True = no publicar (solo generar + evaluar).
    """
    t_inicio = time.time()

    # Defaults
    if productos is None:
        productos = list(PRODUCTOS.keys())
    if formatos is None:
        formatos = list(DEFAULT_FORMATOS)
    if nombre is None:
        nombre = f"Auto_{datetime.now().strftime('%Y%m%d_%H%M')}"

    total = len(productos) * len(formatos)

    print()
    print(_c("╔══════════════════════════════════════════════════════════════════╗", "m"))
    print(_c("║      PRIZMA — FULL PASS AUTÓNOMO v1.0                          ║", "m"))
    print(_c("║      Generar → Evaluar (×3) → Publicar — sin intervención      ║", "m"))
    print(_c("╚══════════════════════════════════════════════════════════════════╝", "m"))
    print()
    print(f"  Campaña:    {_c(nombre, 'c')}")
    print(f"  Productos:  {_c(str(len(productos)), 'y')} ({', '.join(productos)})")
    print(f"  Formatos:   {_c(str(len(formatos)), 'y')} ({', '.join(formatos)})")
    print(f"  Total imgs: {_c(str(total), 'B')}")
    print(f"  Modelo:     {_c(modelo, 'y')}")
    print(f"  Umbral:     {_c(str(umbral), 'y')}/100")
    print(f"  Rondas max: {_c(str(max_rondas), 'y')}")
    print(f"  Dry-run:    {_c('SÍ' if dry_run else 'NO', 'y' if dry_run else 'g')}")
    print()

    try:
        # STEP 1: Generar
        config = _step_generar(productos, formatos, modelo, tematica, nombre)

        # STEP 2: Evaluar + regenerar automático (hasta N rondas)
        config = _step_evaluar_y_regenerar(config, umbral, max_rondas, modelo)

        # STEP 3: Publicar (si no es dry-run)
        if dry_run:
            _bar("PUBLICAR EN REDES (DRY-RUN)", 3)
            print(f"  {_c('⏭  Dry-run: publicación omitida.', 'y')}")
            print(f"  Las imágenes están en: {_c(config.get('carpeta', ''), 'D')}")
            config["resultados_publicacion"] = []
        else:
            config = _step_publicar(config, publicar_fb, publicar_ig)

        # STEP 4: Resumen
        duracion_seg = time.time() - t_inicio
        mins = int(duracion_seg // 60)
        segs = int(duracion_seg % 60)
        config["_duracion"] = f"{mins}m {segs}s"
        _step_resumen(config)

    except KeyboardInterrupt:
        print(f"\n\n  {_c('⏹ Cancelado (Ctrl+C).', 'y')}")
        sys.exit(1)
    except Exception as e:
        logger.error("Error en auto full pass: %s", e, exc_info=True)
        print(f"\n  {_c(f'❌ Error: {e}', 'r')}")
        sys.exit(1)


def main():
    """Entry point CLI."""
    import argparse

    parser = argparse.ArgumentParser(
        description="FULL PASS autónomo — genera, evalúa y publica sin intervención"
    )
    parser.add_argument(
        "--productos", nargs="+", default=None,
        help=f"Productos a incluir (default: todos). Opciones: {list(PRODUCTOS.keys())}",
    )
    parser.add_argument(
        "--formatos", nargs="+", default=None,
        help=f"Formatos de imagen (default: {DEFAULT_FORMATOS})",
    )
    parser.add_argument("--modelo", default=DEFAULT_MODELO, help="Modelo IA")
    parser.add_argument("--tematica", default=DEFAULT_TEMATICA, help="Temática de campaña")
    parser.add_argument("--nombre", default=None, help="Nombre de la campaña")
    parser.add_argument("--umbral", type=int, default=DEFAULT_UMBRAL, help="Score mínimo (0-100)")
    parser.add_argument("--max-rondas", type=int, default=DEFAULT_MAX_RONDAS, help="Rondas de regeneración")
    parser.add_argument("--skip-fb", action="store_true", help="No publicar en Facebook")
    parser.add_argument("--skip-ig", action="store_true", help="No publicar en Instagram")
    parser.add_argument("--dry-run", action="store_true", help="Solo generar + evaluar, sin publicar")

    args = parser.parse_args()

    run_auto(
        productos=args.productos,
        formatos=args.formatos,
        modelo=args.modelo,
        tematica=args.tematica,
        nombre=args.nombre,
        umbral=args.umbral,
        max_rondas=args.max_rondas,
        publicar_fb=not args.skip_fb,
        publicar_ig=not args.skip_ig,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    main()
