"""
config.py — Configuración centralizada del Marketing Autopilot.

Constantes compartidas, setup de logging, modelos de datos,
y utilidades de retry para todo el pipeline.
"""

import os
import sys
import logging
import time
import functools
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv

# ------------------------------------------------------------------ #
#  PATHS
# ------------------------------------------------------------------ #

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = Path(__file__).resolve().parent
ENV_PATH = PROJECT_ROOT / ".env"
OUTPUT_DIR = PROJECT_ROOT / "output"
IMAGES_DIR = OUTPUT_DIR / "imagenes"
CAMPAIGNS_DIR = OUTPUT_DIR / "campanas"
QUEUE_DIR = OUTPUT_DIR / "queue"
LOG_DIR = OUTPUT_DIR / "logs"

# Repositorios hermanos
PRIZMA_DOCS_DIR = PROJECT_ROOT.parent.parent / "HumanizarDocs"
BRAND_ASSETS_DIR = PRIZMA_DOCS_DIR / "Imagen de marca"
SCREENSHOTS_DIR = BRAND_ASSETS_DIR / "capturas"
NARRATIVA_PATH = BRAND_ASSETS_DIR / "NARRATIVA_MARCA.md"

# Crear directorios necesarios
for _dir in [OUTPUT_DIR, IMAGES_DIR, CAMPAIGNS_DIR, QUEUE_DIR, LOG_DIR]:
    _dir.mkdir(parents=True, exist_ok=True)

# ------------------------------------------------------------------ #
#  CARGAR .ENV
# ------------------------------------------------------------------ #

load_dotenv(ENV_PATH)

# ------------------------------------------------------------------ #
#  META API — Constantes compartidas
# ------------------------------------------------------------------ #

GRAPH_API_VERSION = "v24.0"
GRAPH_API_BASE = f"https://graph.facebook.com/{GRAPH_API_VERSION}"

# IDs y credenciales (leídas de .env)
META_APP_ID = os.getenv("META_APP_ID", "")
META_APP_SECRET = os.getenv("META_APP_SECRET", "")
META_ACCESS_TOKEN = os.getenv("META_ACCESS_TOKEN", "")
META_AD_ACCOUNT_ID = os.getenv("META_AD_ACCOUNT_ID", "")
META_PAGE_ID = os.getenv("META_PAGE_ID", "")
META_INSTAGRAM_ID = os.getenv("META_INSTAGRAM_ID", "")
META_PAGE_TOKEN = os.getenv("META_PAGE_TOKEN", "")
META_LONG_LIVED_TOKEN = os.getenv("META_LONG_LIVED_TOKEN", "")

# Gemini
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")

# ------------------------------------------------------------------ #
#  IA — Modelos por defecto
# ------------------------------------------------------------------ #

DEFAULT_COPY_MODEL = "gemini-2.0-flash"
DEFAULT_IMAGE_MODEL = "gemini-3-pro-image-preview"
FALLBACK_IMAGE_MODEL = "gemini-2.5-flash-image"
CRITIC_MODEL = "gemini-2.5-pro"

# ------------------------------------------------------------------ #
#  PUBLICACIÓN — Constantes
# ------------------------------------------------------------------ #

QUALITY_THRESHOLD = 70  # Score mínimo para auto-publicar (0-100)
MAX_IG_CONTAINER_RETRIES = 15
IG_CONTAINER_POLL_INTERVAL = 3  # segundos
PUBLISH_INTERVAL_SECONDS = 300  # 5 min entre publicaciones en lote

# Horarios óptimos de publicación (hora Colombia UTC-5)
HORARIOS_OPTIMOS = {
    "lunes": ["08:00", "12:30", "18:00"],
    "martes": ["09:00", "13:00", "19:00"],
    "miercoles": ["08:30", "12:00", "17:30"],
    "jueves": ["09:00", "13:30", "18:30"],
    "viernes": ["08:00", "12:00", "17:00"],
    "sabado": ["10:00", "14:00"],
    "domingo": ["11:00", "16:00"],
}

# Productos que reciben campañas activas
PRODUCTOS_ACTIVOS = ["emw", "graf", "talaria", "sinergia", "agora", "terminal"]

# ------------------------------------------------------------------ #
#  LOGGING — Setup centralizado
# ------------------------------------------------------------------ #

LOG_FORMAT = "%(asctime)s [%(name)s] %(levelname)s: %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
LOG_FILE = LOG_DIR / f"autopilot_{datetime.now().strftime('%Y%m%d')}.log"


def get_logger(name: str, level: int = logging.INFO) -> logging.Logger:
    """
    Crea un logger con formato consistente, salida a consola y archivo.

    Uso:
        from config import get_logger
        logger = get_logger(__name__)
        logger.info("Publicación exitosa")
        logger.error("Falló la API", exc_info=True)
    """
    logger = logging.getLogger(name)

    if logger.handlers:
        return logger

    logger.setLevel(level)

    # Consola
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(level)
    console.setFormatter(logging.Formatter(LOG_FORMAT, datefmt=LOG_DATE_FORMAT))
    logger.addHandler(console)

    # Archivo (append, rotación diaria por nombre)
    try:
        file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(logging.Formatter(LOG_FORMAT, datefmt=LOG_DATE_FORMAT))
        logger.addHandler(file_handler)
    except Exception:
        pass  # Si no puede escribir log, continuar sin archivo

    return logger


# ------------------------------------------------------------------ #
#  RETRY — Decorador con backoff exponencial
# ------------------------------------------------------------------ #

def retry(
    max_attempts: int = 3,
    base_delay: float = 2.0,
    max_delay: float = 60.0,
    exceptions: tuple = (Exception,),
    logger_name: str = "retry",
):
    """
    Decorador de retry con backoff exponencial.

    Uso:
        @retry(max_attempts=3, base_delay=2.0)
        def llamar_api():
            ...
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            log = get_logger(logger_name)
            last_exception = None

            for attempt in range(1, max_attempts + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    if attempt == max_attempts:
                        log.error(
                            "Fallo definitivo en %s después de %d intentos: %s",
                            func.__name__, max_attempts, e
                        )
                        raise
                    delay = min(base_delay * (2 ** (attempt - 1)), max_delay)
                    log.warning(
                        "Intento %d/%d de %s falló: %s. Retry en %.1fs",
                        attempt, max_attempts, func.__name__, e, delay
                    )
                    time.sleep(delay)

            raise last_exception

        return wrapper
    return decorator


# ------------------------------------------------------------------ #
#  UTM — Generador de URLs con tracking
# ------------------------------------------------------------------ #

def build_utm_url(
    base_url: str,
    source: str = "social",
    medium: str = "organic",
    campaign: str = "",
    content: str = "",
) -> str:
    """
    Construye una URL con parámetros UTM para tracking de conversiones.

    Uso:
        url = build_utm_url("https://iris.prizma.cloud",
                            campaign="lanzamiento_peitho",
                            content="post_feed_iris")
    """
    from urllib.parse import urlencode, urlparse, urlunparse, parse_qs

    parsed = urlparse(base_url)
    params = parse_qs(parsed.query)
    params["utm_source"] = [source]
    params["utm_medium"] = [medium]
    if campaign:
        params["utm_campaign"] = [campaign]
    if content:
        params["utm_content"] = [content]

    query = urlencode({k: v[0] for k, v in params.items()})
    return urlunparse(parsed._replace(query=query))


# ------------------------------------------------------------------ #
#  PRODUCTOS — Catálogo único (fuente de verdad)
# ------------------------------------------------------------------ #

PRODUCTOS = {
    "prizma": {
        "nombre": "Prizma",
        "tipo": "marca",
        "descripcion": "Ecosistema de software que conecta ventas, operación y automatización en una sola suite empresarial para pymes colombianas",
        "slogan": "Activa ventas, operación y automatización en una sola suite empresarial",
        "color_primario": "#4154f1",
        "color_secundario": "#2a2c39",
        "color_fondo": "#f6f9ff",
        "tema": "claro",
        "url": "https://prizma.cloud",
        "cta": "Empieza gratis → prizma.cloud",
        "productos_estrella": ["Graf", "EMW"],
        "logos": [
            "logos/prizma/prizma-1080-variante1.png",
            "logos/prizma/prizma-1080-variante2.png",
            "logos/prizma/prizma-arbol-blanco.png",
            "logos/prizma/prizma-v2.png",
        ],
        "screenshots": [
            "capturas/prizma/prizma-web-fullpage.png",
        ],
    },
    "emw": {
        "nombre": "EMW",
        "tipo": "producto",
        "descripcion": "Envíos masivos y personalizados por WhatsApp para activar bases de clientes, recuperar ventas y acelerar campañas",
        "slogan": "Más conversión en WhatsApp con campañas segmentadas",
        "color_primario": "#25D366",
        "color_secundario": "#128C7E",
        "color_fondo": "#ffffff",
        "tema": "claro",
        "url": "https://iris.prizma.cloud",
        "cta": "Empieza gratis → iris.prizma.cloud",
        "precio_desde": "$88.000",
        "linea": "Comercial",
        "publico_objetivo": "Equipos de ventas y marketing que necesitan captar y reactivar clientes por WhatsApp",
        "logos": [
            "logos/emw/emw-color-sin-fondo.png",
            "logos/emw/emw-color.png",
            "logos/emw/emw-icono.png",
            "logos/emw/emw-oscuro-sin-fondo.png",
        ],
        "screenshots": [
            "capturas/emw/emw-app.png",
            "capturas/emw/emw-fullpage.png",
            "capturas/emw/emw-login.png",
        ],
    },
    "graf": {
        "nombre": "Graf",
        "tipo": "producto",
        "descripcion": "Catálogo y carrito conectado a WhatsApp para vender con procesos simples, rápidos y medibles",
        "slogan": "Más pedidos cerrados con catálogo y carrito conversacional",
        "color_primario": "#28a745",
        "color_secundario": "#212529",
        "color_fondo": "#ffffff",
        "tema": "claro",
        "url": "https://www.graf.com.co/graf",
        "cta": "Empieza gratis → graf.com.co",
        "precio_desde": "$30.000/mes",
        "linea": "Comercial",
        "publico_objetivo": "Dueños de negocios que venden por WhatsApp y necesitan orden en pedidos y catálogo digital",
        "logos": [
            "logos/graf/graf-total-pedido-ancho.png",
            "logos/graf/graf-color-sin-fondo.png",
            "logos/graf/graf-icono.png",
            "logos/graf/graf-marca-color.png",
        ],
        "screenshots": [
            "capturas/graf/graf-landing.png",
            "capturas/graf/graf-admin-dashboard.png",
            "capturas/graf/graf-fullpage.png",
            "capturas/graf/graf-register.png",
        ],
    },
    "talaria": {
        "nombre": "Talaria",
        "tipo": "producto",
        "descripcion": "Asignación automática de domiciliarios, seguimiento de pedidos y reportes operativos de cada entrega",
        "slogan": "Entregas más rápidas con trazabilidad por pedido",
        "color_primario": "#f1c40f",
        "color_secundario": "#003049",
        "color_fondo": "#ffffff",
        "tema": "claro",
        "url": "https://www.prizma.cloud",
        "cta": "Empieza gratis → www.prizma.cloud",
        "precio_desde": "$49.500/mes",
        "linea": "Operación",
        "publico_objetivo": "Negocios con domicilios que necesitan organizar entregas y asignar domiciliarios",
        "logos": [
            "logos/talaria/talaria-ancho.png",
            "logos/talaria/talaria-icono.png",
            "logos/talaria/talaria-movil.png",
        ],
        "screenshots": [
            "capturas/talaria/talaria-app.png",
            "capturas/talaria/talaria-fullpage.png",
        ],
    },
    "sinergia": {
        "nombre": "Sinergia POS",
        "tipo": "producto",
        "descripcion": "POS para control de ventas e inventario en tienda física con operación estable para el día a día",
        "slogan": "Caja e inventario ordenados en tiempo real",
        "color_primario": "#6366f1",
        "color_secundario": "#a78bfa",
        "color_fondo": "#1a1b2e",
        "tema": "oscuro",
        "url": "https://www.sinergia-pos.com",
        "cta": "Empieza gratis → sinergia-pos.com",
        "precio_desde": "$10/mes",
        "linea": "Operación",
        "publico_objetivo": "Tiendas y comercios que necesitan control de caja, inventario y facturación",
        "logos": [
            "logos/sinergia/sinergia-ancho.png",
            "logos/sinergia/sinergia-icono.png",
            "logos/sinergia/sinergia-color.png",
            "logos/sinergia/sinergia-oscuro-sin-fondo.png",
        ],
        "screenshots": [
            "capturas/sinergia/sinergia-app.png",
            "capturas/sinergia/sinergiapos-fullpage.png",
        ],
    },
    "agora": {
        "nombre": "Agora",
        "tipo": "producto",
        "descripcion": "Editor, terminal Linux y espacios colaborativos en la nube para equipos técnicos, académicos y empresariales",
        "slogan": "Equipos coordinados en un solo workspace cloud",
        "color_primario": "#ff9800",
        "color_secundario": "#ffa726",
        "color_fondo": "#121212",
        "tema": "oscuro",
        "url": "https://agora.prizma.cloud",
        "cta": "Empieza gratis → agora.prizma.cloud",
        "precio_desde": "$30.000/mes",
        "linea": "Productividad",
        "publico_objetivo": "Equipos técnicos, academias y empresas que necesitan workspace colaborativo en la nube",
        "logos": [
            "logos/agora/agora-icono.png",
        ],
        "screenshots": [
            "capturas/agora/agora-landing.png",
            "capturas/agora/agora-login.png",
            "capturas/agora/agora-app.png",
            "capturas/agora/agora-fullpage.png",
        ],
    },
    "terminal": {
        "nombre": "Terminal",
        "tipo": "producto",
        "descripcion": "Cliente web para administrar workers y terminales remotas en entornos de soporte y operación avanzada",
        "slogan": "Soporte técnico más ágil en entornos remotos",
        "color_primario": "#009688",
        "color_secundario": "#4db6ac",
        "color_fondo": "#121212",
        "tema": "oscuro",
        "url": "https://terminal.prizma.cloud",
        "cta": "Empieza gratis → terminal.prizma.cloud",
        "precio_desde": "$10/mes",
        "linea": "Productividad",
        "publico_objetivo": "Equipos de soporte técnico y operaciones que necesitan acceso remoto a servidores",
        "logos": [
            "logos/terminal/terminal-icono.png",
        ],
        "screenshots": [
            "capturas/terminal/terminal-landing.png",
            "capturas/terminal/terminal-fullpage.png",
        ],
    },
    "fiar": {
        "nombre": "Fiar",
        "tipo": "producto",
        "descripcion": "Gestión digital de créditos y préstamos para negocios que requieren trazabilidad y control de cartera",
        "slogan": "Control de cobro y cartera en un flujo digital",
        "color_primario": "#58a399",
        "color_secundario": "#06d6a0",
        "color_fondo": "#f5eedc",
        "tema": "claro",
        "url": "https://pistis.prizma.cloud",
        "cta": "Empieza gratis → pistis.prizma.cloud",
        "precio_desde": "Próximamente",
        "linea": "Facturación",
        "publico_objetivo": "Comercios que fían a clientes y necesitan trazabilidad digital de créditos",
        "logos": [
            "logos/fiar/fiar-icono.png",
        ],
        "screenshots": [
            "capturas/fiar/fiar-landing.png",
            "capturas/fiar/fiar-fullpage.png",
        ],
    },
}


# ------------------------------------------------------------------ #
#  VISUAL GUIDELINES (fuente única)
# ------------------------------------------------------------------ #

VISUAL_GUIDELINES = """
VISUAL BRAND GUIDELINES — PRIZMA:
- Style: tech-premium, clean, modern. NO clip-art, NO generic stock photos.
- Colombian context: if people appear, reflect real Colombian workplace diversity.
- NO mockup devices with fake screens. Prefer real workspace scenes or abstract data visualizations.
- Each product has its OWN color palette (see product config) — ALWAYS use it.
- The Prizma umbrella brand uses royal blue #4154f1 — include subtly as brand marker.
- Typography feel: Open Sans (clean body), Nunito (rounded headings).
- Light themes: white/light gray backgrounds with colored accents.
- Dark themes: deep dark backgrounds (#121212 or similar) with vibrant accents.
- Geometric patterns and data-flow visualizations are preferred decorative elements.
- Gradients should be subtle, using primary→secondary color of each product.
- NO excessive text in images. Maximum: product name + short slogan.
- Mood: professional but approachable, startup energy with enterprise reliability.
- Country context: Colombia, LATAM, tropical urban business environments.

⛔ CRITICAL — THIRD-PARTY BRAND PROHIBITION:
DO NOT include ANY logos, icons, names, or visual elements from external brands.
This includes but is not limited to: Google, Apple, Microsoft, Amazon, Meta, Facebook,
Instagram, WhatsApp icon, Hostinger, GoDaddy, Shopify, WordPress, Slack, Discord,
Visa, Mastercard, PayPal, Chrome, Android, Windows, Nike, Adidas, Uber, Rappi,
or ANY other recognizable brand that is NOT part of Prizma.
The ONLY brands allowed are: Prizma, EMW, Graf, Talaria, Sinergia POS,
Agora, Terminal, Fiar. NO EXCEPTIONS.
If you feel tempted to add a recognizable icon for context — DON'T. Use abstract shapes instead.
"""


# ------------------------------------------------------------------ #
#  PAIN POINTS (fuente única, usados por image_generator y captions)
# ------------------------------------------------------------------ #

PAIN_POINTS = {
    "emw": "People overwhelmed managing hundreds of WhatsApp contacts manually",
    "graf": "Small business owner losing orders because chat messages get buried",
    "talaria": "Delivery coordination chaos with no tracking or assignment system",
    "sinergia": "Shop owner who doesn't know daily sales totals or inventory levels",
    "agora": "Remote team struggling with disconnected tools and no shared workspace",
    "terminal": "IT support team needing remote server access without VPN complexity",
    "fiar": "Store owner lending credit to customers with no digital tracking",
}


# ------------------------------------------------------------------ #
#  CAPTIONS — Generador de captions correctos desde PRODUCTOS
# ------------------------------------------------------------------ #

def generar_caption_ig(producto_key: str) -> str:
    """
    Genera un caption de Instagram correcto basado en los datos reales
    del catálogo PRODUCTOS. Nunca usa descripciones hardcodeadas incorrectas.
    """
    prod = PRODUCTOS.get(producto_key)
    if not prod:
        return ""

    nombre = prod["nombre"]
    desc = prod["descripcion"]
    slogan = prod["slogan"]
    url = prod.get("url", "https://prizma.cloud")
    precio = prod.get("precio_desde", "")
    linea = prod.get("linea", "")

    # Estructura: gancho → solución → prueba social → CTA
    if producto_key == "prizma":
        caption = (
            "¿Cansado de saltar entre apps y perder el control de tu negocio? 🤯\n\n"
            f"{desc}.\n"
            "Más de 60 pymes colombianas ya simplificaron su día a día.\n\n"
            f"¡Conoce el ecosistema Prizma! 👉 {url}\n\n"
            "#pymescolombia #emprendimientocolombiano #softwareparapymes "
            "#gestionempresarial #transformaciondigital"
        )
    else:
        precio_line = f"\nDesde {precio}. " if precio and precio != "Próximamente" else "\n"
        caption = (
            f"{slogan} 🚀\n\n"
            f"{desc}.{precio_line}\n"
            f"Más de 60 pymes colombianas ya lo usan 💼\n\n"
            f"Conoce más 👉 {url}\n\n"
            f"#pymescolombia #{nombre.lower().replace(' ', '')} "
            f"#softwareparapymes #emprendimiento #{linea.lower() if linea else 'tecnologia'}"
        )

    return caption
