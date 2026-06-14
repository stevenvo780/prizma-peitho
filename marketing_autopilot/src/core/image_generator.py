"""
image_generator.py — Generación de imágenes de marca con Gemini (Nano Banana).

Modelos soportados:
  - gemini-3-pro-image-preview → PRO (default), hasta 14 refs, hasta 4K, razonamiento, texto preciso
  - gemini-2.5-flash-image  → rápido, hasta 3 refs, 1K (fallback económico)

Funcionalidades:
  - Texto a imagen (post para redes)
  - Imagen + texto a imagen (usa logos de referencia)
  - Generación de paquetes de marca (batch por producto)
  
Narrativa visual integrada desde NARRATIVA_MARCA.md y PALETA_COLORES.md.
"""

import os
import json
import hashlib
from datetime import datetime
from pathlib import Path
from google import genai
from google.genai import types
from PIL import Image
from dotenv import load_dotenv

from config import (
    get_logger, PRODUCTOS, VISUAL_GUIDELINES, PAIN_POINTS,
    BRAND_ASSETS_DIR as _BRAND_ASSETS_DIR,
    SCREENSHOTS_DIR as _SCREENSHOTS_DIR,
    IMAGES_DIR as _IMAGES_DIR,
    CAMPAIGNS_DIR as _CAMPAIGNS_DIR,
    DEFAULT_IMAGE_MODEL, FALLBACK_IMAGE_MODEL,
)

load_dotenv()

logger = get_logger("image_generator")
client = genai.Client(api_key=os.getenv("GOOGLE_API_KEY"))

# Directorio base de logos de marca
BRAND_ASSETS_DIR = str(_BRAND_ASSETS_DIR)
# Capturas reales de las apps
SCREENSHOTS_DIR = str(_SCREENSHOTS_DIR)
# Directorio de salida para imágenes generadas
OUTPUT_DIR = str(_IMAGES_DIR)
# Directorio de campañas
CAMPAIGNS_DIR = str(_CAMPAIGNS_DIR)

# ------------------------------------------------------------------ #
#  GUIDELINES VISUALES DE MARCA (extraídas de NARRATIVA_MARCA.md)
# ------------------------------------------------------------------ #
# VISUAL_GUIDELINES y PRODUCTOS importados desde config.py (fuente única de verdad)
# PAIN_POINTS también importado desde config.py


class ImageGenerator:
    def __init__(self, model: str = "gemini-3-pro-image-preview"):
        """
        model: 'gemini-3-pro-image-preview' (pro, mejor texto) o 'gemini-2.5-flash-image' (rápido)
        """
        self.model = model
        self.is_pro = "3-pro" in model
        os.makedirs(OUTPUT_DIR, exist_ok=True)

    def _load_logo(self, filename: str) -> Image.Image:
        """Carga un logo desde el directorio de assets."""
        path = os.path.join(BRAND_ASSETS_DIR, filename)
        if not os.path.exists(path):
            raise FileNotFoundError(f"Logo no encontrado: {path}")
        return Image.open(path)

    def _save_image(self, image: Image.Image, nombre: str, subfolder: str = "", base_dir: str = "") -> str:
        """Guarda imagen y retorna la ruta absoluta."""
        base = base_dir or OUTPUT_DIR
        folder = os.path.join(base, subfolder) if subfolder else base
        os.makedirs(folder, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        # Sanitizar nombre
        safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in nombre)
        filename = f"{safe_name}_{timestamp}.png"
        path = os.path.join(folder, filename)
        image.save(path)
        print(f"💾 Imagen guardada: {path}")
        return path

    # ------------------------------------------------------------------ #
    #  TEXTO → IMAGEN
    # ------------------------------------------------------------------ #
    def generar_desde_texto(
        self,
        prompt: str,
        aspect_ratio: str = "1:1",
        resolution: str = "2K",
        subfolder: str = "",
        nombre: str = "generada",
        screenshot_files: list[str] | None = None,
    ) -> str:
        """Genera una imagen a partir de un prompt de texto, opcionalmente con screenshots de referencia."""
        # Cargar screenshots de referencia si se proporcionan
        contents = [prompt]
        if screenshot_files:
            max_refs = 3 if self.is_pro else 2
            for ss_file in screenshot_files[:max_refs]:
                ss_path = os.path.join(BRAND_ASSETS_DIR, ss_file)
                if os.path.exists(ss_path):
                    try:
                        ss_img = Image.open(ss_path)
                        contents.append(ss_img)
                        print(f"   📸 Screenshot de referencia: {ss_file}")
                    except Exception:
                        pass

        config = types.GenerateContentConfig(
            response_modalities=["IMAGE"],
            image_config=types.ImageConfig(
                aspect_ratio=aspect_ratio,
            ),
        )
        # Gemini 3 Pro soporta resolución personalizada
        if self.is_pro:
            config = types.GenerateContentConfig(
                response_modalities=["TEXT", "IMAGE"],
                image_config=types.ImageConfig(
                    aspect_ratio=aspect_ratio,
                    image_size=resolution,
                ),
            )

        response = client.models.generate_content(
            model=self.model,
            contents=contents,
            config=config,
        )

        for part in response.parts:
            if part.inline_data is not None:
                image = part.as_image()
                return self._save_image(image, nombre, subfolder)

        print("⚠️  No se generó imagen en la respuesta")
        return ""

    # ------------------------------------------------------------------ #
    #  LOGO + TEXTO → IMAGEN (edición / composición)
    # ------------------------------------------------------------------ #
    def generar_con_logo(
        self,
        prompt: str,
        logo_files: list[str],
        aspect_ratio: str = "1:1",
        resolution: str = "2K",
        subfolder: str = "",
        nombre: str = "con_logo",
        screenshot_files: list[str] | None = None,
    ) -> str:
        """
        Genera imagen usando logos Y screenshots como referencia visual.
        Gemini integra el logo en el diseño y usa los screenshots
        para entender la estética real del producto.
        """
        contents = [prompt]
        loaded_refs = 0
        max_refs = 5 if self.is_pro else 3

        # 1) Cargar logos
        for logo_file in logo_files[:max_refs]:
            try:
                logo = self._load_logo(logo_file)
                contents.append(logo)
                loaded_refs += 1
            except FileNotFoundError as e:
                print(f"⚠️  {e}")

        loaded_logos = loaded_refs

        # 2) Cargar screenshots de referencia (interfaz real del producto)
        if screenshot_files:
            for ss_file in screenshot_files:
                if loaded_refs >= max_refs:
                    break
                ss_path = os.path.join(BRAND_ASSETS_DIR, ss_file)
                if os.path.exists(ss_path):
                    try:
                        ss_img = Image.open(ss_path)
                        contents.append(ss_img)
                        loaded_refs += 1
                        print(f"   📸 Screenshot de referencia: {ss_file}")
                    except Exception as e:
                        print(f"⚠️  Error cargando screenshot {ss_file}: {e}")

        # Si no se cargó ningún logo, quitar instrucciones de logo del prompt
        if loaded_logos == 0:
            prompt_cleaned = prompt.replace("Use the provided logo prominently and clearly in the design. ", "")
            prompt_cleaned = prompt_cleaned.replace("Use the provided logo at the top of the design. ", "")
            prompt_cleaned = prompt_cleaned.replace("Use the provided logo on the left side, sized proportionally. ", "")
            prompt_cleaned = prompt_cleaned.replace("Use the provided brand logo subtly integrated in the design. ", "")
            prompt_cleaned = prompt_cleaned.replace("The logo must be clearly visible and well-integrated.", "")
            contents[0] = prompt_cleaned
            print("ℹ️  Sin logos de referencia — generando sin instrucciones de logo")

        config = types.GenerateContentConfig(
            response_modalities=["TEXT", "IMAGE"],
            image_config=types.ImageConfig(
                aspect_ratio=aspect_ratio,
            ),
        )
        if self.is_pro:
            config = types.GenerateContentConfig(
                response_modalities=["TEXT", "IMAGE"],
                image_config=types.ImageConfig(
                    aspect_ratio=aspect_ratio,
                    image_size=resolution,
                ),
            )

        response = client.models.generate_content(
            model=self.model,
            contents=contents,
            config=config,
        )

        for part in response.parts:
            if hasattr(part, "inline_data") and part.inline_data is not None:
                image = part.as_image()
                return self._save_image(image, nombre, subfolder)

        print("⚠️  No se generó imagen en la respuesta")
        return ""

    # ------------------------------------------------------------------ #
    #  PAQUETE DE MARCA — genera set completo para un producto
    # ------------------------------------------------------------------ #
    def generar_paquete_marca(self, producto_key: str) -> list[str]:
        """
        Genera un paquete de imágenes de marca para un producto:
          1. Post cuadrado 1:1 (Feed Instagram/Facebook)
          2. Story/Reel 9:16 (Stories)
          3. Banner horizontal 16:9 (Cover Facebook/Twitter)
          4. Post promocional con producto (1:1)
        
        Usa guidelines visuales de NARRATIVA_MARCA.md para consistencia.
        Retorna lista de paths de imágenes generadas.
        """
        if producto_key not in PRODUCTOS:
            print(f"❌ Producto '{producto_key}' no encontrado. Opciones: {list(PRODUCTOS.keys())}")
            return []

        prod = PRODUCTOS[producto_key]
        nombre = prod["nombre"]
        desc = prod["descripcion"]
        slogan = prod["slogan"]
        color1 = prod["color_primario"]
        color2 = prod["color_secundario"]
        color_bg = prod.get("color_fondo", "#ffffff")
        tema = prod.get("tema", "claro")
        logos = prod["logos"]
        cta = prod.get("cta", "humanizar.co")
        linea = prod.get("linea", "")
        pain = ""
        # Extraer pain point del tipo de producto
        if prod.get("tipo") == "producto":
            pain = PAIN_POINTS.get(producto_key, "")

        subfolder = producto_key
        screenshots = prod.get("screenshots", [])

        # Instrucción de tema para los prompts
        if tema == "oscuro":
            tema_instruccion = (
                f"DARK THEME design. Background color: {color_bg}. "
                f"Use light/white text for readability. Deep, rich feel. "
                f"Accent colors pop against dark background. "
            )
        else:
            tema_instruccion = (
                f"LIGHT THEME design. Background color: {color_bg}. "
                f"Use dark text for readability. Clean, airy feel. "
                f"White space is important. "
            )

        # Instrucción de referencia visual (screenshots del producto real)
        screenshot_hint = ""
        if screenshots:
            screenshot_hint = (
                "I'm providing REAL SCREENSHOTS of the product's interface as visual reference. "
                "Use them to understand the actual look, color palette, and style of the app. "
                "Match the visual language and aesthetics of the real product. "
            )

        # Contexto visual de marca (siempre incluido)
        brand_hint = (
            f"\n{VISUAL_GUIDELINES}\n"
            f"PRODUCT: {nombre} (line: {linea}). "
            f"Primary color: {color1}. Secondary: {color2}. Background: {color_bg}. "
            f"This product helps: {desc}. "
            f"{screenshot_hint}"
        )
        if pain:
            brand_hint += f"User pain point scene: {pain}. "

        print(f"\n🎨 Generando paquete de marca para {nombre}")
        print(f"   {desc}")
        print(f"   Logos: {len(logos)} configurados | Screenshots: {len(screenshots)} | Tema: {tema} | Línea: {linea}")
        for l in logos:
            full = os.path.join(BRAND_ASSETS_DIR, l)
            exists = "✅" if os.path.exists(full) else "❌"
            print(f"   {exists} {l}")
        for s in screenshots:
            full = os.path.join(BRAND_ASSETS_DIR, s)
            exists = "✅" if os.path.exists(full) else "❌"
            print(f"   {exists} 📸 {s}")
        print("=" * 60)

        generated = []

        # 1) Post Feed cuadrado con logo
        print("\n📐 [1/4] Post cuadrado (1:1) con logo...")
        prompt_feed = (
            f"{brand_hint}"
            f"{tema_instruccion}"
            f"Create a professional social media post (1080x1080) for '{nombre}'. "
            f"Use the provided logo prominently and clearly in the design. "
            f"Include subtle geometric data-flow patterns as decoration. "
            f"The text '{slogan}' should appear elegantly in the design. "
            f"Style: Colombian tech startup, premium feel, suitable for Instagram/Facebook feed. "
            f"Mood: professional but approachable, confident, trustworthy. "
            f"NO mockup devices. The logo must be clearly visible and well-integrated."
        )
        path = self.generar_con_logo(
            prompt_feed,
            logos[:2],
            aspect_ratio="1:1",
            subfolder=subfolder,
            nombre=f"{producto_key}_feed_1x1",
            screenshot_files=screenshots[:2],
        )
        if path:
            generated.append(path)

        # 2) Story vertical
        print("\n📱 [2/4] Story vertical (9:16)...")
        prompt_story = (
            f"{brand_hint}"
            f"{tema_instruccion}"
            f"Create a vertical story/reel graphic (9:16 aspect ratio) for '{nombre}'. "
            f"Use the provided logo at the top of the design. "
            f"Bold gradient background from {color1} to {color2}. "
            f"Modern, eye-catching design with dynamic flowing shapes and connection nodes. "
            f"Include the slogan '{slogan}' in large, bold text in the middle. "
            f"Add call-to-action text '{cta}' at the bottom. "
            f"Style: energetic startup, tech-forward, Colombian business context."
        )
        path = self.generar_con_logo(
            prompt_story,
            logos[:1],
            aspect_ratio="9:16",
            subfolder=subfolder,
            nombre=f"{producto_key}_story_9x16",
            screenshot_files=screenshots[:1],
        )
        if path:
            generated.append(path)

        # 3) Banner horizontal (cover)
        print("\n🖼️  [3/4] Banner horizontal (16:9)...")
        prompt_banner = (
            f"{brand_hint}"
            f"{tema_instruccion}"
            f"Create a wide banner/cover image (16:9 aspect ratio) for '{nombre}'. "
            f"Use the provided logo on the left side, sized proportionally. "
            f"Right side: abstract visualization of data connections, nodes, and flow lines "
            f"representing business processes (orders, deliveries, sales). "
            f"Clean typography with '{slogan}' centered or right-aligned. "
            f"Suitable for Facebook cover or Twitter/X header. "
            f"Premium quality, no clutter, breathable layout."
        )
        path = self.generar_con_logo(
            prompt_banner,
            logos[:1],
            aspect_ratio="16:9",
            subfolder=subfolder,
            nombre=f"{producto_key}_banner_16x9",
            screenshot_files=screenshots[:1],
        )
        if path:
            generated.append(path)

        # 4) Post promocional (escena contextual sin logo)
        print("\n🎯 [4/4] Post promocional (1:1)...")
        prompt_promo = (
            f"{brand_hint}"
            f"{tema_instruccion}"
            f"A photorealistic scene showing a Colombian small business workspace. "
            f"The scene represents someone using '{nombre}' — {desc}. "
        )
        if pain:
            prompt_promo += (
                f"Show the POSITIVE outcome: the user is organized, in control, smiling. "
                f"Contrast with the pain of '{pain}' — but show the solution, not the problem. "
            )
        prompt_promo += (
            f"Color accents in the environment matching {color1} and {color2}. "
            f"Warm, tropical urban Colombian setting. Modern desk, plants, natural light. "
            f"Professional yet inviting atmosphere. "
            f"Photorealistic, soft lighting, shallow depth of field. "
            f"NO text overlays in the image. NO logos. Pure scene photography style."
        )
        path = self.generar_desde_texto(
            prompt_promo,
            aspect_ratio="1:1",
            subfolder=subfolder,
            nombre=f"{producto_key}_promo_1x1",
            screenshot_files=screenshots[:1],
        )
        if path:
            generated.append(path)

        print(f"\n✅ Paquete '{nombre}' completado: {len(generated)}/4 imágenes generadas")
        return generated

    # ------------------------------------------------------------------ #
    #  GENERAR TODOS LOS PAQUETES
    # ------------------------------------------------------------------ #
    def generar_todos_los_paquetes(self) -> dict:
        """Genera paquetes de marca para TODOS los productos."""
        resultados = {}
        for key in PRODUCTOS:
            try:
                paths = self.generar_paquete_marca(key)
                resultados[key] = {"ok": True, "imagenes": paths, "total": len(paths)}
            except Exception as e:
                print(f"❌ Error en {key}: {e}")
                resultados[key] = {"ok": False, "error": str(e)}
        return resultados

    # ------------------------------------------------------------------ #
    #  CAMPAÑAS — sets temáticos de imágenes con nombre y contexto
    # ------------------------------------------------------------------ #
    def generar_campana(
        self,
        nombre_campana: str,
        productos: list[str],
        tematica: str = "",
        formatos: list[str] = None,
    ) -> dict:
        """
        Genera un set de imágenes agrupado bajo un nombre de campaña.

        Args:
            nombre_campana: Nombre descriptivo (ej: "Lanzamiento EMW 2026", "Black Friday")
            productos: Lista de producto_keys a incluir (ej: ["emw", "graf"])
            tematica: Temática o ángulo creativo opcional (ej: "descuentos fin de año",
                      "productividad de equipos remotos"). Se inyecta en cada prompt.
            formatos: Lista de formatos a generar. Default: todos.
                      Opciones: ["feed_1x1", "story_9x16", "banner_16x9", "promo_1x1"]

        Returns:
            dict con metadata de la campaña y paths de imágenes generadas.

        Ejemplo:
            gen.generar_campana(
                nombre_campana="CyberWeek Febrero",
                productos=["emw", "graf"],
                tematica="Ofertas especiales por apertura de cuenta en febrero",
                formatos=["feed_1x1", "story_9x16"],
            )
        """
        if formatos is None:
            formatos = [
                "feed_1x1", "story_9x16", "banner_16x9", "promo_1x1",
                "carousel_1x1", "tip_1x1", "stat_1x1",
                "feature_9x16", "cta_story_9x16", "testimonial_1x1",
            ]

        # Crear carpeta de campaña
        safe_name = "".join(
            c if c.isalnum() or c in "-_ " else "_" for c in nombre_campana
        ).strip().replace(" ", "_")
        timestamp = datetime.now().strftime("%Y%m%d")
        campana_dir = os.path.join(CAMPAIGNS_DIR, f"{timestamp}_{safe_name}")
        os.makedirs(campana_dir, exist_ok=True)

        print(f"\n🎬 CAMPAÑA: {nombre_campana}")
        if tematica:
            print(f"   🎯 Temática: {tematica}")
        print(f"   📦 Productos: {productos}")
        print(f"   📐 Formatos: {formatos}")
        print(f"   📁 Carpeta: {campana_dir}")
        print("=" * 60)

        campana_meta = {
            "nombre": nombre_campana,
            "tematica": tematica,
            "productos": productos,
            "formatos": formatos,
            "created_at": datetime.now().isoformat(),
            "carpeta": campana_dir,
            "imagenes": {},
        }

        for prod_key in productos:
            if prod_key not in PRODUCTOS:
                print(f"⚠️  Producto '{prod_key}' no existe, saltando...")
                continue

            prod = PRODUCTOS[prod_key]
            print(f"\n🏷️  {prod['nombre']} ({prod_key})")

            # Carpeta del producto dentro de la campaña
            prod_dir = os.path.join(campana_dir, prod_key)
            os.makedirs(prod_dir, exist_ok=True)

            imagenes_prod = []

            for fmt in formatos:
                path = self._generar_formato_campana(
                    prod_key, fmt, tematica, prod_dir
                )
                if path:
                    imagenes_prod.append({"formato": fmt, "path": path})

            campana_meta["imagenes"][prod_key] = imagenes_prod
            print(f"   ✅ {len(imagenes_prod)}/{len(formatos)} imágenes generadas")

        # Guardar metadata de la campaña
        meta_path = os.path.join(campana_dir, "campana.json")
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(campana_meta, f, indent=2, ensure_ascii=False)

        total = sum(len(v) for v in campana_meta["imagenes"].values())
        esperado = len(productos) * len(formatos)
        print(f"\n{'=' * 60}")
        print(f"🎬 Campaña '{nombre_campana}' completada: {total}/{esperado} imágenes")
        print(f"📁 Carpeta: {campana_dir}")
        print(f"📄 Metadata: {meta_path}")

        return campana_meta

    def _generar_formato_campana(
        self, producto_key: str, formato: str, tematica: str, output_dir: str
    ) -> str:
        """Genera una imagen de un formato específico para una campaña."""
        prod = PRODUCTOS[producto_key]
        nombre = prod["nombre"]
        desc = prod["descripcion"]
        slogan = prod["slogan"]
        color1 = prod["color_primario"]
        color2 = prod["color_secundario"]
        color_bg = prod.get("color_fondo", "#ffffff")
        tema = prod.get("tema", "claro")
        logos = prod["logos"]
        cta = prod.get("cta", "humanizar.co")
        linea = prod.get("linea", "")
        screenshots = prod.get("screenshots", [])

        # Instrucciones de tema
        if tema == "oscuro":
            tema_inst = (
                f"DARK THEME. Background: {color_bg}. Light/white text. Deep, rich feel. "
            )
        else:
            tema_inst = (
                f"LIGHT THEME. Background: {color_bg}. Dark text. Clean, airy feel. "
            )

        brand = (
            f"\n{VISUAL_GUIDELINES}\n"
            f"PRODUCT: {nombre} (line: {linea}). "
            f"Primary: {color1}. Secondary: {color2}. Background: {color_bg}. "
            f"Description: {desc}. "
        )

        # Inyectar temática de campaña si existe
        tematica_hint = ""
        if tematica:
            tematica_hint = (
                f"\n\n🎯 CAMPAIGN THEME: {tematica}\n"
                f"The visual must reflect this campaign angle. "
                f"Integrate the theme naturally into the composition and messaging.\n"
            )

        # Cargar screenshot como referencia visual si existe
        ref_images = []
        for ss in screenshots[:1]:  # máx 1 screenshot de referencia
            ss_path = os.path.join(BRAND_ASSETS_DIR, ss)
            if os.path.exists(ss_path):
                try:
                    ref_images.append(Image.open(ss_path))
                except Exception:
                    pass

        aspect_ratio = "1:1"
        usa_logo = True

        if formato == "feed_1x1":
            aspect_ratio = "1:1"
            prompt = (
                f"{brand}{tema_inst}{tematica_hint}"
                f"Create a professional social media post (1080x1080) for '{nombre}'. "
                f"Use the provided logo prominently. "
                f"Include subtle geometric data-flow patterns. "
                f"Text '{slogan}' elegantly placed. "
                f"Style: Colombian tech startup, premium feel."
            )
        elif formato == "story_9x16":
            aspect_ratio = "9:16"
            prompt = (
                f"{brand}{tema_inst}{tematica_hint}"
                f"Create a vertical story/reel (9:16) for '{nombre}'. "
                f"Logo at the top. Bold gradient from {color1} to {color2}. "
                f"Slogan '{slogan}' in large bold text in the middle. "
                f"CTA '{cta}' at the bottom. Energetic, tech-forward."
            )
        elif formato == "banner_16x9":
            aspect_ratio = "16:9"
            prompt = (
                f"{brand}{tema_inst}{tematica_hint}"
                f"Create a wide banner/cover (16:9) for '{nombre}'. "
                f"Logo on the left. Right side: abstract data connections. "
                f"Typography with '{slogan}' centered/right-aligned. "
                f"Facebook cover quality. Premium, breathable."
            )
        elif formato == "promo_1x1":
            aspect_ratio = "1:1"
            usa_logo = False
            pain = PAIN_POINTS.get(producto_key, "")
            prompt = (
                f"{brand}{tema_inst}{tematica_hint}"
                f"Photorealistic Colombian small business workspace scene. "
                f"Someone using '{nombre}' — {desc}. "
            )
            if pain:
                prompt += f"POSITIVE outcome: user organized, in control. "
            prompt += (
                f"Color accents: {color1} and {color2}. "
                f"Warm tropical urban Colombian setting. "
                f"NO text overlays. NO logos. Pure photography."
            )
        elif formato == "carousel_1x1":
            aspect_ratio = "1:1"
            prompt = (
                f"{brand}{tema_inst}{tematica_hint}"
                f"Create a carousel-style social media slide (1080x1080) for '{nombre}'. "
                f"Use the provided logo small in a corner. "
                f"Show a KEY FEATURE or BENEFIT of the product with a simple icon illustration. "
                f"Large bold text highlighting ONE specific benefit. "
                f"Clean, minimal design with lots of white space. "
                f"Swipeable feel — looks like part of a series. "
                f"Bottom: '{cta}' in small text."
            )
        elif formato == "tip_1x1":
            aspect_ratio = "1:1"
            tip_map = {
                "emw": "¿Sabías que puedes segmentar envíos por etiquetas de cliente?",
                "graf": "Tip: Activa notificaciones de pedido para no perder ninguna venta",
                "meravuelta": "Tip: Asigna domiciliarios por zona para entregas más rápidas",
                "sinergia": "Tip: Usa el cierre de caja diario para detectar descuadres al instante",
                "agora": "Tip: Crea espacios separados por proyecto para mantener el orden",
                "terminal": "Tip: Agrupa tus servidores por ambiente (dev/staging/prod)",
                "fiar": "Tip: Configura alertas de vencimiento para cobrar a tiempo",
                "humanizar": "Tip: Conecta Graf + EMW para vender y comunicar desde un solo lugar",
            }
            tip = tip_map.get(producto_key, f"Tip: Aprovecha {nombre} al máximo")
            prompt = (
                f"{brand}{tema_inst}{tematica_hint}"
                f"Create an educational 'tip' post (1080x1080) for '{nombre}'. "
                f"Use the provided logo small in top corner. "
                f"Header: '💡 Tip' or '¿Sabías que...?' in bold. "
                f"Body text: '{tip}' "
                f"Style: clean infographic, easy to read, one key takeaway. "
                f"Light background, accent color {color1}. "
                f"NO photos. Clean graphic design only."
            )
        elif formato == "stat_1x1":
            aspect_ratio = "1:1"
            stat_map = {
                "emw": "87% de tasa de apertura en WhatsApp vs 20% en email",
                "graf": "+3x pedidos cuando usas catálogo digital vs solo chat",
                "meravuelta": "40% menos tiempo de entrega con asignación automática",
                "sinergia": "0 descuadres de caja con cierre digital diario",
                "agora": "5x más productivo con workspace unificado en la nube",
                "terminal": "90% menos tiempo resolviendo tickets con acceso remoto directo",
                "fiar": "60% menos cartera vencida con alertas automáticas de cobro",
                "humanizar": "8 herramientas conectadas en un solo ecosistema empresarial",
            }
            stat = stat_map.get(producto_key, f"Resultados reales con {nombre}")
            prompt = (
                f"{brand}{tema_inst}{tematica_hint}"
                f"Create a STATISTIC highlight post (1080x1080) for '{nombre}'. "
                f"Big bold number or percentage as the focal point. "
                f"Stat: '{stat}' "
                f"Use the provided logo subtly. "
                f"Minimal design, the number dominates. "
                f"Colors: {color1} for the number, {color_bg} background. "
                f"Professional data visualization feel."
            )
        elif formato == "feature_9x16":
            aspect_ratio = "9:16"
            feature_map = {
                "emw": "Envíos masivos personalizados con variables por cliente",
                "graf": "Catálogo digital + carrito + pago en un solo link de WhatsApp",
                "meravuelta": "Seguimiento en tiempo real de cada entrega en el mapa",
                "sinergia": "Inventario actualizado automáticamente con cada venta",
                "agora": "Editor de código + terminal + chat en un solo workspace",
                "terminal": "Acceso SSH desde el navegador sin configurar VPN",
                "fiar": "Historial completo de créditos y pagos por cliente",
                "humanizar": "Suite completa: ventas, operación y automatización integradas",
            }
            feature = feature_map.get(producto_key, desc)
            prompt = (
                f"{brand}{tema_inst}{tematica_hint}"
                f"Create a vertical FEATURE SHOWCASE story (9:16) for '{nombre}'. "
                f"Use the provided logo at the top. "
                f"Show a mockup or abstract representation of this feature: '{feature}'. "
                f"Use abstract UI elements, floating cards, and data visualizations. "
                f"Bold headline text describing the feature. "
                f"Bottom CTA: '{cta}'. "
                f"Dynamic, modern, tech-forward design."
            )
        elif formato == "cta_story_9x16":
            aspect_ratio = "9:16"
            usa_logo = True
            prompt = (
                f"{brand}{tema_inst}{tematica_hint}"
                f"Create a CALL-TO-ACTION story (9:16) for '{nombre}'. "
                f"Use the provided logo prominently at the top. "
                f"Bold gradient background from {color1} to {color2}. "
                f"Center text: '¡{nombre} es gratis!' or 'Empieza hoy' in huge bold text. "
                f"Arrow or swipe-up indicator pointing to CTA. "
                f"Bottom: '{cta}' in contrasting color. "
                f"Urgency feel, energetic, action-oriented. "
                f"NO photos. Pure bold graphic design."
            )
        elif formato == "testimonial_1x1":
            aspect_ratio = "1:1"
            usa_logo = False
            testimonial_map = {
                "emw": "Recuperamos el 35% de clientes inactivos en una semana con EMW",
                "graf": "Pasamos de perder pedidos en el chat a tener todo organizado con Graf",
                "meravuelta": "Nuestras entregas bajaron de 2 horas a 40 minutos con Mera Vuelta",
                "sinergia": "Ya no tenemos descuadres de caja desde que usamos Sinergia POS",
                "agora": "Todo el equipo trabaja en un solo lugar gracias a Agora",
                "terminal": "Resolvemos tickets en minutos sin necesitar VPN con Terminal",
                "fiar": "Redujimos la cartera vencida un 60% con Fiar",
                "humanizar": "Humanizar nos conectó ventas, entregas y facturación en un solo lugar",
            }
            quote = testimonial_map.get(producto_key, f"Transformamos nuestro negocio con {nombre}")
            prompt = (
                f"{brand}{tema_inst}{tematica_hint}"
                f"Create a TESTIMONIAL post (1080x1080). "
                f"Show a professional Colombian business person (diverse, realistic). "
                f"Quote bubble or elegant text overlay: '{quote}' "
                f"— Dueño de negocio, Colombia' "
                f"Warm, trustworthy, authentic feel. "
                f"Subtle brand color {color1} accents. "
                f"Photorealistic, warm lighting, professional setting. "
                f"Small '{nombre}' text at the bottom."
            )
        else:
            print(f"⚠️  Formato desconocido: {formato}")
            return ""

        # Generar con logo + screenshot de referencia
        try:
            nombre_archivo = f"{producto_key}_{formato}"
            if usa_logo and logos:
                contents = [prompt]
                loaded = 0
                max_refs = 5 if self.is_pro else 3
                # Primero logos
                for logo_file in logos[:2]:
                    try:
                        logo = self._load_logo(logo_file)
                        contents.append(logo)
                        loaded += 1
                    except FileNotFoundError:
                        pass
                # Luego screenshots como referencia
                for ref_img in ref_images:
                    if loaded < max_refs:
                        contents.append(ref_img)
                        loaded += 1

                config = types.GenerateContentConfig(
                    response_modalities=["TEXT", "IMAGE"],
                    image_config=types.ImageConfig(aspect_ratio=aspect_ratio),
                )
                if self.is_pro:
                    config = types.GenerateContentConfig(
                        response_modalities=["TEXT", "IMAGE"],
                        image_config=types.ImageConfig(
                            aspect_ratio=aspect_ratio, image_size="2K"
                        ),
                    )

                response = client.models.generate_content(
                    model=self.model, contents=contents, config=config
                )
                for part in response.parts:
                    if hasattr(part, "inline_data") and part.inline_data is not None:
                        image = part.as_image()
                        return self._save_image(image, nombre_archivo, base_dir=output_dir)

            else:
                # Promo sin logo — guardar en carpeta de campaña
                prompt_final = prompt
                config = types.GenerateContentConfig(
                    response_modalities=["IMAGE"],
                    image_config=types.ImageConfig(aspect_ratio=aspect_ratio),
                )
                if self.is_pro:
                    config = types.GenerateContentConfig(
                        response_modalities=["TEXT", "IMAGE"],
                        image_config=types.ImageConfig(
                            aspect_ratio=aspect_ratio, image_size="2K"
                        ),
                    )
                response = client.models.generate_content(
                    model=self.model, contents=[prompt_final], config=config
                )
                for part in response.parts:
                    if part.inline_data is not None:
                        image = part.as_image()
                        return self._save_image(image, nombre_archivo, base_dir=output_dir)
        except Exception as e:
            print(f"   ❌ Error generando {formato}: {e}")

        return ""

    # ------------------------------------------------------------------ #
    #  LISTAR CAMPAÑAS EXISTENTES
    # ------------------------------------------------------------------ #
    @staticmethod
    def listar_campanas() -> list[dict]:
        """Lista todas las campañas existentes."""
        if not os.path.isdir(CAMPAIGNS_DIR):
            return []
        campanas = []
        for d in sorted(os.listdir(CAMPAIGNS_DIR)):
            meta_path = os.path.join(CAMPAIGNS_DIR, d, "campana.json")
            if os.path.exists(meta_path):
                with open(meta_path, "r", encoding="utf-8") as f:
                    meta = json.load(f)
                total_imgs = sum(len(v) for v in meta.get("imagenes", {}).values())
                campanas.append({
                    "carpeta": d,
                    "nombre": meta.get("nombre", d),
                    "tematica": meta.get("tematica", ""),
                    "productos": meta.get("productos", []),
                    "total_imagenes": total_imgs,
                    "fecha": meta.get("created_at", ""),
                })
        return campanas

    # ------------------------------------------------------------------ #
    #  GENERAR IMAGEN PARA POST ESPECÍFICO (usado por campaign_runner)
    # ------------------------------------------------------------------ #
    def generar_imagen_para_post(
        self,
        prompt_imagen: str,
        producto_key: str = "humanizar",
        aspect_ratio: str = "1:1",
    ) -> str:
        """
        Genera una imagen para un post específico usando el prompt de Cerebro
        y los logos del producto como referencia.
        Inyecta guidelines visuales de marca para consistencia.
        
        Retorna el path de la imagen generada.
        """
        prod = PRODUCTOS.get(producto_key, PRODUCTOS["humanizar"])
        logos = prod["logos"]
        tema = prod.get("tema", "claro")
        color_bg = prod.get("color_fondo", "#ffffff")
        linea = prod.get("linea", "")

        if tema == "oscuro":
            tema_hint = f"DARK THEME, background {color_bg}, light text. Deep rich feel. "
        else:
            tema_hint = f"LIGHT THEME, background {color_bg}, dark text. Clean airy feel. "

        full_prompt = (
            f"{VISUAL_GUIDELINES}\n"
            f"PRODUCT: {prod['nombre']} ({linea}). "
            f"Primary: {prod['color_primario']}. Secondary: {prod['color_secundario']}. "
            f"\n{prompt_imagen}\n"
            f"Use the provided brand logo subtly integrated in the design. "
            f"{tema_hint}"
            f"Style: professional social media post for Colombian pyme audience. "
            f"Tech-premium, clean and modern. "
            f"NO excessive text. NO generic stock imagery. "
            f"Suitable for Facebook/Instagram."
        )

        return self.generar_con_logo(
            full_prompt,
            logos[:2],
            aspect_ratio=aspect_ratio,
            subfolder="posts",
            nombre=f"post_{producto_key}",
        )


# ------------------------------------------------------------------ #
#  CLI
# ------------------------------------------------------------------ #
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Generador de Imágenes de Marca — Humanizar")
    parser.add_argument("--producto", type=str, help=f"Producto: {list(PRODUCTOS.keys())}")
    parser.add_argument("--todos", action="store_true", help="Generar paquetes para todos los productos")
    parser.add_argument("--texto", type=str, help="Prompt libre para generar imagen")
    parser.add_argument("--ratio", type=str, default="1:1", help="Aspect ratio: 1:1, 9:16, 16:9")
    parser.add_argument("--modelo", type=str, default="gemini-3-pro-image-preview",
                        help="Modelo: gemini-3-pro-image-preview (pro) o gemini-2.5-flash-image (rápido)")
    # Campañas
    parser.add_argument("--campana", type=str, help="Nombre de la campaña (agrupa imágenes en carpeta)")
    parser.add_argument("--tematica", type=str, default="",
                        help="Temática/ángulo creativo de la campaña (ej: 'descuentos febrero')")
    parser.add_argument("--productos", nargs="+", default=None,
                        help="Productos a incluir en la campaña (ej: emw graf)")
    parser.add_argument("--formatos", nargs="+", default=None,
                        help="Formatos a generar (ej: feed_1x1 story_9x16 banner_16x9 promo_1x1)")
    parser.add_argument("--listar-campanas", action="store_true",
                        help="Listar campañas existentes")

    args = parser.parse_args()
    gen = ImageGenerator(model=args.modelo)

    if args.listar_campanas:
        campanas = ImageGenerator.listar_campanas()
        if not campanas:
            print("📭 No hay campañas creadas aún.")
        else:
            print(f"\n🎬 CAMPAÑAS EXISTENTES ({len(campanas)}):")
            print("=" * 60)
            for c in campanas:
                print(f"  📁 {c['carpeta']}")
                print(f"     Nombre: {c['nombre']}")
                if c['tematica']:
                    print(f"     Temática: {c['tematica']}")
                print(f"     Productos: {c['productos']}")
                print(f"     Imágenes: {c['total_imagenes']}")
                print(f"     Fecha: {c['fecha']}")
                print()
    elif args.campana:
        productos = args.productos or ["graf", "emw"]
        gen.generar_campana(
            nombre_campana=args.campana,
            productos=productos,
            tematica=args.tematica,
            formatos=args.formatos,
        )
    elif args.todos:
        gen.generar_todos_los_paquetes()
    elif args.producto:
        gen.generar_paquete_marca(args.producto)
    elif args.texto:
        gen.generar_desde_texto(args.texto, aspect_ratio=args.ratio, nombre="custom")
    else:
        parser.print_help()
