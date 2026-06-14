"""
campaign_runner.py — Orquestador de campañas de marketing para Humanizar Systems.

Flujos:
  --publicar: Publicación orgánica directa (genera copy + imagen + publica)
  --campana: Crea campaña de Ads (pausada)
  --imagenes: Genera paquete de imágenes de marca
  --programar: Genera calendario semanal y encola (usa scheduler.py)
  --auto: Modo autopiloto completo (scheduler)
"""

import json
import os

from config import get_logger, PRODUCTOS
from core.cerebro import MarketingCerebro
from social.publisher import MetaAdsManager
from core.image_generator import ImageGenerator

from dotenv import load_dotenv

load_dotenv()

logger = get_logger("campaign_runner")


class CampaignRunner:
    def __init__(self, modelo_imagen="gemini-2.5-flash-image"):
        self.cerebro = MarketingCerebro()
        self.meta = MetaAdsManager()
        self.image_gen = ImageGenerator(model=modelo_imagen)

    def generar_y_publicar_organico(self, objetivo, publico, plataforma="Facebook", con_imagen=True, producto="graf"):
        """
        Flujo completo: Gemini genera estrategia → genera imagen → publica post.
        
        Cada post va dirigido a un PRODUCTO específico con su URL, CTA y contexto.
        Si producto='humanizar', se hace awareness general del ecosistema.
        
        Args:
            objetivo: Objetivo de marketing
            publico: Público objetivo
            plataforma: Facebook o Instagram
            con_imagen: Si True, genera imagen con IA y la publica
            producto: Key del producto (emw, graf, meravuelta, sinergia, agora, terminal, fiar, humanizar)
        """
        from image_generator import ImageGenerator
        prod_info = PRODUCTOS.get(producto, PRODUCTOS["humanizar"])
        
        # Enriquecer el objetivo con contexto del producto
        objetivo_enriquecido = (
            f"{objetivo}. "
            f"Producto: {prod_info['nombre']} — {prod_info['descripcion']}. "
            f"URL: {prod_info.get('url', 'humanizar.co')}. "
            f"CTA: {prod_info.get('cta', 'humanizar.co')}."
        )
        if prod_info.get('precio_desde'):
            objetivo_enriquecido += f" Precio desde: {prod_info['precio_desde']}."
        if prod_info.get('publico_objetivo'):
            publico = f"{publico}. Específicamente: {prod_info['publico_objetivo']}"
        
        logger.info("Producto: %s (%s)", prod_info['nombre'], prod_info.get('tipo', 'producto'))
        logger.info("URL: %s | CTA: %s", prod_info.get('url', 'N/A'), prod_info.get('cta', 'N/A'))
        logger.info("[Cerebro] Generando estrategia...")
        
        estrategia_json = self.cerebro.generar_campana(objetivo_enriquecido, publico)
        estrategia = json.loads(estrategia_json)
        
        # Gemini a veces devuelve array
        if isinstance(estrategia, list):
            estrategia = estrategia[0]
        
        logger.info("Estrategia: %s", estrategia.get('ESTRATEGIA', 'N/A'))
        
        # Seleccionar copy segun plataforma
        copy = estrategia["COPIES"].get(plataforma, estrategia["COPIES"].get("Facebook", ""))
        hashtags = " ".join(estrategia.get("HASHTAGS", []))
        
        # Usar URL y CTA del producto específico (no siempre humanizar.co)
        url_producto = prod_info.get("url", "https://www.humanizar.co")
        cta_producto = prod_info.get("cta", "humanizar.co")
        mensaje_final = f"{copy}\n\n{hashtags}\n\n🔗 {url_producto}"
        
        logger.info("Mensaje (%d chars): %s...", len(mensaje_final), mensaje_final[:120])
        
        # Generar imagen con IA si se solicita
        image_path = None
        if con_imagen:
            prompt_imagen = estrategia.get("PROMPT_IMAGEN", "")
            if prompt_imagen:
                logger.info("[Imagen] Generando con Gemini — prompt: %s...", prompt_imagen[:80])
                image_path = self.image_gen.generar_imagen_para_post(
                    prompt_imagen,
                    producto_key=producto,
                    aspect_ratio="1:1",
                )
                if image_path:
                    logger.info("Imagen generada: %s", image_path)
                else:
                    logger.warning("No se pudo generar imagen, publicando solo texto")
        
        # Publicar en la pagina
        logger.info("Publicando en la página de Facebook...")
        if image_path:
            resultado = self.meta.publicar_con_imagen(mensaje_final, image_path=image_path)
        else:
            resultado = self.meta.publicar_en_feed(mensaje_final, link=url_producto)
        
        if resultado.get("success"):
            post_key = "post_id" if "post_id" in resultado else "photo_id"
            logger.info("POST PUBLICADO: %s", resultado.get(post_key))
        else:
            logger.error("Error publicando: %s", resultado.get('error'))
        
        return {
            "estrategia": estrategia,
            "mensaje": mensaje_final,
            "imagen_path": image_path,
            "resultado_publicacion": resultado
        }

    def ejecutar_campana_piloto(self):
        """Flujo original: genera + simula campana de ads (sin gastar)."""
        logger.info("[Cerebro] Analizando estrategia para Graf...")
        
        objetivo = "Atraer duenos de e-commerce que venden por WhatsApp pero no tienen orden en sus pedidos."
        publico = "Duenos de negocios en Colombia, 25-45 anos, interesados en Shopify, emprendimiento y logistica."
        
        estrategia_json = self.cerebro.generar_campana(objetivo, publico)
        estrategia = json.loads(estrategia_json)
        if isinstance(estrategia, list):
            estrategia = estrategia[0]
        
        logger.info("Estrategia Generada: %s", estrategia.get('ESTRATEGIA', 'N/A'))
        logger.info("Copy IG: %s...", estrategia['COPIES']['Instagram'][:80])
        
        # Simulacion de campana (sin inyectar dinero real)
        presupuesto = 20000
        resultado_meta = self.meta.inyectar_presupuesto_campana(
            estrategia.get('ESTRATEGIA', 'Campana Humanizar'), 
            presupuesto
        )
        
        return {
            "status": "success",
            "campana": estrategia.get('ESTRATEGIA'),
            "meta_status": resultado_meta
        }

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Humanizar Ads Automator")
    parser.add_argument("--publicar", action="store_true", help="Generar con IA y publicar post organico real")
    parser.add_argument("--campana", action="store_true", help="Crear campana de ads (PAUSADA)")
    parser.add_argument("--imagenes", action="store_true", help="Generar paquete de imagenes de marca")
    parser.add_argument("--programar", action="store_true", help="Generar calendario semanal y encolar posts (scheduler)")
    parser.add_argument("--auto", action="store_true", help="Modo autopiloto: genera + evalúa + auto-aprueba + publica")
    parser.add_argument("--revisar", action="store_true", help="Ver cola de posts pendientes")
    parser.add_argument("--publicar-siguiente", action="store_true", help="Publicar siguiente post aprobado de la cola")
    parser.add_argument("--objetivo", type=str, default="Atraer emprendedores que necesitan automatizar ventas por WhatsApp", help="Objetivo de la campana")
    parser.add_argument("--publico", type=str, default="Duenos de negocios en Colombia, 25-45 anos, e-commerce", help="Publico objetivo")
    parser.add_argument("--producto", type=str, default="graf", help="Producto: emw, graf, meravuelta, sinergia, agora, terminal, fiar, humanizar (awareness)")
    parser.add_argument("--sin-imagen", action="store_true", help="Publicar sin generar imagen (solo texto)")
    parser.add_argument("--modelo-imagen", type=str, default="gemini-2.5-flash-image",
                        help="Modelo: gemini-2.5-flash-image o gemini-3-pro-image-preview")
    
    args = parser.parse_args()
    automator = CampaignRunner(modelo_imagen=args.modelo_imagen)
    
    if args.publicar:
        print("🚀 MODO: Publicacion organica real" + (" (con imagen IA)" if not args.sin_imagen else " (solo texto)"))
        print("=" * 50)
        result = automator.generar_y_publicar_organico(
            args.objetivo, args.publico,
            con_imagen=not args.sin_imagen,
            producto=args.producto,
        )
        print("\n📊 Resultado final:")
        print(json.dumps(result["resultado_publicacion"], indent=2, ensure_ascii=False))
    elif args.campana:
        print("🚀 MODO: Creacion de campana de Ads")
        print("=" * 50)
        print(automator.ejecutar_campana_piloto())
    elif args.imagenes:
        print(f"🎨 MODO: Generación de paquete de imágenes para '{args.producto}'")
        print("=" * 50)
        if args.producto == "todos":
            automator.image_gen.generar_todos_los_paquetes()
        else:
            automator.image_gen.generar_paquete_marca(args.producto)
    elif args.programar:
        from scheduler import PublicationScheduler
        print("📅 MODO: Generar calendario semanal y encolar")
        print("=" * 50)
        scheduler = PublicationScheduler(modelo_imagen=args.modelo_imagen)
        scheduler.generar_semana([args.producto] if args.producto != "todos" else None)
    elif args.auto:
        from scheduler import PublicationScheduler
        print("🤖 MODO: Autopiloto completo")
        print("=" * 50)
        scheduler = PublicationScheduler(modelo_imagen=args.modelo_imagen)
        scheduler.modo_auto(
            [args.producto] if args.producto != "todos" else None,
            publicar=True,
        )
    elif args.revisar:
        from scheduler import PublicationScheduler
        scheduler = PublicationScheduler(modelo_imagen=args.modelo_imagen)
        scheduler.revisar_cola()
    elif getattr(args, 'publicar_siguiente', False):
        from scheduler import PublicationScheduler
        scheduler = PublicationScheduler(modelo_imagen=args.modelo_imagen)
        scheduler.publicar_siguiente()
    else:
        parser.print_help()
