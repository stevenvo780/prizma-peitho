"""
scheduler.py — Programador de publicaciones automáticas para Prizma (ex Steven Vallejo).

Funcionalidades:
  - Genera calendario editorial semanal con Cerebro IA
  - Cola de posts pendientes con filtrado de calidad
  - Publicación automática en horarios óptimos
  - Aprobación manual opcional (modo review)
  - Log de publicaciones y métricas

Modos de operación:
  - --generar-semana: Genera calendario + copies + imágenes para la semana
  - --revisar: Muestra cola de posts pendientes para aprobación
  - --aprobar ID: Aprueba un post específico
  - --publicar-siguiente: Publica el siguiente post aprobado
  - --auto: Modo piloto automático (genera, evalúa, publica si calidad > umbral)
  - --status: Estado actual de la cola
"""

import os
import json
import time
import argparse
from datetime import datetime, timedelta
from pathlib import Path
from dotenv import load_dotenv

from config import (
    get_logger, PRODUCTOS, QUALITY_THRESHOLD, QUEUE_DIR,
    LOG_DIR, PRODUCTOS_ACTIVOS, HORARIOS_OPTIMOS,
    PUBLISH_INTERVAL_SECONDS,
)
from core.cerebro import MarketingCerebro
from social.publisher import MetaAdsManager
from core.image_generator import ImageGenerator

load_dotenv()

logger = get_logger("scheduler")

# ------------------------------------------------------------------ #
#  CONFIGURACIÓN (importada de config.py)
# ------------------------------------------------------------------ #

LOG_FILE = os.path.join(str(LOG_DIR), "publicaciones.log")

os.makedirs(str(QUEUE_DIR), exist_ok=True)


# ------------------------------------------------------------------ #
#  COLA DE PUBLICACIÓN
# ------------------------------------------------------------------ #

class PostQueue:
    """Gestiona la cola de posts pendientes de publicación."""

    def __init__(self):
        self.queue_file = os.path.join(str(QUEUE_DIR), "queue.json")
        self._load()

    def _load(self):
        if os.path.exists(self.queue_file):
            with open(self.queue_file, "r", encoding="utf-8") as f:
                self.posts = json.load(f)
        else:
            self.posts = []

    def _save(self):
        with open(self.queue_file, "w", encoding="utf-8") as f:
            json.dump(self.posts, f, indent=2, ensure_ascii=False)

    def add(self, post: dict):
        """Agrega un post a la cola."""
        max_id = max((p.get("id", 0) for p in self.posts), default=0)
        post["id"] = max_id + 1
        post["created_at"] = datetime.now().isoformat()
        post["status"] = "pendiente"  # pendiente → aprobado → publicado → fallido
        self.posts.append(post)
        self._save()
        return post["id"]

    def get_pendientes(self) -> list:
        return [p for p in self.posts if p["status"] == "pendiente"]

    def get_aprobados(self) -> list:
        return [p for p in self.posts if p["status"] == "aprobado"]

    def get_publicados(self) -> list:
        return [p for p in self.posts if p["status"] == "publicado"]

    def aprobar(self, post_id: int):
        for p in self.posts:
            if p["id"] == post_id:
                p["status"] = "aprobado"
                p["approved_at"] = datetime.now().isoformat()
                self._save()
                return True
        return False

    def rechazar(self, post_id: int, motivo: str = ""):
        for p in self.posts:
            if p["id"] == post_id:
                p["status"] = "rechazado"
                p["reject_reason"] = motivo
                self._save()
                return True
        return False

    def marcar_publicado(self, post_id: int, resultado: dict):
        for p in self.posts:
            if p["id"] == post_id:
                p["status"] = "publicado"
                p["published_at"] = datetime.now().isoformat()
                p["resultado"] = resultado
                self._save()
                return True
        return False

    def marcar_fallido(self, post_id: int, error: str):
        for p in self.posts:
            if p["id"] == post_id:
                p["status"] = "fallido"
                p["error"] = error
                self._save()
                return True
        return False

    def stats(self) -> dict:
        from collections import Counter
        estados = Counter(p["status"] for p in self.posts)
        return {
            "total": len(self.posts),
            "pendientes": estados.get("pendiente", 0),
            "aprobados": estados.get("aprobado", 0),
            "publicados": estados.get("publicado", 0),
            "rechazados": estados.get("rechazado", 0),
            "fallidos": estados.get("fallido", 0),
        }


# ------------------------------------------------------------------ #
#  SCHEDULER PRINCIPAL
# ------------------------------------------------------------------ #

class PublicationScheduler:
    """Orquesta generación, evaluación y publicación de contenido."""

    def __init__(self, modelo_imagen="gemini-2.5-flash-image"):
        self.cerebro = MarketingCerebro()
        self.meta = MetaAdsManager()
        self.image_gen = ImageGenerator(model=modelo_imagen)
        self.queue = PostQueue()

    def generar_semana(self, productos_foco: list[str] = None) -> list[int]:
        """
        Genera un calendario editorial completo para la semana.
        Cada día → genera copy con Cerebro → evalúa calidad → genera imagen → encola.
        
        Retorna lista de IDs de posts encolados.
        """
        if not productos_foco:
            productos_foco = PRODUCTOS_ACTIVOS[:4]  # Top 4 por defecto

        print("📅 Generando calendario editorial semanal...")
        print(f"   Productos en foco: {productos_foco}")
        print("=" * 60)

        # 1. Generar calendario con Cerebro
        calendario_json = self.cerebro.generar_calendario_semanal(productos_foco)
        calendario = json.loads(calendario_json)
        if not isinstance(calendario, list):
            calendario = [calendario]

        ids_encolados = []

        for i, dia_plan in enumerate(calendario):
            dia = dia_plan.get("dia", f"dia_{i+1}")
            producto_key = dia_plan.get("producto", "graf")
            objetivo = dia_plan.get("objetivo", "Awareness general")
            publico = dia_plan.get("publico", "Pymes colombianas")
            tipo = dia_plan.get("tipo_contenido", "awareness")
            gancho = dia_plan.get("gancho", "")

            print(f"\n📆 {dia.upper()} — {tipo} — {producto_key}")
            print(f"   Objetivo: {objetivo}")
            print(f"   Gancho: {gancho}")

            # 2. Generar campaña/copy con Cerebro
            prod_info = PRODUCTOS.get(producto_key, PRODUCTOS.get("prizma"))
            objetivo_enriquecido = (
                f"{objetivo}. "
                f"Producto: {prod_info['nombre']} — {prod_info['descripcion']}. "
                f"URL: {prod_info.get('url', 'prisma-enterprice.cloud')}. "
                f"CTA: {prod_info.get('cta', 'prisma-enterprice.cloud')}."
            )
            if prod_info.get("precio_desde"):
                objetivo_enriquecido += f" Precio desde: {prod_info['precio_desde']}."

            try:
                estrategia_json = self.cerebro.generar_campana(objetivo_enriquecido, publico)
                estrategia = json.loads(estrategia_json)
                if isinstance(estrategia, list):
                    estrategia = estrategia[0]
            except Exception as e:
                print(f"   ❌ Error generando copy: {e}")
                continue

            # 3. Evaluar calidad del copy
            copy_fb = estrategia.get("COPIES", {}).get("Facebook", "")
            try:
                evaluacion = self.cerebro.evaluar_calidad_post(copy_fb, producto_key)
                score = evaluacion.get("score_total", 0)
                aprobado_auto = evaluacion.get("aprobado", False)
                print(f"   📊 Calidad: {score}/100 — {'✅ Aprobado' if aprobado_auto else '⚠️ Revisar'}")
                if evaluacion.get("feedback"):
                    print(f"   💬 {evaluacion['feedback'][:120]}")
            except Exception as e:
                print(f"   ⚠️ No se pudo evaluar calidad: {e}")
                score = 75  # Default medio
                aprobado_auto = True
                evaluacion = {"score_total": score}

            # 4. Generar imagen
            prompt_imagen = estrategia.get("PROMPT_IMAGEN", "")
            imagen_path = None
            if prompt_imagen:
                try:
                    print(f"   🎨 Generando imagen para {producto_key}...")
                    imagen_path = self.image_gen.generar_imagen_para_post(
                        prompt_imagen,
                        producto_key=producto_key,
                        aspect_ratio="1:1",
                    )
                    if imagen_path:
                        print(f"   ✅ Imagen: {imagen_path}")
                except Exception as e:
                    print(f"   ⚠️ Error generando imagen: {e}")

            # 5. Construir mensaje final
            hashtags = " ".join(estrategia.get("HASHTAGS", []))
            url_producto = prod_info.get("url", "https://prisma-enterprice.cloud")
            copy_ig = estrategia.get("COPIES", {}).get("Instagram", "")

            mensaje_fb = f"{copy_fb}\n\n{hashtags}\n\n🔗 {url_producto}"
            mensaje_ig = f"{copy_ig}\n\n{hashtags}"

            # 6. Encolar
            post_data = {
                "dia": dia,
                "tipo_contenido": tipo,
                "producto": producto_key,
                "producto_nombre": prod_info["nombre"],
                "estrategia": estrategia.get("ESTRATEGIA", ""),
                "pilar_narrativo": estrategia.get("PILAR_NARRATIVO", ""),
                "copy_facebook": mensaje_fb,
                "copy_instagram": mensaje_ig,
                "prompt_imagen": prompt_imagen,
                "imagen_path": imagen_path,
                "url_producto": url_producto,
                "cta": prod_info.get("cta", ""),
                "hashtags": estrategia.get("HASHTAGS", []),
                "calidad_score": score,
                "calidad_evaluacion": evaluacion,
                "gancho": gancho,
            }

            # Auto-aprobar si score > umbral
            post_id = self.queue.add(post_data)
            if score >= QUALITY_THRESHOLD and aprobado_auto:
                self.queue.aprobar(post_id)
                print(f"   ✅ Post #{post_id} auto-aprobado (score {score} >= {QUALITY_THRESHOLD})")
            else:
                print(f"   📋 Post #{post_id} encolado para revisión manual (score {score})")

            ids_encolados.append(post_id)

        print(f"\n{'=' * 60}")
        print(f"📊 Resumen: {len(ids_encolados)} posts generados")
        stats = self.queue.stats()
        print(f"   Cola: {stats['aprobados']} aprobados | {stats['pendientes']} pendientes | {stats['publicados']} publicados")

        return ids_encolados

    def publicar_siguiente(self) -> dict:
        """
        Publica el siguiente post aprobado de la cola.
        Retorna resultado de la publicación.
        """
        aprobados = self.queue.get_aprobados()
        if not aprobados:
            print("📭 No hay posts aprobados en la cola.")
            return {"error": "Cola vacía"}

        post = aprobados[0]
        post_id = post["id"]
        print(f"\n📤 Publicando post #{post_id}: {post['estrategia']}")
        print(f"   Producto: {post['producto_nombre']}")
        print(f"   Copy: {post['copy_facebook'][:100]}...")

        try:
            imagen = post.get("imagen_path")
            if imagen and os.path.exists(imagen):
                resultado = self.meta.publicar_con_imagen(
                    post["copy_facebook"],
                    image_path=imagen,
                )
            else:
                resultado = self.meta.publicar_en_feed(
                    post["copy_facebook"],
                    link=post.get("url_producto"),
                )

            if resultado.get("success"):
                post_key = "post_id" if "post_id" in resultado else "photo_id"
                print(f"   ✅ Publicado: {resultado.get(post_key)}")
                self.queue.marcar_publicado(post_id, resultado)
                self._log_publicacion(post, resultado)
            else:
                error = resultado.get("error", "Error desconocido")
                print(f"   ❌ Error: {error}")
                self.queue.marcar_fallido(post_id, error)

            return resultado

        except Exception as e:
            error = str(e)
            print(f"   ❌ Excepción: {error}")
            self.queue.marcar_fallido(post_id, error)
            return {"error": error}

    def publicar_lote(self, max_posts: int = 3, intervalo_seg: int = PUBLISH_INTERVAL_SECONDS) -> list:
        """
        Publica un lote de posts aprobados con intervalo entre ellos.
        Default: máx 3 posts, 5 min entre cada uno.
        """
        resultados = []
        for i in range(max_posts):
            aprobados = self.queue.get_aprobados()
            if not aprobados:
                print(f"\n📭 No más posts aprobados. Publicados: {len(resultados)}")
                break

            resultado = self.publicar_siguiente()
            resultados.append(resultado)

            if i < max_posts - 1 and self.queue.get_aprobados():
                print(f"\n⏳ Esperando {intervalo_seg}s antes del siguiente post...")
                time.sleep(intervalo_seg)

        return resultados

    def revisar_cola(self):
        """Muestra todos los posts pendientes para revisión."""
        pendientes = self.queue.get_pendientes()
        aprobados = self.queue.get_aprobados()

        print(f"\n📋 COLA DE PUBLICACIÓN")
        print(f"{'=' * 60}")

        if pendientes:
            print(f"\n⏳ PENDIENTES DE REVISIÓN ({len(pendientes)}):")
            for p in pendientes:
                self._print_post_summary(p)

        if aprobados:
            print(f"\n✅ APROBADOS - LISTOS PARA PUBLICAR ({len(aprobados)}):")
            for p in aprobados:
                self._print_post_summary(p)

        if not pendientes and not aprobados:
            print("\n📭 Cola vacía. Genera contenido con --generar-semana")

        stats = self.queue.stats()
        print(f"\n📊 Total: {stats['total']} | Pendientes: {stats['pendientes']} | "
              f"Aprobados: {stats['aprobados']} | Publicados: {stats['publicados']} | "
              f"Rechazados: {stats['rechazados']}")

    def _print_post_summary(self, post: dict):
        print(f"\n  #{post['id']} [{post.get('dia', '?')}] {post.get('producto_nombre', '?')} — {post.get('tipo_contenido', '?')}")
        print(f"     Estrategia: {post.get('estrategia', 'N/A')[:80]}")
        print(f"     Score: {post.get('calidad_score', '?')}/100")
        print(f"     Gancho: {post.get('gancho', 'N/A')[:80]}")
        print(f"     Imagen: {'✅' if post.get('imagen_path') else '❌'}")
        print(f"     Estado: {post['status']}")

    def _log_publicacion(self, post: dict, resultado: dict):
        """Registra publicación en log."""
        os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
        entry = {
            "timestamp": datetime.now().isoformat(),
            "post_id": post["id"],
            "producto": post.get("producto"),
            "estrategia": post.get("estrategia"),
            "tipo": post.get("tipo_contenido"),
            "score": post.get("calidad_score"),
            "resultado": resultado,
        }
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def modo_auto(self, productos_foco: list[str] = None, publicar: bool = False):
        """
        Modo piloto automático:
        1. Genera calendario semanal
        2. Evalúa calidad de cada copy
        3. Auto-aprueba si score >= umbral
        4. Opcionalmente publica los aprobados
        """
        print("🤖 MODO AUTOPILOTO")
        print("=" * 60)

        # Generar semana
        ids = self.generar_semana(productos_foco)

        if publicar:
            print(f"\n🚀 Publicando posts auto-aprobados...")
            self.publicar_lote(max_posts=len(ids))
        else:
            print(f"\n📋 Posts generados. Usa --revisar para ver la cola.")
            print(f"   Usa --publicar-siguiente para publicar uno a uno.")
            print(f"   Usa --publicar-lote para publicar todos los aprobados.")


# ------------------------------------------------------------------ #
#  CLI
# ------------------------------------------------------------------ #

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Scheduler de Publicaciones — Prizma",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Ejemplos de uso:
  python scheduler.py --generar-semana                      # Genera 7 días de contenido
  python scheduler.py --generar-semana --productos emw graf # Foco en EMW y Graf
  python scheduler.py --revisar                             # Ver cola de posts
  python scheduler.py --aprobar 1 2 3                       # Aprobar posts específicos
  python scheduler.py --publicar-siguiente                  # Publicar el siguiente aprobado
  python scheduler.py --publicar-lote                       # Publicar todos los aprobados
  python scheduler.py --auto                                # Generar + auto-aprobar
  python scheduler.py --auto --publicar                     # Full autopilot (genera + publica)
  python scheduler.py --status                              # Estado de la cola
        """
    )

    parser.add_argument("--generar-semana", action="store_true",
                        help="Genera calendario editorial + copies + imágenes para la semana")
    parser.add_argument("--productos", nargs="+", default=None,
                        help=f"Productos foco: {PRODUCTOS_ACTIVOS}")
    parser.add_argument("--revisar", action="store_true",
                        help="Muestra la cola de posts pendientes")
    parser.add_argument("--aprobar", nargs="+", type=int,
                        help="Aprueba posts por ID")
    parser.add_argument("--rechazar", nargs="+", type=int,
                        help="Rechaza posts por ID")
    parser.add_argument("--publicar-siguiente", action="store_true",
                        help="Publica el siguiente post aprobado")
    parser.add_argument("--publicar-lote", action="store_true",
                        help="Publica todos los posts aprobados (con intervalo)")
    parser.add_argument("--max-posts", type=int, default=3,
                        help="Máximo de posts a publicar en lote (default: 3)")
    parser.add_argument("--intervalo", type=int, default=300,
                        help="Segundos entre publicaciones en lote (default: 300)")
    parser.add_argument("--auto", action="store_true",
                        help="Modo autopiloto: genera + evalúa + auto-aprueba")
    parser.add_argument("--publicar", action="store_true",
                        help="En modo --auto, también publica los aprobados")
    parser.add_argument("--status", action="store_true",
                        help="Muestra estado de la cola")
    parser.add_argument("--modelo-imagen", type=str, default="gemini-2.5-flash-image",
                        help="Modelo de imagen: gemini-2.5-flash-image o gemini-3-pro-image-preview")

    args = parser.parse_args()
    scheduler = PublicationScheduler(modelo_imagen=args.modelo_imagen)

    if args.generar_semana:
        scheduler.generar_semana(args.productos)

    elif args.revisar:
        scheduler.revisar_cola()

    elif args.aprobar:
        for pid in args.aprobar:
            if scheduler.queue.aprobar(pid):
                print(f"✅ Post #{pid} aprobado")
            else:
                print(f"❌ Post #{pid} no encontrado")

    elif args.rechazar:
        for pid in args.rechazar:
            if scheduler.queue.rechazar(pid, motivo="Rechazado manualmente"):
                print(f"🚫 Post #{pid} rechazado")
            else:
                print(f"❌ Post #{pid} no encontrado")

    elif args.publicar_siguiente:
        scheduler.publicar_siguiente()

    elif args.publicar_lote:
        scheduler.publicar_lote(max_posts=args.max_posts, intervalo_seg=args.intervalo)

    elif args.auto:
        scheduler.modo_auto(args.productos, publicar=args.publicar)

    elif args.status:
        stats = scheduler.queue.stats()
        print(f"\n📊 Estado de la cola:")
        for k, v in stats.items():
            print(f"   {k}: {v}")

    else:
        parser.print_help()
