"""
image_critic.py — Crítico visual de imágenes de marca con IA.

Segundo paso del pipeline de generación:
  1. image_generator.py genera las imágenes (primer paso)
  2. image_critic.py las evalúa y regenera las que no cumplan (segundo paso)

Usa Gemini 2.0 Flash (visión) como juez rápido y barato.
Evalúa cada imagen contra la identidad visual del producto y una rúbrica de 5 criterios.
Las imágenes rechazadas se mueven a _rejected/ y se regeneran con feedback del crítico.

Uso:
  python3 -m src.image_critic --todos                   # evalúa todo
  python3 -m src.image_critic --todos --regenerar        # evalúa y regenera las que fallen
  python3 -m src.image_critic --producto prizma           # solo un producto
  python3 -m src.image_critic --umbral 75                # puntaje mínimo personalizado
  python3 -m src.image_critic --max-intentos 3           # máximo intentos de regeneración
"""

import os
import re
import json
import shutil
from datetime import datetime
from pathlib import Path
from google import genai
from google.genai import types
from PIL import Image
from dotenv import load_dotenv

from core.image_generator import ImageGenerator
from config import (
    PRODUCTOS, VISUAL_GUIDELINES,
    BRAND_ASSETS_DIR as _BRAND_ASSETS_DIR,
    IMAGES_DIR as _IMAGES_DIR,
    CRITIC_MODEL, get_logger,
)

BRAND_ASSETS_DIR = str(_BRAND_ASSETS_DIR)
OUTPUT_DIR = str(_IMAGES_DIR)

load_dotenv()

logger_critic = get_logger("image_critic")
client = genai.Client(api_key=os.getenv("GOOGLE_API_KEY"))

# Modelo de visión importado desde config (CRITIC_MODEL)

# ------------------------------------------------------------------ #
#  RÚBRICA DE EVALUACIÓN
# ------------------------------------------------------------------ #
RUBRICA = """
Eres un director de arte senior especializado en branding digital para startups de tecnología
Y un inspector de marcas comerciales especializado en detectar logos y brandings de terceros.

Tu trabajo es evaluar imágenes de marketing para redes sociales (Facebook/Instagram).
Debes ser MUY ESTRICTO con:
  1. La calidad del texto renderizado — es el defecto más común en IA generativa.
  2. La presencia de CUALQUIER logo, favicon, icono o marca de terceros.

EVALÚA la imagen según estos 5 criterios. Puntúa cada uno de 0 a 20 (total máximo = 100):

1. **COLORES Y PALETA** (0-20)
   - ¿Usa los colores de marca del producto indicado?
   - ¿El contraste es adecuado? ¿Los textos son legibles sobre el fondo?
   - ¿La paleta transmite la identidad correcta (tech-premium, profesional)?
   - 0 = colores totalmente incorrectos. 20 = paleta perfecta y coherente.

2. **TEXTO Y TIPOGRAFÍA** (0-20) ⚠️ CRITERIO CRÍTICO — SÉ MUY ESTRICTO
   Lee CADA palabra visible en la imagen y verifica TODO lo siguiente:
   a) DUPLICADOS: ¿Hay alguna palabra, frase o línea de texto que aparezca repetida 2 o más veces?
      → Si el slogan, nombre del producto, o CTA aparece duplicado = máximo 5 puntos.
   b) CARACTERES ROTOS: ¿Hay letras deformadas, gibberish, o caracteres sin sentido?
      → Cualquier carácter corrupto o ilegible = máximo 5 puntos.
   c) ORTOGRAFÍA: ¿Hay errores ortográficos o palabras inventadas?
      → Nombres de producto mal escritos = máximo 5 puntos.
   d) LEGIBILIDAD: ¿El texto es legible? ¿No está cortado, superpuesto o tapado?
      → Texto parcialmente oculto o ilegible = máximo 8 puntos.
   e) CANTIDAD: ¿Hay demasiado texto? (máximo recomendado: nombre + slogan + CTA)
      → Texto excesivo que satura = máximo 10 puntos.
   f) COHERENCIA: ¿El texto dice lo que debería decir según el producto?
      → Texto que no corresponde al producto o marca = máximo 5 puntos.
   g) IDIOMA: ¿El texto está en el idioma correcto (español o inglés según contexto)?
      → Mezcla de idiomas sin sentido = máximo 8 puntos.

   ⛔ Si hay texto duplicado, caracteres rotos, o palabras inventadas: PUNTAJE MÁXIMO 5/20.
   0 = texto ilegible/duplicado/corrupto. 20 = texto perfecto, sin duplicados, bien integrado.

3. **COMPOSICIÓN Y DISEÑO** (0-20)
   - ¿La composición es profesional y equilibrada?
   - ¿Respeta el aspect ratio esperado (1:1 feed, 9:16 story, 16:9 banner)?
   - ¿No hay elementos cortados, distorsionados o mal alineados?
   - ¿El espacio negativo se usa correctamente?
   - 0 = caótico/amateur. 20 = composición profesional impecable.

4. **LOGO E IDENTIDAD** (0-20)
   - ¿El logo está presente cuando corresponde (feed, story, banner)?
   - ¿Se ve claro, no distorsionado, bien integrado en el diseño?
   - ¿NO se inventó un logo falso (hallucination)?
   - Para imágenes promo (sin logo): ¿la escena comunica el producto correcto?
   - 0 = logo inventado/ausente cuando debería estar. 20 = logo perfecto.

5. **IMPACTO PARA REDES SOCIALES** (0-20)
   - ¿Llamaría la atención en un feed de Instagram/Facebook?
   - ¿Es visualmente atractiva para el público objetivo (pymes colombianas)?
   - ¿Transmite profesionalismo y confianza?
   - ¿Genera curiosidad o engagement?
   - 0 = ignorable/amateur. 20 = scroll-stopper profesional.

⚠️ **VALIDACIÓN DE MARCAS DE TERCEROS — PARTE INTEGRAL DE ESTA EVALUACIÓN**:
   Examina TODA la imagen con máximo detalle buscando logos, iconos, o nombres de marcas externas.
   Los modelos de IA generativa frecuentemente insertan logos/iconos de marcas conocidas por error.
   Esta validación se hace EN UNA SOLA PASADA (no separada).

   🔎 **ZONA DE ALTO RIESGO — PANTALLAS Y MOCKUPS**:
   Si la imagen contiene laptops, monitores, teléfonos, tablets u CUALQUIER pantalla:
   → EXAMINA CADA PÍXEL de la pantalla renderizada.
   → Busca en: barras de navegador, pestañas, barras de tareas, docks, toolbars,
      esquinas de la pantalla, íconos de apps, favicons, barras de estado.
   → Los favicons son MUY PEQUEÑOS (16x16 px) pero CUENTAN como violación.
   → Busca formas/colores reconocibles aunque estén borrosos o parcialmente visibles.
   → Un dashboard o interfaz genérica con CUALQUIER branding real = RECHAZO.

   📋 **FIRMAS VISUALES DE MARCAS COMUNES** (busca estas formas/colores):
   - Hostinger: cuadrado azul/púrpura con "H" blanca, favicon morado con "H"
   - Google: "G" multicolor (rojo/amarillo/verde/azul), Chrome = círculo tricolor
   - Apple: silueta de manzana mordida
   - Microsoft: ventana de 4 colores (rojo/verde/azul/amarillo)
   - Windows: icono de ventana azul, barra de inicio
   - Amazon: flecha naranja de A→Z, sonrisa
   - Meta/Facebook: "f" blanca en azul, icono de Messenger
   - Instagram: gradiente púrpura/naranja con cámara
   - WhatsApp: burbuja verde con teléfono blanco
   - GoDaddy: corazón verde, tipografía característica
   - Cloudflare: nube naranja, escudo
   - AWS: sonrisa naranja
   - Shopify: bolsa verde con "S"
   - WordPress: "W" en círculo
   - Slack: almohadilla multicolor
   - Discord: gamepad/controlador púrpura
   - GitHub: gato octocat negro
   - Docker: ballena azul con containers
   - Twitter/X: pájaro azul, o "X" en negro
   - YouTube: triángulo play rojo
   - LinkedIn: "in" azul
   - Nike: swoosh/check curvo
   - Chrome: círculo rojo/amarillo/verde con centro azul
   - Firefox: zorro naranja envolviendo globo
   - Figma: cuadrados multicolor
   - Canva: gradiente con "C"

   📋 **LISTA COMPLETA DE MARCAS PROHIBIDAS** (busca nombres Y logos):
   Google, Apple, Microsoft, Amazon, Meta, Facebook, Instagram, WhatsApp,
   Hostinger, GoDaddy, Cloudflare, DigitalOcean, AWS, Azure, Vercel, Netlify,
   Shopify, WordPress, WooCommerce, Mercado Libre, Rappi, iFood,
   Slack, Discord, Zoom, Teams, Notion, Trello, Jira, GitHub, GitLab,
   Samsung, Xiaomi, Huawei, Android, iOS, Chrome, Firefox, Safari,
   Visa, Mastercard, PayPal, Stripe, Nequi, Daviplata, PSE,
   Coca-Cola, Nike, Adidas, o CUALQUIER otra marca reconocible que NO sea Prizma ni sus productos.

   Incluye también: favicons (aunque sean DIMINUTOS), app icons, brand shapes reconocibles,
   colores corporativos en contexto de marca, barras de navegador con logos reales.

   ⛔ Si detectas CUALQUIER marca, logo, favicon o icono de terceros → RECHAZO INMEDIATO.
   ⛔ Ante la DUDA de si algo es un logo de tercero → REPORTA como detectado.
   Reporta CADA marca detectada en el campo "marcas_terceros".

REGLAS DE AUTO-RECHAZO (independiente del puntaje total):
- Si el texto tiene duplicados → RECHAZADA obligatoria.
- Si hay caracteres rotos/gibberish → RECHAZADA obligatoria.
- Si el nombre del producto está mal escrito → RECHAZADA obligatoria.
- Si hay CUALQUIER logo, icono o nombre de marca de terceros visible → RECHAZADA obligatoria.

RESPONDE EXCLUSIVAMENTE en JSON válido, sin bloques markdown, con esta estructura exacta:
{
  "colores": {"puntaje": N, "observacion": "..."},
  "texto": {"puntaje": N, "observacion": "..."},
  "composicion": {"puntaje": N, "observacion": "..."},
  "logo": {"puntaje": N, "observacion": "..."},
  "impacto": {"puntaje": N, "observacion": "..."},
  "puntaje_total": N,
  "veredicto": "APROBADA" | "RECHAZADA",
  "defectos_criticos": ["lista de defectos graves encontrados, vacía si no hay"],
  "textos_encontrados": ["lista literal de CADA texto/palabra visible en la imagen"],
  "marcas_terceros": ["lista de marcas/logos/iconos de terceros detectados, vacía si no hay"],
  "tiene_pantalla": true|false,
  "zonas_sospechosas": ["descripción de zonas donde viste algo sospechoso, vacía si no hay"],
  "resumen": "Una oración con el veredicto general",
  "feedback_regeneracion": "Instrucciones específicas para mejorar la imagen si se regenera (vacío si aprobada)"
}
"""


# ------------------------------------------------------------------ #
#  CLASE PRINCIPAL
# ------------------------------------------------------------------ #
class ImageCritic:
    def __init__(self, umbral: int = 70, max_intentos: int = 2):
        """
        umbral: puntaje mínimo para aprobar (0-100, default 70)
        max_intentos: cuántas veces intentar regenerar una imagen rechazada
        """
        self.umbral = umbral
        self.max_intentos = max_intentos
        self.generator = ImageGenerator()  # usa el modelo Pro por default
        self._resultados: list[dict] = []

    # ------------------------------------------------------------------ #
    #  EVALUAR UNA IMAGEN
    # ------------------------------------------------------------------ #
    def evaluar_imagen(self, ruta_imagen: str, producto_key: str, formato: str = "") -> dict:
        """
        Evalúa una imagen contra los estándares de marca del producto.
        
        Args:
            ruta_imagen: ruta absoluta a la imagen PNG
            producto_key: clave del producto en PRODUCTOS (ej: 'prizma', 'emw')
            formato: tipo de imagen ('feed_1x1', 'story_9x16', 'banner_16x9', 'promo_1x1')
        
        Returns:
            dict con puntajes, veredicto, y feedback
        """
        if not os.path.exists(ruta_imagen):
            return {"error": f"Imagen no encontrada: {ruta_imagen}", "puntaje_total": 0}

        prod = PRODUCTOS.get(producto_key, {})
        if not prod:
            return {"error": f"Producto '{producto_key}' no existe", "puntaje_total": 0}

        # Detectar formato del nombre del archivo si no se especificó
        if not formato:
            nombre = os.path.basename(ruta_imagen).lower()
            if "feed_1x1" in nombre:
                formato = "feed_1x1"
            elif "story_9x16" in nombre:
                formato = "story_9x16"
            elif "banner_16x9" in nombre:
                formato = "banner_16x9"
            elif "promo_1x1" in nombre:
                formato = "promo_1x1"
            else:
                formato = "desconocido"

        # Contexto del producto para el crítico
        contexto = (
            f"PRODUCTO: {prod['nombre']}\n"
            f"Descripción: {prod['descripcion']}\n"
            f"Slogan: {prod['slogan']}\n"
            f"Color primario: {prod['color_primario']}\n"
            f"Color secundario: {prod['color_secundario']}\n"
            f"Color fondo: {prod.get('color_fondo', '#ffffff')}\n"
            f"Tema: {prod.get('tema', 'claro')}\n"
            f"Línea: {prod.get('linea', 'marca')}\n"
            f"Formato de imagen: {formato}\n"
            f"{'La imagen NO debe tener logo (es promo/escena)' if 'promo' in formato else 'La imagen DEBE incluir el logo real del producto'}\n"
        )

        prompt_evaluacion = (
            f"{RUBRICA}\n\n"
            f"=== CONTEXTO DEL PRODUCTO ===\n{contexto}\n"
            f"=== GUIDELINES VISUALES ===\n{VISUAL_GUIDELINES}\n\n"
            f"Evalúa la imagen adjunta según la rúbrica. "
            f"El umbral de aprobación es {self.umbral}/100."
        )

        # Cargar imagen
        try:
            img = Image.open(ruta_imagen)
        except Exception as e:
            return {"error": f"No se pudo abrir la imagen: {e}", "puntaje_total": 0}

        # Enviar a Gemini Vision
        try:
            response = client.models.generate_content(
                model=CRITIC_MODEL,
                contents=[prompt_evaluacion, img],
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=0.2,  # Bajo para consistencia en evaluación
                ),
            )

            # Parsear respuesta JSON
            raw = response.text.strip()
            # Limpiar posibles bloques markdown
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[1]
                if raw.endswith("```"):
                    raw = raw[:-3]
            resultado = json.loads(raw)

        except json.JSONDecodeError as e:
            print(f"⚠️  Error parseando evaluación para {ruta_imagen}: {e}")
            print(f"   Respuesta raw: {response.text[:200]}")
            return {"error": f"JSON inválido: {e}", "puntaje_total": 0}
        except Exception as e:
            print(f"⚠️  Error evaluando {ruta_imagen}: {e}")
            return {"error": str(e), "puntaje_total": 0}

        # Enriquecer resultado con metadata
        resultado["archivo"] = os.path.basename(ruta_imagen)
        resultado["ruta"] = ruta_imagen
        resultado["producto"] = producto_key
        resultado["formato"] = formato

        # Asegurar que campos de validación de marcas estén presentes
        # (el modelo debe incluirlos, pero ser defensivo ante respuestas parciales)
        if "tiene_pantalla" not in resultado:
            resultado["tiene_pantalla"] = False
        if "zonas_sospechosas" not in resultado:
            resultado["zonas_sospechosas"] = []

        # --- AUTO-RECHAZO por defectos críticos de texto ---
        defectos = resultado.get("defectos_criticos", [])
        texto_puntaje = resultado.get("texto", {}).get("puntaje", 20)
        auto_rechazada = False

        # Defecto crítico explícito reportado por el modelo
        if defectos and len(defectos) > 0:
            auto_rechazada = True

        # Puntaje de texto demasiado bajo = defecto grave
        if texto_puntaje <= 10:
            auto_rechazada = True
            if "Puntaje de texto <= 10" not in defectos:
                defectos.append(f"Puntaje de texto muy bajo: {texto_puntaje}/20")

        # Detectar duplicados en textos_encontrados
        textos = resultado.get("textos_encontrados", [])
        if textos:
            textos_lower = [t.strip().lower() for t in textos if t.strip()]
            vistos = set()
            for t in textos_lower:
                if t in vistos and len(t) > 2:  # ignorar artículos cortos
                    auto_rechazada = True
                    msg = f"Texto duplicado detectado: '{t}'"
                    if msg not in defectos:
                        defectos.append(msg)
                vistos.add(t)

        # --- AUTO-RECHAZO por marcas de terceros ---
        marcas_terceros = resultado.get("marcas_terceros", [])
        if marcas_terceros and len(marcas_terceros) > 0:
            auto_rechazada = True
            for marca in marcas_terceros:
                msg = f"⛔ Marca de tercero detectada: '{marca}'"
                if msg not in defectos:
                    defectos.append(msg)

        # Verificar también en textos_encontrados contra lista de marcas prohibidas
        MARCAS_PROHIBIDAS = {
            "google", "apple", "microsoft", "amazon", "meta", "facebook",
            "instagram", "whatsapp", "hostinger", "godaddy", "cloudflare",
            "digitalocean", "aws", "azure", "vercel", "netlify", "heroku",
            "shopify", "wordpress", "woocommerce", "mercado libre", "mercadolibre",
            "rappi", "ifood", "uber", "didi", "slack", "discord", "zoom",
            "teams", "notion", "trello", "jira", "github", "gitlab",
            "samsung", "xiaomi", "huawei", "android", "chrome", "firefox",
            "safari", "visa", "mastercard", "paypal", "stripe", "nequi",
            "daviplata", "pse", "coca-cola", "nike", "adidas", "twitter",
            "tiktok", "youtube", "linkedin", "pinterest", "snapchat",
            "windows", "linux", "ubuntu", "docker", "kubernetes",
            "openai", "chatgpt", "gemini", "claude", "copilot",
            "figma", "canva", "adobe", "photoshop", "illustrator",
            "intercom", "hubspot", "salesforce", "mailchimp", "sendgrid",
        }
        if textos:
            for t in textos_lower:
                # Buscar marcas en cada texto usando word boundaries (evita falsos positivos)
                for marca in MARCAS_PROHIBIDAS:
                    if marca not in {"graf", "emw", "fiar", "agora", "terminal", "sinergia", "prizma", "talaria"}:
                        # Usar word boundary regex para evitar substrings: 'hostinger' no rechaza 'hostile'
                        pattern = r'\b' + re.escape(marca) + r'\b'
                        if re.search(pattern, t):
                            auto_rechazada = True
                            msg = f"⛔ Texto contiene marca prohibida: '{marca}' encontrada en '{t}'"
                            if msg not in defectos:
                                defectos.append(msg)

        # --- Búsqueda de marcas en TODAS las observaciones del modelo ---
        campos_observacion = [
            resultado.get("colores", {}).get("observacion", ""),
            resultado.get("texto", {}).get("observacion", ""),
            resultado.get("composicion", {}).get("observacion", ""),
            resultado.get("logo", {}).get("observacion", ""),
            resultado.get("impacto", {}).get("observacion", ""),
            resultado.get("resumen", ""),
            resultado.get("feedback_regeneracion", ""),
        ]
        texto_completo = " ".join(campos_observacion).lower()
        for marca in MARCAS_PROHIBIDAS:
            if marca not in {
                "graf", "emw", "fiar", "agora", "terminal",
                "sinergia", "prizma", "talaria",
            }:
                # Usar word boundary regex para evitar falsos positivos
                pattern = r'\b' + re.escape(marca) + r'\b'
                if re.search(pattern, texto_completo):
                    auto_rechazada = True
                    msg = f"⛔ Marca mencionada en observaciones: '{marca}'"
                    if msg not in defectos:
                        defectos.append(msg)

        resultado["defectos_criticos"] = defectos
        resultado["auto_rechazada"] = auto_rechazada

        # Forzar veredicto: auto-rechazo supera el umbral
        total = resultado.get("puntaje_total", 0)
        if auto_rechazada:
            resultado["veredicto"] = "RECHAZADA"
        else:
            resultado["veredicto"] = "APROBADA" if total >= self.umbral else "RECHAZADA"

        # --- VALIDACIÓN DE MARCAS INCLUIDA EN RÚBRICA ÚNICA ---
        # La detección de marcas de terceros se realiza DENTRO del mismo prompt de evaluación.
        # No hay llamada extra a Gemini. Esto reduce de 64 calls a 32 (8 productos × 4 formatos).
        # Los campos "tiene_pantalla", "zonas_sospechosas" y "marcas_terceros" se rellenan
        # en la respuesta del primer (y único) generate_content().
        # Ver línea 52: rúbrica integrada combina evaluación + validación de marcas.

        # Verificar si la respuesta indicó pantallas sospechosas sin marcas confirmadas
        zonas = resultado.get("zonas_sospechosas", [])
        if zonas and not marcas_terceros:
            logger_critic.info(
                "Zonas sospechosas detectadas en %s pero sin marcas confirmadas: %s",
                os.path.basename(ruta_imagen), zonas,
            )

        return resultado

    # ------------------------------------------------------------------ #
    #  EVALUAR PAQUETE (todas las imágenes de un producto)
    # ------------------------------------------------------------------ #
    def evaluar_paquete(self, producto_key: str) -> list[dict]:
        """Evalúa todas las imágenes de un producto."""
        carpeta = os.path.join(OUTPUT_DIR, producto_key)
        if not os.path.isdir(carpeta):
            print(f"❌ Carpeta no encontrada: {carpeta}")
            return []

        imagenes = sorted(
            [f for f in os.listdir(carpeta) if f.lower().endswith(".png")],
        )

        if not imagenes:
            print(f"⚠️  Sin imágenes en {carpeta}")
            return []

        print(f"\n🔍 Evaluando paquete '{producto_key}' ({len(imagenes)} imágenes)")
        print("=" * 60)

        resultados = []
        for img_name in imagenes:
            ruta = os.path.join(carpeta, img_name)
            print(f"\n   📸 {img_name}...")
            resultado = self.evaluar_imagen(ruta, producto_key)

            if "error" in resultado:
                print(f"   ❌ Error: {resultado['error']}")
            else:
                emoji = "✅" if resultado["veredicto"] == "APROBADA" else "❌"
                print(f"   {emoji} {resultado['puntaje_total']}/100 — {resultado['veredicto']}")
                print(f"      Colores: {resultado['colores']['puntaje']}/20 | "
                      f"Texto: {resultado['texto']['puntaje']}/20 | "
                      f"Composición: {resultado['composicion']['puntaje']}/20 | "
                      f"Logo: {resultado['logo']['puntaje']}/20 | "
                      f"Impacto: {resultado['impacto']['puntaje']}/20")
                if resultado.get("auto_rechazada"):
                    print(f"      ⛔ AUTO-RECHAZADA por defectos críticos:")
                    for d in resultado.get("defectos_criticos", []):
                        print(f"         • {d}")
                if resultado.get("marcas_terceros"):
                    print(f"      🚫 Marcas de terceros: {resultado['marcas_terceros']}")
                if resultado.get("zonas_sospechosas"):
                    print(f"      🔍 Zonas sospechosas: {resultado['zonas_sospechosas']}")
                if resultado.get("textos_encontrados"):
                    print(f"      📝 Textos: {resultado['textos_encontrados']}")
                if resultado["veredicto"] == "RECHAZADA":
                    print(f"      💡 {resultado.get('feedback_regeneracion', '')}")

            resultados.append(resultado)

        # Resumen del paquete
        aprobadas = sum(1 for r in resultados if r.get("veredicto") == "APROBADA")
        rechazadas = sum(1 for r in resultados if r.get("veredicto") == "RECHAZADA")
        errores = sum(1 for r in resultados if "error" in r)
        prom = (sum(r.get("puntaje_total", 0) for r in resultados) / len(resultados)) if resultados else 0

        print(f"\n📊 Resumen '{producto_key}': {aprobadas}✅ {rechazadas}❌ {errores}⚠️  | Promedio: {prom:.0f}/100")

        self._resultados.extend(resultados)
        return resultados

    # ------------------------------------------------------------------ #
    #  EVALUAR TODOS LOS PRODUCTOS
    # ------------------------------------------------------------------ #
    def evaluar_todos(self) -> dict:
        """Evalúa imágenes de todos los productos que tengan carpeta."""
        resumen_global = {}
        for key in PRODUCTOS:
            carpeta = os.path.join(OUTPUT_DIR, key)
            if os.path.isdir(carpeta) and any(f.endswith(".png") for f in os.listdir(carpeta)):
                resultados = self.evaluar_paquete(key)
                aprobadas = [r for r in resultados if r.get("veredicto") == "APROBADA"]
                rechazadas = [r for r in resultados if r.get("veredicto") == "RECHAZADA"]
                resumen_global[key] = {
                    "total": len(resultados),
                    "aprobadas": len(aprobadas),
                    "rechazadas": len(rechazadas),
                    "puntaje_promedio": (
                        sum(r.get("puntaje_total", 0) for r in resultados) / len(resultados)
                    ) if resultados else 0,
                }

        # Resumen global
        print("\n" + "=" * 60)
        print("📋 REPORTE GLOBAL DE CALIDAD")
        print("=" * 60)
        total_ap = sum(v["aprobadas"] for v in resumen_global.values())
        total_re = sum(v["rechazadas"] for v in resumen_global.values())
        total_im = sum(v["total"] for v in resumen_global.values())
        for key, data in resumen_global.items():
            nombre = PRODUCTOS[key]["nombre"]
            emoji = "🟢" if data["rechazadas"] == 0 else "🟡" if data["rechazadas"] < data["total"] else "🔴"
            print(f"  {emoji} {nombre:20s} {data['aprobadas']}/{data['total']} aprobadas | "
                  f"Promedio: {data['puntaje_promedio']:.0f}/100")

        print(f"\n  TOTAL: {total_ap}/{total_im} aprobadas, {total_re} para regenerar")
        print("=" * 60)

        return resumen_global

    # ------------------------------------------------------------------ #
    #  REGENERAR RECHAZADAS
    # ------------------------------------------------------------------ #
    def regenerar_rechazadas(self, producto_key: str = None) -> dict:
        """
        Evalúa y regenera las imágenes que no pasen el umbral.
        
        Flujo por imagen rechazada:
          1. Mover original a _rejected/
          2. Regenerar con feedback del crítico como contexto adicional
          3. Re-evaluar la nueva imagen
          4. Si sigue fallando y quedan intentos, repetir
          5. Si agota intentos, mantener la mejor versión
        
        Args:
            producto_key: producto específico o None para todos
        
        Returns:
            dict con resumen de regeneraciones
        """
        # Primero evaluar
        if producto_key:
            resultados = self.evaluar_paquete(producto_key)
            productos_a_procesar = [producto_key]
        else:
            self.evaluar_todos()
            resultados = self._resultados
            productos_a_procesar = list(PRODUCTOS.keys())

        rechazadas = [r for r in resultados if r.get("veredicto") == "RECHAZADA"]
        if not rechazadas:
            print("\n🎉 Todas las imágenes pasaron la evaluación. No hay nada que regenerar.")
            return {"regeneradas": 0, "mejoradas": 0}

        print(f"\n🔄 Regenerando {len(rechazadas)} imágenes rechazadas...")
        print("=" * 60)

        # Crear carpeta de rechazadas
        rejected_dir = os.path.join(OUTPUT_DIR, "_rejected")
        os.makedirs(rejected_dir, exist_ok=True)

        stats = {"regeneradas": 0, "mejoradas": 0, "sin_mejora": 0, "detalles": []}

        for resultado in rechazadas:
            ruta_original = resultado["ruta"]
            prod_key = resultado["producto"]
            formato = resultado["formato"]
            puntaje_original = resultado["puntaje_total"]
            feedback = resultado.get("feedback_regeneracion", "")
            archivo = resultado["archivo"]

            print(f"\n   🔄 Regenerando: {archivo} (puntaje: {puntaje_original}/100)")
            if feedback:
                print(f"   💡 Feedback: {feedback[:120]}...")

            # Mover original a _rejected/ (NO borrar)
            rejected_subdir = os.path.join(rejected_dir, prod_key)
            os.makedirs(rejected_subdir, exist_ok=True)
            rejected_path = os.path.join(rejected_subdir, archivo)
            shutil.copy2(ruta_original, rejected_path)
            print(f"   📁 Original copiado a: {rejected_path}")

            # Intentar regenerar
            mejor_puntaje = puntaje_original
            mejor_ruta = ruta_original

            for intento in range(1, self.max_intentos + 1):
                print(f"\n   🎨 Intento {intento}/{self.max_intentos}...")

                nueva_ruta = self._regenerar_imagen(
                    prod_key, formato, feedback, intento
                )

                if not nueva_ruta:
                    print(f"   ⚠️  Falló la generación en intento {intento}")
                    continue

                # Evaluar la nueva imagen
                nueva_eval = self.evaluar_imagen(nueva_ruta, prod_key, formato)
                nuevo_puntaje = nueva_eval.get("puntaje_total", 0)

                emoji = "✅" if nueva_eval.get("veredicto") == "APROBADA" else "❌"
                print(f"   {emoji} Nueva imagen: {nuevo_puntaje}/100 "
                      f"(original: {puntaje_original}/100)")

                if nuevo_puntaje > mejor_puntaje:
                    # La nueva es mejor → reemplazar
                    if mejor_ruta != ruta_original:
                        os.remove(mejor_ruta)  # Eliminar versión anterior (no la original)
                    mejor_puntaje = nuevo_puntaje
                    mejor_ruta = nueva_ruta

                    if nueva_eval.get("veredicto") == "APROBADA":
                        print(f"   ✅ Imagen aprobada en intento {intento}")
                        # Eliminar la original ya que tenemos una mejor
                        if os.path.exists(ruta_original) and mejor_ruta != ruta_original:
                            os.remove(ruta_original)
                        break
                    else:
                        # Mejoró pero no aprobó — usar feedback actualizado
                        feedback = nueva_eval.get("feedback_regeneracion", feedback)
                else:
                    # La nueva no mejoró → eliminarla
                    os.remove(nueva_ruta)
                    print(f"   ↩️  No mejoró, manteniendo la versión anterior")

            # Resultado final
            mejoro = mejor_puntaje > puntaje_original
            if mejoro:
                stats["mejoradas"] += 1
                # Si la mejor imagen es nueva, reemplazar la original
                if mejor_ruta != ruta_original and os.path.exists(ruta_original):
                    os.remove(ruta_original)
            else:
                stats["sin_mejora"] += 1
                print(f"   ⚠️  No se logró mejorar {archivo} tras {self.max_intentos} intentos")

            stats["regeneradas"] += 1
            stats["detalles"].append({
                "archivo": archivo,
                "puntaje_original": puntaje_original,
                "puntaje_final": mejor_puntaje,
                "mejoro": mejoro,
            })

        # Resumen final
        print("\n" + "=" * 60)
        print("📋 RESUMEN DE REGENERACIÓN")
        print("=" * 60)
        print(f"  Imágenes procesadas:  {stats['regeneradas']}")
        print(f"  Mejoradas:            {stats['mejoradas']}")
        print(f"  Sin mejora:           {stats['sin_mejora']}")
        for d in stats["detalles"]:
            emoji = "📈" if d["mejoro"] else "📉"
            print(f"  {emoji} {d['archivo']}: {d['puntaje_original']} → {d['puntaje_final']}")
        print("=" * 60)

        return stats

    # ------------------------------------------------------------------ #
    #  REGENERAR UNA IMAGEN ESPECÍFICA
    # ------------------------------------------------------------------ #
    def _regenerar_imagen(
        self, producto_key: str, formato: str, feedback: str, intento: int
    ) -> str:
        """
        Regenera una imagen específica usando el feedback del crítico.
        Retorna la ruta de la nueva imagen o '' si falla.
        """
        prod = PRODUCTOS.get(producto_key, {})
        if not prod:
            return ""

        nombre = prod["nombre"]
        desc = prod["descripcion"]
        slogan = prod["slogan"]
        color1 = prod["color_primario"]
        color2 = prod["color_secundario"]
        color_bg = prod.get("color_fondo", "#ffffff")
        tema = prod.get("tema", "claro")
        logos = prod.get("logos", [])
        cta = prod.get("cta", "prizma.cloud")
        linea = prod.get("linea", "")

        # Instrucción de tema
        if tema == "oscuro":
            tema_instruccion = (
                f"DARK THEME design. Background color: {color_bg}. "
                f"Use light/white text for readability. Deep, rich feel. "
            )
        else:
            tema_instruccion = (
                f"LIGHT THEME design. Background color: {color_bg}. "
                f"Use dark text for readability. Clean, airy feel. "
            )

        brand_hint = (
            f"\n{VISUAL_GUIDELINES}\n"
            f"PRODUCT: {nombre} (line: {linea}). "
            f"Primary color: {color1}. Secondary: {color2}. Background: {color_bg}. "
            f"This product helps: {desc}. "
        )

        # Feedback del crítico como corrección
        correccion = ""
        if feedback:
            correccion = (
                f"\n\n⚠️ CORRECCIONES OBLIGATORIAS (de evaluación anterior):\n"
                f"{feedback}\n"
                f"Es el intento #{intento}. Asegúrate de corregir los problemas señalados.\n"
                f"⛔ REMINDER: Do NOT include ANY logos, icons, or names of third-party brands "
                f"(Google, Apple, Hostinger, WhatsApp icon, Shopify, etc.). "
                f"ONLY Prizma products are allowed.\n"
            )

        # Construir prompt según formato
        aspect_ratio = "1:1"
        usa_logo = True

        if formato == "feed_1x1":
            aspect_ratio = "1:1"
            prompt = (
                f"{brand_hint}{tema_instruccion}"
                f"Create a professional social media post (1080x1080) for '{nombre}'. "
                f"Use the provided logo prominently and clearly in the design. "
                f"Include subtle geometric data-flow patterns as decoration. "
                f"The text '{slogan}' should appear elegantly in the design. "
                f"Style: Colombian tech startup, premium feel. "
                f"NO mockup devices. The logo must be clearly visible."
                f"{correccion}"
            )
        elif formato == "story_9x16":
            aspect_ratio = "9:16"
            prompt = (
                f"{brand_hint}{tema_instruccion}"
                f"Create a vertical story/reel graphic (9:16) for '{nombre}'. "
                f"Use the provided logo at the top of the design. "
                f"Bold gradient background from {color1} to {color2}. "
                f"Include the slogan '{slogan}' in large, bold text in the middle. "
                f"Add call-to-action text '{cta}' at the bottom. "
                f"Style: energetic startup, tech-forward, Colombian business context."
                f"{correccion}"
            )
        elif formato == "banner_16x9":
            aspect_ratio = "16:9"
            prompt = (
                f"{brand_hint}{tema_instruccion}"
                f"Create a wide banner/cover image (16:9) for '{nombre}'. "
                f"Use the provided logo on the left side, sized proportionally. "
                f"Right side: abstract visualization of data connections and flow lines. "
                f"Clean typography with '{slogan}' centered or right-aligned. "
                f"Suitable for Facebook cover. Premium quality, no clutter."
                f"{correccion}"
            )
        elif formato == "promo_1x1":
            aspect_ratio = "1:1"
            usa_logo = False
            pain_map = {
                "emw": "People overwhelmed managing hundreds of WhatsApp contacts manually",
                "graf": "Small business owner losing orders because chat messages get buried",
                "talaria": "Delivery coordination chaos with no tracking or assignment system",
                "sinergia": "Shop owner who doesn't know daily sales totals or inventory levels",
                "agora": "Remote team struggling with disconnected tools and no shared workspace",
                "terminal": "IT support team needing remote server access without VPN complexity",
                "fiar": "Store owner lending credit to customers with no digital tracking",
            }
            pain = pain_map.get(producto_key, "")
            prompt = (
                f"{brand_hint}{tema_instruccion}"
                f"A photorealistic scene showing a Colombian small business workspace. "
                f"The scene represents someone using '{nombre}' — {desc}. "
            )
            if pain:
                prompt += (
                    f"Show the POSITIVE outcome: the user is organized, in control, smiling. "
                    f"Contrast with the pain of '{pain}' — but show the solution. "
                )
            prompt += (
                f"Color accents matching {color1} and {color2}. "
                f"Warm, tropical urban Colombian setting. Modern desk, plants, natural light. "
                f"Photorealistic, soft lighting, shallow depth of field. "
                f"NO text overlays. NO logos. Pure scene photography style."
                f"{correccion}"
            )
        else:
            print(f"⚠️  Formato desconocido: {formato}")
            return ""

        # Generar
        screenshots = prod.get("screenshots", [])
        try:
            if usa_logo and logos:
                path = self.generator.generar_con_logo(
                    prompt,
                    logos[:2],
                    aspect_ratio=aspect_ratio,
                    subfolder=producto_key,
                    nombre=f"{producto_key}_{formato}",
                    screenshot_files=screenshots[:2],
                )
            else:
                path = self.generator.generar_desde_texto(
                    prompt,
                    aspect_ratio=aspect_ratio,
                    subfolder=producto_key,
                    nombre=f"{producto_key}_{formato}",
                    screenshot_files=screenshots[:1],
                )
            return path or ""
        except Exception as e:
            print(f"   ❌ Error generando: {e}")
            return ""

    # ------------------------------------------------------------------ #
    #  EXPORTAR REPORTE
    # ------------------------------------------------------------------ #
    def exportar_reporte(self, ruta: str = None) -> str:
        """Exporta el reporte de evaluación a JSON."""
        if not ruta:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            ruta = os.path.join(OUTPUT_DIR, f"reporte_calidad_{timestamp}.json")

        # Limpiar objetos no serializables
        datos_limpios = []
        for r in self._resultados:
            limpio = {}
            for k, v in r.items():
                if isinstance(v, (str, int, float, bool, list, dict, type(None))):
                    limpio[k] = v
            datos_limpios.append(limpio)

        with open(ruta, "w", encoding="utf-8") as f:
            json.dump(datos_limpios, f, indent=2, ensure_ascii=False)

        print(f"\n📄 Reporte guardado: {ruta}")
        return ruta


# ------------------------------------------------------------------ #
#  CLI
# ------------------------------------------------------------------ #
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Crítico visual de imágenes de marca — Prizma"
    )
    parser.add_argument(
        "--producto", type=str,
        help=f"Producto a evaluar: {list(PRODUCTOS.keys())}"
    )
    parser.add_argument(
        "--todos", action="store_true",
        help="Evaluar todos los productos con imágenes"
    )
    parser.add_argument(
        "--regenerar", action="store_true",
        help="Regenerar automáticamente las imágenes rechazadas"
    )
    parser.add_argument(
        "--umbral", type=int, default=70,
        help="Puntaje mínimo para aprobar (0-100, default: 70)"
    )
    parser.add_argument(
        "--max-intentos", type=int, default=2,
        help="Máximo intentos de regeneración por imagen (default: 2)"
    )
    parser.add_argument(
        "--reporte", type=str, default=None,
        help="Ruta para guardar el reporte JSON"
    )

    args = parser.parse_args()
    critic = ImageCritic(umbral=args.umbral, max_intentos=args.max_intentos)

    if args.todos:
        if args.regenerar:
            critic.regenerar_rechazadas()
        else:
            critic.evaluar_todos()
    elif args.producto:
        if args.regenerar:
            critic.regenerar_rechazadas(args.producto)
        else:
            critic.evaluar_paquete(args.producto)
    else:
        parser.print_help()
        exit(0)

    # Siempre exportar reporte
    critic.exportar_reporte(args.reporte)
