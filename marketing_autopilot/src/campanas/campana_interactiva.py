#!/usr/bin/env python3
"""
campana_interactiva.py — Flujo completo de campaña con aprobación humana.

Pipeline step-by-step:
  STEP 1 → Configurar campaña (nombre, temática, productos, formatos, cantidad)
  STEP 2 → Generar imágenes con IA
  STEP 3 → Evaluación automática (Image Critic)
  STEP 4 → Revisión humana (aprobar / rechazar / eliminar)
  STEP 5 → Publicar en Facebook + Instagram
  STEP 6 → Resumen final

Uso:
  cd marketing_autopilot
  python3 -m src.campana_interactiva
"""

import os
import sys
import json
import glob
import time
import shutil
import subprocess
import threading
import http.server
import socketserver
from pathlib import Path
from datetime import datetime

from config import (
    get_logger, PRODUCTOS, PRODUCTOS_ACTIVOS, IMAGES_DIR,
    CAMPAIGNS_DIR, OUTPUT_DIR, generar_caption_ig, build_utm_url,
    GRAPH_API_BASE, META_PAGE_TOKEN, META_INSTAGRAM_ID,
    MAX_IG_CONTAINER_RETRIES, IG_CONTAINER_POLL_INTERVAL,
)
from core.image_generator import ImageGenerator
from core.image_critic import ImageCritic
from social.publisher import MetaAdsManager

import requests

logger = get_logger("campana_interactiva")

# ------------------------------------------------------------------ #
#  UTILIDADES DE INTERFAZ
# ------------------------------------------------------------------ #

COLORES = {
    "reset":   "\033[0m",
    "bold":    "\033[1m",
    "dim":     "\033[2m",
    "red":     "\033[91m",
    "green":   "\033[92m",
    "yellow":  "\033[93m",
    "blue":    "\033[94m",
    "magenta": "\033[95m",
    "cyan":    "\033[96m",
}


def c(texto: str, color: str) -> str:
    """Colorea texto para terminal."""
    return f"{COLORES.get(color, '')}{texto}{COLORES['reset']}"


def banner(titulo: str, step: int = 0, total: int = 6):
    """Muestra un banner de paso."""
    print()
    print(c("=" * 70, "cyan"))
    if step > 0:
        progreso = "█" * step + "░" * (total - step)
        print(c(f"  STEP {step}/{total}  [{progreso}]  {titulo}", "bold"))
    else:
        print(c(f"  {titulo}", "bold"))
    print(c("=" * 70, "cyan"))
    print()


def pregunta(texto: str, default: str = "") -> str:
    """Input con valor por defecto."""
    hint = f" [{default}]" if default else ""
    resp = input(f"  {c('›', 'cyan')} {texto}{hint}: ").strip()
    return resp or default


def pregunta_si_no(texto: str, default: bool = True) -> bool:
    """Pregunta sí/no."""
    hint = "S/n" if default else "s/N"
    resp = input(f"  {c('›', 'cyan')} {texto} ({hint}): ").strip().lower()
    if not resp:
        return default
    return resp in ("s", "si", "sí", "y", "yes")


def elegir_opcion(opciones: list[str], texto: str = "Elige una opción") -> int:
    """Muestra opciones numeradas y retorna el índice elegido."""
    for i, op in enumerate(opciones, 1):
        print(f"    {c(str(i), 'yellow')}. {op}")
    while True:
        try:
            idx = int(pregunta(texto, "1"))
            if 1 <= idx <= len(opciones):
                return idx - 1
            print(c("    Opción inválida.", "red"))
        except ValueError:
            print(c("    Ingresa un número.", "red"))


def elegir_multiples(opciones: list[str], texto: str = "Elige (separados por coma, 'all' para todos)") -> list[int]:
    """Muestra opciones y permite elegir varias."""
    for i, op in enumerate(opciones, 1):
        print(f"    {c(str(i), 'yellow')}. {op}")
    while True:
        resp = pregunta(texto, "all").lower()
        if resp in ("all", "todos", "*"):
            return list(range(len(opciones)))
        try:
            indices = [int(x.strip()) - 1 for x in resp.split(",")]
            if all(0 <= i < len(opciones) for i in indices):
                return indices
            print(c("    Algún número está fuera de rango.", "red"))
        except ValueError:
            print(c("    Ingresa números separados por coma.", "red"))


def abrir_imagen(ruta: str):
    """Abre una imagen con el visor del sistema."""
    try:
        subprocess.Popen(
            ["xdg-open", ruta],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        print(c(f"    No se pudo abrir: {ruta}", "dim"))


def abrir_carpeta(ruta: str):
    """Abre una carpeta con el file manager del sistema."""
    try:
        subprocess.Popen(
            ["xdg-open", ruta],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        pass


# ------------------------------------------------------------------ #
#  STEP 1 — CONFIGURAR CAMPAÑA
# ------------------------------------------------------------------ #

def step_configurar() -> dict:
    """Configura los parámetros de la campaña interactivamente."""
    banner("CONFIGURAR CAMPAÑA", 1)

    # Nombre
    nombre = pregunta(
        "Nombre de la campaña",
        f"Campaña_{datetime.now().strftime('%Y%m%d')}",
    )

    # Temática
    print()
    print(c("  Temáticas sugeridas:", "dim"))
    tematicas = [
        "Lanzamiento de producto",
        "Promoción / descuento",
        "Educativo / tips",
        "Testimonios / casos de éxito",
        "Awareness / marca",
        "Personalizada (escribir)",
    ]
    idx_tema = elegir_opcion(tematicas, "Temática")
    if idx_tema == len(tematicas) - 1:
        tematica = pregunta("Describe la temática")
    else:
        tematica = tematicas[idx_tema]

    # Productos
    print()
    print(c("  Productos disponibles:", "dim"))
    prods = list(PRODUCTOS.keys())
    prod_labels = []
    for k in prods:
        p = PRODUCTOS[k]
        activo = "⚡" if k in PRODUCTOS_ACTIVOS else "  "
        prod_labels.append(f"{activo} {p['nombre']:18s} — {p['descripcion'][:60]}")
    indices = elegir_multiples(prod_labels, "Productos a incluir")
    productos = [prods[i] for i in indices]
    print(c(f"  ✓ Seleccionados: {', '.join(productos)}", "green"))

    # Formatos
    print()
    print(c("  Formatos de imagen disponibles:", "dim"))
    todos_formatos = [
        ("feed_1x1",        "Post cuadrado (1:1) — Feed FB/IG"),
        ("story_9x16",      "Story vertical (9:16) — Stories/Reels"),
        ("banner_16x9",     "Banner horizontal (16:9) — Cover FB"),
        ("promo_1x1",       "Escena promocional (1:1) — Sin logo"),
        ("carousel_1x1",    "Slide carrusel (1:1) — Beneficio"),
        ("tip_1x1",         "Tip educativo (1:1) — ¿Sabías que?"),
        ("stat_1x1",        "Estadística (1:1) — Número destacado"),
        ("feature_9x16",    "Feature showcase (9:16) — Función clave"),
        ("cta_story_9x16",  "CTA agresivo (9:16) — ¡Empieza hoy!"),
        ("testimonial_1x1", "Testimonio (1:1) — Quote de cliente"),
    ]
    fmt_labels = [f"{f[0]:22s} — {f[1]}" for f in todos_formatos]
    fmt_indices = elegir_multiples(fmt_labels, "Formatos a generar")
    formatos = [todos_formatos[i][0] for i in fmt_indices]
    print(c(f"  ✓ Formatos: {', '.join(formatos)}", "green"))

    # Modelo
    print()
    print(c("  Modelo de generación:", "dim"))
    modelos = [
        "gemini-3-pro-image-preview   (PRO — mejor calidad, más lento)",
        "gemini-2.5-flash-image       (Flash — rápido, menor calidad)",
    ]
    idx_modelo = elegir_opcion(modelos, "Modelo")
    modelo = "gemini-3-pro-image-preview" if idx_modelo == 0 else "gemini-2.5-flash-image"

    # Resumen
    total_imgs = len(productos) * len(formatos)
    print()
    print(c("  ─── RESUMEN DE CONFIGURACIÓN ───", "bold"))
    print(f"    Nombre:     {c(nombre, 'cyan')}")
    print(f"    Temática:   {c(tematica, 'cyan')}")
    print(f"    Productos:  {c(str(len(productos)), 'yellow')} ({', '.join(productos)})")
    print(f"    Formatos:   {c(str(len(formatos)), 'yellow')} ({', '.join(formatos)})")
    print(f"    Modelo:     {c(modelo, 'yellow')}")
    print(f"    Total imgs: {c(str(total_imgs), 'bold')}")
    print()

    if not pregunta_si_no("¿Confirmar y continuar?"):
        print(c("  Cancelado por el usuario.", "red"))
        sys.exit(0)

    return {
        "nombre": nombre,
        "tematica": tematica,
        "productos": productos,
        "formatos": formatos,
        "modelo": modelo,
        "total_esperado": total_imgs,
    }


# ------------------------------------------------------------------ #
#  STEP 2 — GENERAR IMÁGENES
# ------------------------------------------------------------------ #

def step_generar(config: dict) -> dict:
    """Genera las imágenes usando ImageGenerator."""
    banner("GENERAR IMÁGENES", 2)

    print(f"  Generando {c(str(config['total_esperado']), 'bold')} imágenes...")
    print(f"  Modelo: {c(config['modelo'], 'cyan')}")
    print(f"  Esto puede tomar varios minutos.\n")

    gen = ImageGenerator(model=config["modelo"])

    campana_meta = gen.generar_campana(
        nombre_campana=config["nombre"],
        productos=config["productos"],
        tematica=config["tematica"],
        formatos=config["formatos"],
    )

    # Contar resultados
    total_generadas = sum(len(v) for v in campana_meta.get("imagenes", {}).values())
    carpeta = campana_meta.get("carpeta", "")

    print()
    print(c(f"  ✓ {total_generadas}/{config['total_esperado']} imágenes generadas", "green"))
    print(f"    Carpeta: {c(carpeta, 'dim')}")

    config["campana_meta"] = campana_meta
    config["carpeta"] = carpeta

    # Abrir carpeta para que vea las imágenes mientras tanto
    if carpeta and os.path.isdir(carpeta):
        if pregunta_si_no("¿Abrir la carpeta de imágenes?"):
            abrir_carpeta(carpeta)

    return config


# ------------------------------------------------------------------ #
#  STEP 3 — EVALUACIÓN AUTOMÁTICA (IA)
# ------------------------------------------------------------------ #

def step_evaluar(config: dict) -> dict:
    """Evalúa las imágenes generadas con el Image Critic."""
    banner("EVALUACIÓN AUTOMÁTICA (IA)", 3)

    campana_meta = config["campana_meta"]
    carpeta = config["carpeta"]

    # Recopilar todas las imágenes
    imagenes = []
    for prod_key, imgs in campana_meta.get("imagenes", {}).items():
        for img_info in imgs:
            ruta = img_info.get("path", "")
            formato = img_info.get("formato", "")
            if ruta and os.path.exists(ruta):
                imagenes.append({
                    "ruta": ruta,
                    "producto": prod_key,
                    "formato": formato,
                    "archivo": os.path.basename(ruta),
                })

    if not imagenes:
        print(c("  ⚠ No se encontraron imágenes para evaluar.", "yellow"))
        config["evaluaciones"] = []
        return config

    print(f"  Evaluando {c(str(len(imagenes)), 'bold')} imágenes con IA Critic...")
    print(f"  Umbral de aprobación: {c('70/100', 'yellow')}")
    print()

    critic = ImageCritic(umbral=70, max_intentos=0)  # sin regenerar auto
    evaluaciones = []

    for i, img in enumerate(imagenes, 1):
        nombre_prod = PRODUCTOS[img["producto"]]["nombre"]
        print(f"  [{i}/{len(imagenes)}] {nombre_prod} / {img['formato']}...", end=" ", flush=True)

        resultado = critic.evaluar_imagen(img["ruta"], img["producto"], img["formato"])

        puntaje = resultado.get("puntaje_total", 0)
        veredicto = resultado.get("veredicto", "ERROR")

        if veredicto == "APROBADA":
            print(c(f"✅ {puntaje}/100", "green"))
        elif "error" in resultado:
            print(c(f"⚠ Error: {resultado['error'][:50]}", "yellow"))
        else:
            print(c(f"❌ {puntaje}/100", "red"))
            defectos = resultado.get("defectos_criticos", [])
            if defectos:
                for d in defectos[:2]:
                    print(c(f"       └─ {d[:70]}", "dim"))

        evaluaciones.append({
            **img,
            "puntaje": puntaje,
            "veredicto": veredicto,
            "resumen": resultado.get("resumen", ""),
            "feedback": resultado.get("feedback_regeneracion", ""),
            "defectos": resultado.get("defectos_criticos", []),
            "marcas_terceros": resultado.get("marcas_terceros", []),
            "detalles": {
                "colores": resultado.get("colores", {}).get("puntaje", 0),
                "texto": resultado.get("texto", {}).get("puntaje", 0),
                "composicion": resultado.get("composicion", {}).get("puntaje", 0),
                "logo": resultado.get("logo", {}).get("puntaje", 0),
                "impacto": resultado.get("impacto", {}).get("puntaje", 0),
            },
            "estado": "aprobada_ia" if veredicto == "APROBADA" else "rechazada_ia",
        })

    # Resumen
    aprobadas = sum(1 for e in evaluaciones if e["estado"] == "aprobada_ia")
    rechazadas = len(evaluaciones) - aprobadas
    promedio = (sum(e["puntaje"] for e in evaluaciones) / len(evaluaciones)) if evaluaciones else 0

    print()
    print(c("  ─── RESUMEN EVALUACIÓN IA ───", "bold"))
    print(f"    ✅ Aprobadas:   {c(str(aprobadas), 'green')}")
    print(f"    ❌ Rechazadas:  {c(str(rechazadas), 'red')}")
    print(f"    📊 Promedio:    {c(f'{promedio:.0f}/100', 'yellow')}")

    config["evaluaciones"] = evaluaciones
    return config


# ------------------------------------------------------------------ #
#  STEP 4 — REVISIÓN HUMANA
# ------------------------------------------------------------------ #

def step_revision_humana(config: dict) -> dict:
    """Permite al humano revisar, aprobar, rechazar o eliminar imágenes."""
    banner("REVISIÓN HUMANA", 4)

    evaluaciones = config.get("evaluaciones", [])
    if not evaluaciones:
        print(c("  No hay imágenes para revisar.", "yellow"))
        return config

    print(c("  Revisa cada imagen y decide su destino.", "dim"))
    print(c("  Opciones: (a)probar  (r)echazar  (e)liminar  (v)er  (s)altar", "dim"))
    print(c("  'aa' = aprobar todas las restantes  'done' = terminar revisión", "dim"))
    print()

    # Mostrar tabla resumen primero
    print(c("  #   Producto          Formato           Score   IA        Archivo", "bold"))
    print(c("  " + "─" * 80, "dim"))
    for i, ev in enumerate(evaluaciones):
        nombre_prod = PRODUCTOS[ev["producto"]]["nombre"]
        ia_emoji = "✅" if ev["estado"] == "aprobada_ia" else "❌"
        score_color = "green" if ev["puntaje"] >= 70 else "red"
        print(
            f"  {c(str(i+1).rjust(2), 'yellow')}  "
            f"{nombre_prod:18s} {ev['formato']:18s} "
            f"{c(str(ev['puntaje']).rjust(3), score_color)}/100  {ia_emoji}  "
            f"{c(ev['archivo'][:35], 'dim')}"
        )
    print()

    # Abrir carpeta para revisar visualmente
    carpeta = config.get("carpeta", "")
    if carpeta and os.path.isdir(carpeta):
        if pregunta_si_no("¿Abrir la carpeta para revisión visual?"):
            abrir_carpeta(carpeta)
            print(c("  Revisa las imágenes en el explorador de archivos...", "dim"))
            print()

    # Revisión interactiva
    finales = []
    i = 0
    while i < len(evaluaciones):
        ev = evaluaciones[i]
        nombre_prod = PRODUCTOS[ev["producto"]]["nombre"]
        ia_emoji = "✅" if ev["estado"] == "aprobada_ia" else "❌"
        score_color = "green" if ev["puntaje"] >= 70 else "red"

        print(
            f"  {c(f'[{i+1}/{len(evaluaciones)}]', 'bold')} "
            f"{c(nombre_prod, 'cyan')} / {ev['formato']}  "
            f"Score: {c(str(ev['puntaje']), score_color)}/100 {ia_emoji}"
        )
        if ev.get("resumen"):
            print(c(f"       {ev['resumen'][:90]}", "dim"))
        if ev.get("defectos"):
            for d in ev["defectos"][:2]:
                print(c(f"       ⚠ {d[:80]}", "yellow"))

        while True:
            accion = pregunta("(a)probar (r)echazar (e)liminar (v)er (s)altar (aa=todo) (done)", "a").lower()

            if accion in ("a", "aprobar"):
                ev["estado"] = "aprobada_humano"
                print(c("       ✅ Aprobada", "green"))
                finales.append(ev)
                break
            elif accion in ("r", "rechazar"):
                ev["estado"] = "rechazada_humano"
                print(c("       ❌ Rechazada (se puede regenerar luego)", "red"))
                finales.append(ev)
                break
            elif accion in ("e", "eliminar", "del"):
                ev["estado"] = "eliminada"
                print(c("       🗑  Eliminada", "red"))
                # Mover a _rejected
                rejected_dir = os.path.join(str(OUTPUT_DIR), "_rejected", ev["producto"])
                os.makedirs(rejected_dir, exist_ok=True)
                try:
                    dest = os.path.join(rejected_dir, ev["archivo"])
                    shutil.move(ev["ruta"], dest)
                    print(c(f"       Movida a: {dest}", "dim"))
                except Exception as e:
                    print(c(f"       Error moviendo: {e}", "red"))
                finales.append(ev)
                break
            elif accion in ("v", "ver"):
                abrir_imagen(ev["ruta"])
                print(c("       Imagen abierta. Revisa y elige...", "dim"))
                continue
            elif accion in ("s", "saltar", "skip"):
                # Mantener estado IA
                finales.append(ev)
                print(c("       ⏭  Saltada (mantiene decisión IA)", "dim"))
                break
            elif accion in ("aa", "all", "aprobar todo"):
                # Aprobar todas las restantes
                ev["estado"] = "aprobada_humano"
                finales.append(ev)
                for remaining in evaluaciones[i + 1:]:
                    remaining["estado"] = "aprobada_humano"
                    finales.append(remaining)
                i = len(evaluaciones)
                print(c(f"       ✅ Aprobadas {len(evaluaciones) - i + len(evaluaciones[i:])} imágenes restantes", "green"))
                break
            elif accion in ("done", "fin", "terminar"):
                # Agregar las restantes como están
                finales.append(ev)
                for remaining in evaluaciones[i + 1:]:
                    finales.append(remaining)
                i = len(evaluaciones)
                print(c("       ⏹  Revisión terminada", "dim"))
                break
            else:
                print(c("       Opción inválida. Usa: a/r/e/v/s/aa/done", "red"))

        i += 1

    # Resumen de revisión
    aprobadas = [e for e in finales if e["estado"] in ("aprobada_humano", "aprobada_ia")]
    rechazadas = [e for e in finales if "rechazada" in e["estado"]]
    eliminadas = [e for e in finales if e["estado"] == "eliminada"]

    print()
    print(c("  ─── RESUMEN REVISIÓN HUMANA ───", "bold"))
    print(f"    ✅ Aprobadas:   {c(str(len(aprobadas)), 'green')}")
    print(f"    ❌ Rechazadas:  {c(str(len(rechazadas)), 'red')}")
    print(f"    🗑  Eliminadas:  {c(str(len(eliminadas)), 'red')}")

    config["evaluaciones"] = finales
    config["aprobadas"] = aprobadas

    # ¿Regenerar rechazadas?
    if rechazadas:
        print()
        if pregunta_si_no(f"¿Regenerar las {len(rechazadas)} imágenes rechazadas?", default=False):
            config = _regenerar_rechazadas(config, rechazadas)

    return config


def _regenerar_rechazadas(config: dict, rechazadas: list[dict]) -> dict:
    """Regenera imágenes rechazadas y las re-evalúa."""
    print()
    print(c("  🔄 Regenerando imágenes rechazadas...", "bold"))

    gen = ImageGenerator(model=config.get("modelo", "gemini-3-pro-image-preview"))
    critic = ImageCritic(umbral=70, max_intentos=0)
    carpeta = config.get("carpeta", "")

    nuevas_aprobadas = []

    for ev in rechazadas:
        nombre_prod = PRODUCTOS[ev["producto"]]["nombre"]
        print(f"\n  🎨 {nombre_prod} / {ev['formato']}...")

        # Determinar directorio de salida
        prod_dir = os.path.join(carpeta, ev["producto"]) if carpeta else str(IMAGES_DIR)
        os.makedirs(prod_dir, exist_ok=True)

        # Regenerar usando generar_campana internamente
        nueva_ruta = gen._generar_formato_campana(
            ev["producto"], ev["formato"], config.get("tematica", ""), prod_dir
        )

        if not nueva_ruta:
            print(c("    ⚠ Falló la regeneración", "yellow"))
            continue

        # Re-evaluar
        resultado = critic.evaluar_imagen(nueva_ruta, ev["producto"], ev["formato"])
        puntaje = resultado.get("puntaje_total", 0)
        veredicto = resultado.get("veredicto", "ERROR")

        if veredicto == "APROBADA":
            print(c(f"    ✅ Nueva imagen aprobada: {puntaje}/100", "green"))
            ev["ruta"] = nueva_ruta
            ev["archivo"] = os.path.basename(nueva_ruta)
            ev["puntaje"] = puntaje
            ev["estado"] = "aprobada_humano"
            nuevas_aprobadas.append(ev)
        else:
            print(c(f"    ❌ Nueva imagen también rechazada: {puntaje}/100", "red"))
            # Preguntar si aprobar manualmente
            if pregunta_si_no("    ¿Aprobar manualmente de todas formas?", default=False):
                ev["ruta"] = nueva_ruta
                ev["archivo"] = os.path.basename(nueva_ruta)
                ev["puntaje"] = puntaje
                ev["estado"] = "aprobada_humano"
                nuevas_aprobadas.append(ev)

    # Actualizar lista de aprobadas
    config["aprobadas"] = config.get("aprobadas", []) + nuevas_aprobadas
    print(c(f"\n  ✓ {len(nuevas_aprobadas)} imágenes adicionales aprobadas tras regeneración", "green"))

    return config


# ------------------------------------------------------------------ #
#  STEP 5 — PUBLICAR
# ------------------------------------------------------------------ #

def step_publicar(config: dict) -> dict:
    """Publica las imágenes aprobadas en Facebook e Instagram."""
    banner("PUBLICAR EN REDES", 5)

    aprobadas = config.get("aprobadas", [])
    if not aprobadas:
        print(c("  No hay imágenes aprobadas para publicar.", "yellow"))
        return config

    # Filtrar solo feed_1x1 para publicación (el formato ideal para FB/IG feed)
    publicables = [e for e in aprobadas if os.path.exists(e.get("ruta", ""))]

    if not publicables:
        print(c("  No hay imágenes con archivo válido para publicar.", "yellow"))
        return config

    # Mostrar qué se va a publicar
    print(c("  Imágenes listas para publicar:", "dim"))
    for i, ev in enumerate(publicables, 1):
        nombre = PRODUCTOS[ev["producto"]]["nombre"]
        print(f"    {c(str(i), 'yellow')}. {nombre:18s} / {ev['formato']:18s} ({ev['puntaje']}/100)")

    print()
    print(c("  Plataformas:", "dim"))
    publicar_fb = pregunta_si_no("¿Publicar en Facebook?", default=True)
    publicar_ig = pregunta_si_no("¿Publicar en Instagram?", default=True)

    if not publicar_fb and not publicar_ig:
        print(c("  No se seleccionó ninguna plataforma.", "yellow"))
        return config

    # Seleccionar cuáles publicar
    print()
    labels = [
        f"{PRODUCTOS[e['producto']]['nombre']} / {e['formato']}"
        for e in publicables
    ]
    indices = elegir_multiples(labels, "¿Cuáles publicar?")
    a_publicar = [publicables[i] for i in indices]

    print(f"\n  Publicando {c(str(len(a_publicar)), 'bold')} imágenes...")

    # Inicializar publisher para Facebook
    fb_manager = None
    if publicar_fb:
        try:
            fb_manager = MetaAdsManager()
            logger.info("MetaAdsManager inicializado para Facebook")
        except Exception as e:
            print(c(f"  ⚠ Error inicializando Facebook: {e}", "red"))
            publicar_fb = False

    # Para Instagram necesitamos ngrok
    ngrok_proc = None
    ngrok_url = None
    if publicar_ig:
        ngrok_url = _iniciar_servidor_imagenes(config.get("carpeta", str(IMAGES_DIR)))
        if not ngrok_url:
            print(c("  ⚠ No se pudo iniciar ngrok. Instagram deshabilitado.", "red"))
            publicar_ig = False

    resultados = []

    for ev in a_publicar:
        prod = PRODUCTOS[ev["producto"]]
        nombre = prod["nombre"]
        ruta = ev["ruta"]
        formato = ev["formato"]

        print(f"\n  {'─' * 50}")
        print(f"  📤 {c(nombre, 'cyan')} / {formato}")

        # Generar caption y mensaje
        caption_ig = generar_caption_ig(ev["producto"])
        mensaje_fb = _generar_mensaje_fb(ev["producto"], config.get("tematica", ""))

        resultado = {
            "producto": ev["producto"],
            "formato": formato,
            "fb": None,
            "ig": None,
        }

        # === FACEBOOK ===
        if publicar_fb and fb_manager:
            print(f"    📘 Facebook...", end=" ", flush=True)
            try:
                fb_result = fb_manager.publicar_con_imagen(
                    message=mensaje_fb,
                    image_path=ruta,
                )
                if fb_result.get("success"):
                    print(c(f"✅ Post ID: {fb_result.get('photo_id', 'OK')}", "green"))
                    resultado["fb"] = fb_result.get("photo_id")
                else:
                    print(c(f"❌ {fb_result.get('error', 'Error')[:60]}", "red"))
                    resultado["fb"] = f"ERROR: {fb_result.get('error', '')}"
            except Exception as e:
                print(c(f"❌ {e}", "red"))
                resultado["fb"] = f"ERROR: {e}"

        # === INSTAGRAM ===
        if publicar_ig and ngrok_url:
            print(f"    📸 Instagram...", end=" ", flush=True)
            try:
                # Construir URL pública de la imagen
                carpeta_base = config.get("carpeta", str(IMAGES_DIR))
                ruta_relativa = os.path.relpath(ruta, carpeta_base)
                image_url = f"{ngrok_url}/{ruta_relativa}"

                page_token = META_PAGE_TOKEN or os.getenv("META_PAGE_TOKEN")
                ig_id = META_INSTAGRAM_ID or os.getenv("META_INSTAGRAM_ID")

                ig_result = _publicar_instagram(caption_ig, image_url, page_token, ig_id)
                if ig_result.get("success"):
                    print(c(f"✅ Media ID: {ig_result.get('media_id', 'OK')}", "green"))
                    resultado["ig"] = ig_result.get("media_id")
                else:
                    print(c(f"❌ {ig_result.get('error', 'Error')[:60]}", "red"))
                    resultado["ig"] = f"ERROR: {ig_result.get('error', '')}"
            except Exception as e:
                print(c(f"❌ {e}", "red"))
                resultado["ig"] = f"ERROR: {e}"

        resultados.append(resultado)
        time.sleep(3)  # Rate limiting entre publicaciones

    # Cerrar ngrok
    if ngrok_proc:
        ngrok_proc.terminate()

    config["resultados_publicacion"] = resultados
    return config


def _generar_mensaje_fb(producto_key: str, tematica: str = "") -> str:
    """Genera un mensaje para Facebook con UTM tracking."""
    prod = PRODUCTOS.get(producto_key, {})
    nombre = prod.get("nombre", "")
    desc = prod.get("descripcion", "")
    slogan = prod.get("slogan", "")
    url = prod.get("url", "https://www.humanizar.co")
    cta = prod.get("cta", "")

    url_utm = build_utm_url(
        url,
        source="facebook",
        medium="organic",
        campaign=f"campana_{datetime.now().strftime('%Y%m')}",
        content=f"post_{producto_key}",
    )

    tema_line = f"\n🎯 {tematica}\n" if tematica else ""

    if producto_key == "humanizar":
        return (
            f"🚀 {slogan}{tema_line}\n"
            f"{desc}.\n\n"
            f"Más de 60 pymes colombianas ya simplificaron su operación 💼\n\n"
            f"👉 {url_utm}\n\n"
            "#pymescolombia #softwareparapymes #transformaciondigital"
        )

    precio = prod.get("precio_desde", "")
    precio_line = f"Desde {precio}. " if precio and precio != "Próximamente" else ""

    return (
        f"🚀 {slogan}{tema_line}\n"
        f"{desc}.\n"
        f"{precio_line}\n"
        f"💼 Más de 60 pymes colombianas ya lo usan.\n\n"
        f"👉 {url_utm}\n\n"
        f"#{nombre.lower().replace(' ', '')} #pymescolombia #softwareparapymes"
    )


def _iniciar_servidor_imagenes(carpeta_base: str) -> str | None:
    """Inicia HTTP server + ngrok para servir imágenes a Instagram."""
    print(c("  Iniciando servidor HTTP + ngrok...", "dim"))
    port = 8765

    abs_dir = os.path.abspath(carpeta_base)

    # Servidor HTTP
    def serve():
        os.chdir(abs_dir)
        handler = http.server.SimpleHTTPRequestHandler
        httpd = socketserver.TCPServer(("", port), handler)
        httpd.serve_forever()

    t = threading.Thread(target=serve, daemon=True)
    t.start()
    time.sleep(1)

    # Ngrok
    try:
        subprocess.Popen(
            ["ngrok", "http", str(port), "--log=stdout"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        time.sleep(4)

        # Obtener URL
        r = requests.get("http://localhost:4040/api/tunnels", timeout=5)
        tunnels = r.json().get("tunnels", [])
        for t in tunnels:
            if t.get("proto") == "https":
                url = t["public_url"]
                print(c(f"  ✓ Ngrok URL: {url}", "green"))
                return url
        if tunnels:
            url = tunnels[0]["public_url"]
            print(c(f"  ✓ Ngrok URL: {url}", "green"))
            return url
    except Exception as e:
        print(c(f"  ⚠ Error con ngrok: {e}", "red"))
        print(c("  Asegúrate de tener ngrok instalado y sin sesiones activas.", "dim"))

    return None


def _publicar_instagram(caption: str, image_url: str, page_token: str, ig_id: str) -> dict:
    """Publica en Instagram via Content Publishing API."""
    # Paso 1: Crear container
    r1 = requests.post(
        f"{GRAPH_API_BASE}/{ig_id}/media",
        data={
            "image_url": image_url,
            "caption": caption,
            "access_token": page_token,
        }
    )
    result1 = r1.json()
    if "id" not in result1:
        return {"error": f"Container: {result1.get('error', {}).get('message', str(result1))}"}

    container_id = result1["id"]

    # Paso 2: Esperar que esté listo
    for _ in range(MAX_IG_CONTAINER_RETRIES):
        sr = requests.get(
            f"{GRAPH_API_BASE}/{container_id}",
            params={"fields": "status_code", "access_token": page_token}
        )
        status = sr.json().get("status_code", "")
        if status == "FINISHED":
            break
        elif status == "ERROR":
            return {"error": f"Container ERROR: {sr.json()}"}
        time.sleep(IG_CONTAINER_POLL_INTERVAL)

    # Paso 3: Publicar
    r2 = requests.post(
        f"{GRAPH_API_BASE}/{ig_id}/media_publish",
        data={"creation_id": container_id, "access_token": page_token}
    )
    result2 = r2.json()
    if "id" in result2:
        return {"success": True, "media_id": result2["id"]}
    return {"error": f"Publish: {result2.get('error', {}).get('message', str(result2))}"}


# ------------------------------------------------------------------ #
#  STEP 6 — RESUMEN FINAL
# ------------------------------------------------------------------ #

def step_resumen(config: dict):
    """Muestra el resumen final de toda la campaña."""
    banner("RESUMEN FINAL", 6)

    nombre = config.get("nombre", "")
    tematica = config.get("tematica", "")
    carpeta = config.get("carpeta", "")
    evaluaciones = config.get("evaluaciones", [])
    aprobadas = config.get("aprobadas", [])
    resultados = config.get("resultados_publicacion", [])

    print(f"  📋 Campaña: {c(nombre, 'cyan')}")
    print(f"  🎯 Temática: {c(tematica, 'dim')}")
    print(f"  📁 Carpeta: {c(carpeta, 'dim')}")
    print()

    # Imágenes
    total = len(evaluaciones)
    n_aprobadas = len(aprobadas)
    n_rechazadas = sum(1 for e in evaluaciones if "rechazada" in e.get("estado", ""))
    n_eliminadas = sum(1 for e in evaluaciones if e.get("estado") == "eliminada")

    print(c("  ─── IMÁGENES ───", "bold"))
    print(f"    Generadas:   {total}")
    print(f"    Aprobadas:   {c(str(n_aprobadas), 'green')}")
    print(f"    Rechazadas:  {c(str(n_rechazadas), 'red')}")
    print(f"    Eliminadas:  {c(str(n_eliminadas), 'red')}")

    if aprobadas:
        prom = sum(e["puntaje"] for e in aprobadas) / len(aprobadas)
        print(f"    Promedio:    {c(f'{prom:.0f}/100', 'yellow')}")

    # Publicaciones
    if resultados:
        print()
        print(c("  ─── PUBLICACIONES ───", "bold"))

        fb_ok = sum(1 for r in resultados if r.get("fb") and not str(r["fb"]).startswith("ERROR"))
        ig_ok = sum(1 for r in resultados if r.get("ig") and not str(r["ig"]).startswith("ERROR"))
        fb_total = sum(1 for r in resultados if r.get("fb") is not None)
        ig_total = sum(1 for r in resultados if r.get("ig") is not None)

        if fb_total:
            print(f"    📘 Facebook:  {c(str(fb_ok), 'green')}/{fb_total}")
        if ig_total:
            print(f"    📸 Instagram: {c(str(ig_ok), 'green')}/{ig_total}")

        print()
        print(c("  #   Producto          Formato           FB       IG", "bold"))
        print(c("  " + "─" * 65, "dim"))
        for r in resultados:
            nombre_prod = PRODUCTOS[r["producto"]]["nombre"]
            fb_st = c("✅", "green") if r.get("fb") and not str(r["fb"]).startswith("ERROR") else c("❌", "red") if r.get("fb") else c("──", "dim")
            ig_st = c("✅", "green") if r.get("ig") and not str(r["ig"]).startswith("ERROR") else c("❌", "red") if r.get("ig") else c("──", "dim")
            print(f"      {nombre_prod:18s} {r['formato']:18s} {fb_st}       {ig_st}")

    # Guardar metadata final
    meta_path = os.path.join(carpeta, "campana_resultado.json") if carpeta else None
    if meta_path:
        try:
            meta = {
                "nombre": nombre,
                "tematica": tematica,
                "carpeta": carpeta,
                "fecha": datetime.now().isoformat(),
                "imagenes_total": total,
                "imagenes_aprobadas": n_aprobadas,
                "imagenes_rechazadas": n_rechazadas,
                "imagenes_eliminadas": n_eliminadas,
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
            print(f"\n  💾 Metadata guardada: {c(meta_path, 'dim')}")
        except Exception as e:
            print(c(f"  ⚠ Error guardando metadata: {e}", "dim"))

    print()
    print(c("  🎉 ¡Campaña completada!", "green"))
    print()


# ------------------------------------------------------------------ #
#  MAIN — Orquestador
# ------------------------------------------------------------------ #

def main():
    """Ejecuta el pipeline completo step-by-step."""
    print()
    print(c("╔══════════════════════════════════════════════════════════════════╗", "magenta"))
    print(c("║      HUMANIZAR SYSTEMS — CAMPAÑA INTERACTIVA v1.0              ║", "magenta"))
    print(c("║      Pipeline: Generar → Evaluar → Revisar → Publicar         ║", "magenta"))
    print(c("╚══════════════════════════════════════════════════════════════════╝", "magenta"))

    try:
        # STEP 1: Configurar
        config = step_configurar()

        # STEP 2: Generar imágenes
        config = step_generar(config)

        # STEP 3: Evaluación IA
        if pregunta_si_no("\n  ¿Ejecutar evaluación automática con IA?"):
            config = step_evaluar(config)
        else:
            # Crear evaluaciones mínimas desde campana_meta
            evaluaciones = []
            for prod_key, imgs in config.get("campana_meta", {}).get("imagenes", {}).items():
                for img_info in imgs:
                    ruta = img_info.get("path", "")
                    if ruta and os.path.exists(ruta):
                        evaluaciones.append({
                            "ruta": ruta,
                            "producto": prod_key,
                            "formato": img_info.get("formato", ""),
                            "archivo": os.path.basename(ruta),
                            "puntaje": 0,
                            "veredicto": "NO_EVALUADA",
                            "resumen": "",
                            "feedback": "",
                            "defectos": [],
                            "marcas_terceros": [],
                            "detalles": {},
                            "estado": "aprobada_ia",  # asumir OK sin eval
                        })
            config["evaluaciones"] = evaluaciones

        # STEP 4: Revisión humana
        config = step_revision_humana(config)

        # STEP 5: Publicar
        aprobadas = config.get("aprobadas", [])
        if aprobadas:
            if pregunta_si_no(f"\n  ¿Publicar {len(aprobadas)} imágenes aprobadas en redes?"):
                config = step_publicar(config)
            else:
                print(c("  Publicación omitida. Las imágenes están en la carpeta de campaña.", "dim"))
        else:
            print(c("\n  No hay imágenes aprobadas para publicar.", "yellow"))

        # STEP 6: Resumen
        step_resumen(config)

    except KeyboardInterrupt:
        print(c("\n\n  ⏹ Cancelado por el usuario (Ctrl+C).", "yellow"))
        sys.exit(1)
    except Exception as e:
        logger.error("Error en el pipeline: %s", e, exc_info=True)
        print(c(f"\n  ❌ Error inesperado: {e}", "red"))
        sys.exit(1)


if __name__ == "__main__":
    main()
