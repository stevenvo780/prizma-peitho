#!/usr/bin/env python3
"""
run.py — Entry point único del Marketing Autopilot.

Uso:
  python3 run.py campana           # Campaña interactiva step-by-step
  python3 run.py auto              # FULL PASS autónomo (todos los productos)
  python3 run.py auto --dry-run    # Solo generar + evaluar (sin publicar)
  python3 run.py generar           # Generar imágenes
  python3 run.py evaluar           # Evaluar imágenes con IA
  python3 run.py publicar          # Publicar en FB/IG
  python3 run.py analytics         # Insights de redes
  python3 run.py token             # Gestionar tokens Meta
  python3 run.py test              # Tests de conexión
"""

import sys
import os
from dotenv import load_dotenv

# Cargar .env
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

# Asegurar que src/ esté en el path
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

COMANDOS = {
    "campana":   "Campaña interactiva step-by-step (generar → evaluar → revisar → publicar)",
    "auto":      "FULL PASS autónomo — genera, evalúa (×3) y publica sin intervención",
    "generar":   "Generar imágenes de marca con IA",
    "evaluar":   "Evaluar y depurar imágenes (crítico visual IA)",
    "publicar":  "Publicar posts en Facebook/Instagram",
    "instagram": "Publicación masiva en Instagram",
    "analytics": "Insights y métricas de FB/IG",
    "token":     "Gestionar tokens de Meta (refresh, validar)",
    "test":      "Tests de conexión y dry-run",
    "scheduler": "Cola de publicaciones y calendario",
}


def mostrar_ayuda():
    print()
    print("\033[1m  HUMANIZAR SYSTEMS — Marketing Autopilot\033[0m")
    print("\033[2m  ─────────────────────────────────────────\033[0m")
    print()
    print("  \033[1mUso:\033[0m  python3 run.py <comando> [opciones]")
    print()
    print("  \033[1mComandos disponibles:\033[0m")
    print()
    for cmd, desc in COMANDOS.items():
        print(f"    \033[93m{cmd:12s}\033[0m {desc}")
    print()
    print("  \033[2mEjemplos:\033[0m")
    print("    python3 run.py campana")
    print("    python3 run.py auto                          # Full pass todos los productos")
    print("    python3 run.py auto --productos emw graf --dry-run")
    print("    python3 run.py generar --producto emw")
    print("    python3 run.py generar --campana 'Marzo 2026' --productos emw graf")
    print("    python3 run.py evaluar --todos --regenerar")
    print("    python3 run.py publicar --producto graf --objetivo 'Vender suscripciones'")
    print("    python3 run.py analytics --reporte")
    print()


def main():
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help", "help"):
        mostrar_ayuda()
        return

    comando = sys.argv[1].lower()
    # Quitar el comando de argv para que el módulo hijo reciba solo sus flags
    sys.argv = [sys.argv[0]] + sys.argv[2:]

    if comando == "campana":
        from campanas.campana_interactiva import main as run
        run()

    elif comando == "auto":
        from campanas.campana_auto import main as run_auto
        run_auto()

    elif comando == "generar":
        from core.image_generator import ImageGenerator
        from config import PRODUCTOS
        # Re-parsear args con el CLI existente del módulo
        import argparse
        parser = argparse.ArgumentParser(description="Generar imágenes de marca")
        parser.add_argument("--producto", type=str, help=f"Producto: {list(PRODUCTOS.keys())}")
        parser.add_argument("--todos", action="store_true", help="Todos los productos")
        parser.add_argument("--texto", type=str, help="Prompt libre")
        parser.add_argument("--ratio", type=str, default="1:1")
        parser.add_argument("--modelo", type=str, default="gemini-3-pro-image-preview")
        parser.add_argument("--campana", type=str, help="Nombre de campaña")
        parser.add_argument("--tematica", type=str, default="")
        parser.add_argument("--productos", nargs="+", default=None)
        parser.add_argument("--formatos", nargs="+", default=None)
        parser.add_argument("--listar-campanas", action="store_true")
        args = parser.parse_args()
        gen = ImageGenerator(model=args.modelo)

        if args.listar_campanas:
            campanas = ImageGenerator.listar_campanas()
            if not campanas:
                print("📭 No hay campañas creadas aún.")
            else:
                print(f"\n🎬 CAMPAÑAS ({len(campanas)}):")
                for c in campanas:
                    print(f"  📁 {c['carpeta']} — {c['nombre']} ({c['total_imagenes']} imgs)")
        elif args.campana:
            gen.generar_campana(
                nombre_campana=args.campana,
                productos=args.productos or ["graf", "emw"],
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

    elif comando == "evaluar":
        from core.image_critic import ImageCritic
        from config import PRODUCTOS
        import argparse
        parser = argparse.ArgumentParser(description="Evaluar imágenes")
        parser.add_argument("--producto", type=str, help=f"Producto: {list(PRODUCTOS.keys())}")
        parser.add_argument("--todos", action="store_true")
        parser.add_argument("--regenerar", action="store_true")
        parser.add_argument("--umbral", type=int, default=70)
        parser.add_argument("--max-intentos", type=int, default=2)
        parser.add_argument("--reporte", type=str, default=None)
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
            return
        critic.exportar_reporte(args.reporte)

    elif comando == "publicar":
        from campanas.campaign_runner import CampaignRunner
        import argparse
        parser = argparse.ArgumentParser(description="Publicar en Facebook")
        parser.add_argument("--producto", type=str, required=True)
        parser.add_argument("--objetivo", type=str, default="Generar awareness")
        parser.add_argument("--publico", type=str, default="Pymes colombianas")
        parser.add_argument("--sin-imagen", action="store_true")
        parser.add_argument("--modelo-imagen", type=str, default="gemini-3-pro-image-preview")
        args = parser.parse_args()
        runner = CampaignRunner()
        runner.ejecutar_campana_completa(
            producto=args.producto,
            objetivo=args.objetivo,
            publico_objetivo=args.publico,
            generar_imagen=not args.sin_imagen,
            modelo_imagen=args.modelo_imagen,
        )

    elif comando == "instagram":
        from social.publicar_instagram import main as run
        run()

    elif comando == "analytics":
        from social.analytics import SocialAnalytics
        import argparse
        parser = argparse.ArgumentParser(description="Analytics FB/IG")
        parser.add_argument("--resumen", action="store_true")
        parser.add_argument("--posts", action="store_true")
        parser.add_argument("--best-time", action="store_true")
        parser.add_argument("--reporte", action="store_true")
        parser.add_argument("--dias", type=int, default=28)
        args = parser.parse_args()
        analytics = SocialAnalytics()

        if args.reporte:
            ruta = analytics.generar_reporte()
            print(f"📄 Reporte: {ruta}")
        elif args.posts:
            metrics = analytics.get_posts_metrics(limit=10)
            for m in metrics:
                print(f"  {m}")
        elif args.best_time:
            best = analytics.analyze_best_times()
            print(f"  Mejores horarios: {best}")
        elif args.resumen:
            insights = analytics.get_page_insights(days=args.dias)
            print(f"  Insights: {insights}")
        else:
            parser.print_help()

    elif comando == "token":
        from social.token_manager import TokenManager
        import argparse
        parser = argparse.ArgumentParser(description="Gestión de tokens Meta")
        parser.add_argument("--refresh", action="store_true", help="Renovar token")
        parser.add_argument("--validar", action="store_true", help="Verificar token actual")
        parser.add_argument("--info", action="store_true", help="Info del token")
        args = parser.parse_args()
        tm = TokenManager()

        # Obtener tokens disponibles
        page_token = os.getenv("META_PAGE_TOKEN", "").strip("'")
        user_token = os.getenv("META_ACCESS_TOKEN", "").strip("'")
        token_to_check = page_token or user_token

        if args.refresh:
            token = tm.get_valid_page_token()
            if token:
                print(f"✅ Token renovado: {token[:20]}...")
            else:
                print("❌ No se pudo renovar")
        elif args.validar:
            if not token_to_check:
                print("❌ No hay token configurado en .env")
            else:
                valid = tm.token_is_valid(token_to_check)
                print(f"{'✅ Válido' if valid else '❌ Inválido o expirado'}")
        elif args.info:
            if not token_to_check:
                print("❌ No hay token configurado en .env")
            else:
                info = tm.debug_token(token_to_check)
                print(f"  Válido: {info.get('is_valid', '?')}")
                print(f"  App: {info.get('app_id', '?')}")
                print(f"  Scopes: {', '.join(info.get('scopes', []))}")
                expires = info.get("expires_at", 0)
                if expires == 0:
                    print("  Expira: NUNCA")
                else:
                    from datetime import datetime
                    print(f"  Expira: {datetime.fromtimestamp(expires)}")
        else:
            parser.print_help()

    elif comando == "test":
        from utils.tester import test_brain, test_meta_auth
        import argparse
        parser = argparse.ArgumentParser(description="Tests de conexión")
        parser.add_argument("--brain", action="store_true", help="Test de IA (Gemini)")
        parser.add_argument("--meta", action="store_true", help="Test de auth Meta")
        args = parser.parse_args()

        if args.brain:
            test_brain()
        elif args.meta:
            test_meta_auth()
        else:
            # Sin flags → ejecutar todos los tests
            test_meta_auth()
            test_brain()

    elif comando == "scheduler":
        from utils.scheduler import PostQueue, PublicationScheduler
        import argparse
        parser = argparse.ArgumentParser(description="Cola de publicaciones")
        parser.add_argument("--stats", action="store_true")
        parser.add_argument("--pendientes", action="store_true")
        parser.add_argument("--semana", action="store_true")
        args = parser.parse_args()
        q = PostQueue()

        if args.stats:
            s = q.stats()
            for k, v in s.items():
                print(f"  {k}: {v}")
        elif args.pendientes:
            pendientes = q.get_pendientes()
            if not pendientes:
                print("  No hay posts pendientes.")
            for p in pendientes:
                print(f"  [{p.get('id', '?')}] {p.get('producto', '?')} — {p.get('titulo', '?')}")
        elif args.semana:
            sched = PublicationScheduler()
            ids = sched.generar_semana()
            print(f"  ✅ {len(ids)} posts generados para la semana")
        else:
            parser.print_help()

    else:
        print(f"\n  ❌ Comando desconocido: '{comando}'")
        mostrar_ayuda()


if __name__ == "__main__":
    main()
