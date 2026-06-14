"""
analytics.py — Métricas y reporting de Facebook/Instagram.

Consulta insights de las publicaciones, genera reportes de engagement,
e identifica los mejores horarios y tipos de contenido.

Uso:
  python3 analytics.py --resumen           # Resumen de últimos 30 días
  python3 analytics.py --posts             # Métricas por post
  python3 analytics.py --best-time         # Mejores horarios para publicar
  python3 analytics.py --reporte           # Genera reporte completo en MD
"""

import os
import json
import argparse
from datetime import datetime, timedelta
from collections import defaultdict

import requests
from dotenv import load_dotenv

from config import (
    get_logger, GRAPH_API_BASE, META_PAGE_ID,
    META_PAGE_TOKEN, META_INSTAGRAM_ID, OUTPUT_DIR, retry,
)

load_dotenv()

logger = get_logger("analytics")

# ------------------------------------------------------------------ #
#  CLIENTE DE ANALYTICS
# ------------------------------------------------------------------ #


class SocialAnalytics:
    """Consulta métricas de Facebook e Instagram via Graph API."""

    def __init__(self, page_token: str = None):
        self.page_token = page_token or META_PAGE_TOKEN or os.getenv("META_PAGE_TOKEN", "")
        self.page_id = META_PAGE_ID or os.getenv("META_PAGE_ID", "")
        self.ig_id = META_INSTAGRAM_ID or os.getenv("META_INSTAGRAM_ID", "")

        if not self.page_token:
            logger.warning("No hay PAGE_TOKEN configurado — analytics limitado")

    # ------------------------------------------------------------------ #
    #  FACEBOOK — Insights de página
    # ------------------------------------------------------------------ #

    @retry(max_attempts=2, base_delay=3.0, logger_name="analytics")
    def get_page_insights(self, period: str = "day", days: int = 30) -> dict:
        """
        Obtiene métricas agregadas de la página de Facebook.

        Args:
            period: 'day', 'week', 'days_28'
            days: Días hacia atrás para consultar

        Returns:
            dict con métricas clave
        """
        since = int((datetime.now() - timedelta(days=days)).timestamp())
        until = int(datetime.now().timestamp())

        metrics = [
            "page_impressions_unique",
            "page_posts_impressions",
            "page_post_engagements",
            "page_actions_post_reactions_total",
            "page_views_total",
            "page_daily_follows",
        ]

        r = requests.get(
            f"{GRAPH_API_BASE}/{self.page_id}/insights",
            params={
                "metric": ",".join(metrics),
                "period": period,
                "since": since,
                "until": until,
                "access_token": self.page_token,
            },
        )
        data = r.json()

        if "error" in data:
            logger.error("Error en page insights: %s", data["error"].get("message", ""))
            return {"error": data["error"]}

        result = {}
        for item in data.get("data", []):
            name = item["name"]
            values = item.get("values", [])
            total = sum(v.get("value", 0) for v in values if isinstance(v.get("value"), (int, float)))
            result[name] = {
                "total": total,
                "promedio_diario": round(total / max(len(values), 1), 1),
                "puntos": len(values),
            }

        return result

    # ------------------------------------------------------------------ #
    #  FACEBOOK — Métricas por post
    # ------------------------------------------------------------------ #

    @retry(max_attempts=2, base_delay=3.0, logger_name="analytics")
    def get_posts_metrics(self, limit: int = 25) -> list[dict]:
        """
        Obtiene métricas individuales de los últimos N posts de la página.

        Returns:
            Lista de dicts con info de cada post + métricas
        """
        r = requests.get(
            f"{GRAPH_API_BASE}/{self.page_id}/posts",
            params={
                "fields": (
                    "id,message,created_time,full_picture,"
                    "shares,insights.metric(post_impressions_unique,"
                    "post_clicks,post_reactions_by_type_total)"
                ),
                "limit": limit,
                "access_token": self.page_token,
            },
        )
        data = r.json()

        if "error" in data:
            logger.error("Error en posts metrics: %s", data["error"].get("message", ""))
            return []

        posts = []
        for post in data.get("data", []):
            metrics = {}
            for insight in post.get("insights", {}).get("data", []):
                name = insight["name"]
                values = insight.get("values", [{}])
                metrics[name] = values[0].get("value", 0)

            shares = post.get("shares", {}).get("count", 0)
            reactions = metrics.get("post_reactions_by_type_total", {})
            total_reactions = sum(reactions.values()) if isinstance(reactions, dict) else 0

            impressions = metrics.get("post_impressions_unique", 1)
            clicks = metrics.get("post_clicks", 0)

            engagement_rate = round(((total_reactions + clicks + shares) / max(impressions, 1)) * 100, 2)

            posts.append({
                "id": post["id"],
                "message": (post.get("message", "")[:100] + "...") if post.get("message") else "",
                "created_time": post.get("created_time", ""),
                "impressions": impressions,
                "clicks": clicks,
                "shares": shares,
                "reactions": total_reactions,
                "engagement_rate": engagement_rate,
                "has_image": bool(post.get("full_picture")),
            })

        return sorted(posts, key=lambda x: x["engagement_rate"], reverse=True)

    # ------------------------------------------------------------------ #
    #  INSTAGRAM — Insights de cuenta
    # ------------------------------------------------------------------ #

    @retry(max_attempts=2, base_delay=3.0, logger_name="analytics")
    def get_ig_insights(self, days: int = 30) -> dict:
        """Obtiene métricas de la cuenta de Instagram."""
        if not self.ig_id:
            return {"error": "META_INSTAGRAM_ID no configurado"}

        # Métricas de la cuenta
        r = requests.get(
            f"{GRAPH_API_BASE}/{self.ig_id}",
            params={
                "fields": "followers_count,follows_count,media_count,name,username",
                "access_token": self.page_token,
            },
        )
        account = r.json()

        if "error" in account:
            logger.error("Error en IG insights: %s", account["error"].get("message", ""))
            return {"error": account["error"]}

        return {
            "username": account.get("username", ""),
            "followers": account.get("followers_count", 0),
            "following": account.get("follows_count", 0),
            "media_count": account.get("media_count", 0),
        }

    # ------------------------------------------------------------------ #
    #  INSTAGRAM — Métricas por post
    # ------------------------------------------------------------------ #

    @retry(max_attempts=2, base_delay=3.0, logger_name="analytics")
    def get_ig_posts_metrics(self, limit: int = 25) -> list[dict]:
        """Obtiene métricas de los últimos N posts de Instagram."""
        if not self.ig_id:
            return []

        r = requests.get(
            f"{GRAPH_API_BASE}/{self.ig_id}/media",
            params={
                "fields": (
                    "id,caption,timestamp,media_type,like_count,"
                    "comments_count,media_url,permalink"
                ),
                "limit": limit,
                "access_token": self.page_token,
            },
        )
        data = r.json()

        if "error" in data:
            logger.error("Error en IG posts: %s", data["error"].get("message", ""))
            return []

        posts = []
        for post in data.get("data", []):
            likes = post.get("like_count", 0)
            comments = post.get("comments_count", 0)
            engagement = likes + comments

            posts.append({
                "id": post["id"],
                "caption": (post.get("caption", "")[:100] + "...") if post.get("caption") else "",
                "timestamp": post.get("timestamp", ""),
                "media_type": post.get("media_type", ""),
                "likes": likes,
                "comments": comments,
                "engagement": engagement,
                "permalink": post.get("permalink", ""),
            })

        return sorted(posts, key=lambda x: x["engagement"], reverse=True)

    # ------------------------------------------------------------------ #
    #  BEST TIME TO POST — Análisis de horarios óptimos
    # ------------------------------------------------------------------ #

    def analyze_best_times(self) -> dict:
        """
        Analiza los posts existentes para determinar las mejores horas de publicación.

        Returns:
            dict con mejores horas por día de la semana
        """
        fb_posts = self.get_posts_metrics(limit=50)
        ig_posts = self.get_ig_posts_metrics(limit=50)

        by_hour = defaultdict(list)
        by_day = defaultdict(list)

        for post in fb_posts:
            try:
                dt = datetime.fromisoformat(post["created_time"].replace("Z", "+00:00"))
                # Convertir a hora Colombia (UTC-5)
                hour = (dt.hour - 5) % 24
                day = dt.strftime("%A").lower()
                by_hour[hour].append(post["engagement_rate"])
                by_day[day].append(post["engagement_rate"])
            except (ValueError, KeyError):
                continue

        for post in ig_posts:
            try:
                dt = datetime.fromisoformat(post["timestamp"].replace("Z", "+00:00"))
                hour = (dt.hour - 5) % 24
                day = dt.strftime("%A").lower()
                by_hour[hour].append(post["engagement"])
                by_day[day].append(post["engagement"])
            except (ValueError, KeyError):
                continue

        best_hours = {
            h: round(sum(rates) / len(rates), 2)
            for h, rates in sorted(by_hour.items())
            if rates
        }

        best_days = {
            d: round(sum(rates) / len(rates), 2)
            for d, rates in sorted(by_day.items())
            if rates
        }

        top_3_hours = sorted(best_hours.items(), key=lambda x: x[1], reverse=True)[:3]

        return {
            "by_hour": best_hours,
            "by_day": best_days,
            "top_3_hours": [{"hour": f"{h:02d}:00", "avg_engagement": v} for h, v in top_3_hours],
            "data_points": len(fb_posts) + len(ig_posts),
        }

    # ------------------------------------------------------------------ #
    #  REPORTE COMPLETO — Genera Markdown
    # ------------------------------------------------------------------ #

    def generar_reporte(self, output_path: str = None) -> str:
        """
        Genera un reporte completo de métricas en formato Markdown.

        Returns:
            Path del archivo generado
        """
        logger.info("Generando reporte de analytics...")
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        fecha_legible = datetime.now().strftime("%d %b %Y %H:%M")

        if not output_path:
            output_path = os.path.join(str(OUTPUT_DIR), f"reporte_analytics_{timestamp}.md")

        lines = [
            f"# 📊 Reporte de Analytics — Humanizar Systems",
            f"",
            f"> Generado: {fecha_legible}",
            f"",
        ]

        # Sección Facebook
        lines.append("## 📘 Facebook Page")
        lines.append("")

        page_data = self.get_page_insights(days=30)
        if "error" not in page_data:
            lines.append("### Últimos 30 días")
            lines.append("")
            lines.append("| Métrica | Total | Promedio/día |")
            lines.append("|---------|-------|-------------|")
            metric_names = {
                "page_impressions_unique": "Alcance (personas únicas)",
                "page_posts_impressions": "Impresiones de posts",
                "page_post_engagements": "Interacciones",
                "page_actions_post_reactions_total": "Reacciones totales",
                "page_views_total": "Visitas a la página",
                "page_daily_follows": "Nuevos seguidores",
            }
            for key, label in metric_names.items():
                data = page_data.get(key, {})
                lines.append(f"| {label} | {data.get('total', 0):,} | {data.get('promedio_diario', 0)} |")
            lines.append("")
        else:
            lines.append(f"⚠️ Error: {page_data.get('error', '')}")
            lines.append("")

        # Top posts FB
        lines.append("### Top Posts (por engagement rate)")
        lines.append("")
        fb_posts = self.get_posts_metrics(limit=10)
        if fb_posts:
            lines.append("| # | Engagement% | Impressions | Clicks | Reactions | Post |")
            lines.append("|---|-----------|-------------|--------|-----------|------|")
            for i, p in enumerate(fb_posts[:10], 1):
                msg = p["message"][:50] if p["message"] else "(sin texto)"
                lines.append(
                    f"| {i} | {p['engagement_rate']}% | {p['impressions']:,} | "
                    f"{p['clicks']} | {p['reactions']} | {msg} |"
                )
            lines.append("")

        # Sección Instagram
        lines.append("## 📸 Instagram")
        lines.append("")

        ig_account = self.get_ig_insights()
        if "error" not in ig_account:
            lines.append(f"- **Username:** @{ig_account.get('username', 'N/A')}")
            lines.append(f"- **Seguidores:** {ig_account.get('followers', 0)}")
            lines.append(f"- **Seguidos:** {ig_account.get('following', 0)}")
            lines.append(f"- **Publicaciones:** {ig_account.get('media_count', 0)}")
            lines.append("")

        ig_posts = self.get_ig_posts_metrics(limit=10)
        if ig_posts:
            lines.append("### Top Posts IG (por engagement)")
            lines.append("")
            lines.append("| # | Likes | Comments | Caption |")
            lines.append("|---|-------|----------|---------|")
            for i, p in enumerate(ig_posts[:10], 1):
                caption = p["caption"][:50] if p["caption"] else "(sin caption)"
                lines.append(f"| {i} | {p['likes']} | {p['comments']} | {caption} |")
            lines.append("")

        # Best time to post
        lines.append("## ⏰ Mejores horarios para publicar")
        lines.append("")
        best_times = self.analyze_best_times()
        if best_times["data_points"] > 0:
            lines.append(f"Basado en {best_times['data_points']} publicaciones analizadas:")
            lines.append("")
            if best_times["top_3_hours"]:
                lines.append("| Hora (COL) | Engagement promedio |")
                lines.append("|-----------|-------------------|")
                for t in best_times["top_3_hours"]:
                    lines.append(f"| {t['hour']} | {t['avg_engagement']} |")
                lines.append("")
        else:
            lines.append("⚠️ No hay suficientes datos para analizar horarios.")
            lines.append("")

        # Guardar
        content = "\n".join(lines)
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(content)

        logger.info("Reporte guardado en: %s", output_path)
        return output_path


# ------------------------------------------------------------------ #
#  CLI
# ------------------------------------------------------------------ #

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Analytics de redes sociales — Humanizar Systems"
    )
    parser.add_argument("--resumen", action="store_true", help="Resumen de últimos 30 días")
    parser.add_argument("--posts", action="store_true", help="Métricas por post (FB + IG)")
    parser.add_argument("--best-time", action="store_true", help="Mejores horarios para publicar")
    parser.add_argument("--reporte", action="store_true", help="Genera reporte completo MD")
    parser.add_argument("--dias", type=int, default=30, help="Días hacia atrás (default: 30)")

    args = parser.parse_args()
    analytics = SocialAnalytics()

    if args.resumen:
        print("\n📊 RESUMEN DE PÁGINA (últimos %d días)" % args.dias)
        print("=" * 50)
        data = analytics.get_page_insights(days=args.dias)
        for key, val in data.items():
            print(f"  {key}: {val}")

        print("\n📸 INSTAGRAM")
        ig = analytics.get_ig_insights()
        for key, val in ig.items():
            print(f"  {key}: {val}")

    elif args.posts:
        print("\n📘 TOP POSTS FACEBOOK")
        print("=" * 50)
        for p in analytics.get_posts_metrics(limit=10):
            print(f"  {p['engagement_rate']}% eng | {p['impressions']} imp | {p['message']}")

        print("\n📸 TOP POSTS INSTAGRAM")
        print("=" * 50)
        for p in analytics.get_ig_posts_metrics(limit=10):
            print(f"  ❤️ {p['likes']} 💬 {p['comments']} | {p['caption']}")

    elif args.best_time:
        print("\n⏰ MEJORES HORARIOS PARA PUBLICAR")
        print("=" * 50)
        data = analytics.analyze_best_times()
        print(f"  Data points: {data['data_points']}")
        for t in data.get("top_3_hours", []):
            print(f"  🕐 {t['hour']} — engagement promedio: {t['avg_engagement']}")

    elif args.reporte:
        path = analytics.generar_reporte()
        print(f"✅ Reporte generado: {path}")

    else:
        parser.print_help()
