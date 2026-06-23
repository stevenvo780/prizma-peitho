"""
cerebro.py — Cerebro de marketing IA para Prizma (ex Steven Vallejo).

Usa Gemini como motor de generación de estrategias de marketing.
Carga la narrativa de marca como contexto del sistema para garantizar
consistencia en voz, tono, producto y mensaje.
"""

import os
import json
from pathlib import Path
from google import genai
from dotenv import load_dotenv

from config import get_logger, DEFAULT_COPY_MODEL

# Cargar configuracion
load_dotenv()

logger = get_logger("cerebro")
client = genai.Client(api_key=os.getenv("GOOGLE_API_KEY"))

# ------------------------------------------------------------------ #
#  NARRATIVA DE MARCA — System Context
# ------------------------------------------------------------------ #

# Intentar cargar NARRATIVA_MARCA.md como contexto
_NARRATIVA_PATH = Path(__file__).resolve().parent.parent.parent.parent / "HumanizarDocs" / "Imagen de marca" / "NARRATIVA_MARCA.md"  # external repo path — keep as-is until R4
_NARRATIVA_COMPLETA = ""
if _NARRATIVA_PATH.exists():
    _NARRATIVA_COMPLETA = _NARRATIVA_PATH.read_text(encoding="utf-8")
else:
    logger.warning(f"NARRATIVA_MARCA.md no encontrada en {_NARRATIVA_PATH}. Usando fallback condensado.")

# Contexto condensado (siempre disponible como fallback)
BRAND_CONTEXT = """
=== IDENTIDAD DE MARCA — PRIZMA ===

QUIÉN SOMOS:
Prizma es un ecosistema de software colombiano que conecta ventas, operación
y automatización en una sola suite empresarial para pymes en crecimiento.
- Prizma = Marca paraguas (NO es un producto individual).
- 60 clientes consolidados, 3 años de operación, etapa scale-up temprano.
- País foco: Colombia. ICP: Retail/tiendas, food/dark kitchens, servicios/educación.

PRODUCTOS (cada uno con su URL y pricing):
⭐ EMW — Marketing masivo por WhatsApp ($88.000) → iris.prizma.cloud
   Pain: "Tengo miles de contactos pero no sé cómo activarlos sin parecer spam"
   Ángulo: Recupera ventas dormidas con campañas segmentadas.

⭐ Graf — Catálogo y carrito conversacional ($30.000/mes) → graf.com.co
   Pain: "Recibo pedidos por chat pero se pierden, no tengo orden"
   Ángulo: Más pedidos cerrados con catálogo digital en WhatsApp.

🚚 Talaria — Logística de entregas ($49.500/mes) → www.prizma.cloud
   Pain: "No sé dónde están mis domiciliarios ni cuánto tarda cada entrega"
   Ángulo: Entregas rápidas con trazabilidad y asignación automática.

💳 Sinergia POS — Punto de venta ($10/mes) → sinergia-pos.com
   Pain: "No sé cuánto vendí hoy ni qué tengo en inventario"
   Ángulo: Control de caja e inventario en tiempo real.

🏛️ Agora — Workspace colaborativo ($30.000/mes) → agora.prizma.cloud
   Pain: "Mi equipo trabaja en 5 herramientas y nada está conectado"
   Ángulo: Editor, terminal y workspace en un solo lugar.

🖥️ Terminal — Soporte técnico remoto ($10/mes) → terminal.prizma.cloud
   Pain: "Acceder a servidores remotos es un dolor"
   Ángulo: Soporte ágil desde el navegador.

💰 Fiar — Control de créditos (Próximamente) → pistis.prizma.cloud
   Pain: "Fío a clientes pero no tengo trazabilidad de quién debe cuánto"
   Ángulo: Control digital de cartera.

BUNDLES:
- Growth Comercial: EMW + Graf → "Captura leads + ciérralos con catálogo"
- Operación Unificada: Graf + Sinergia POS + Talaria → "Venta + caja + entrega"
- Escalamiento Digital: Agora + Terminal + Conectores → "Workspace + terminal + automatización"

VOZ Y TONO:
- Directa, práctica, cercana, colombiana, confiable.
- SIN buzzwords: no usar "disruptivo", "360°", "revolucionario", "soluciones integrales".
- SÍ usar: activar, escalar, ordenar, conectar, automatizar, crecer, control, trazabilidad.
- Emojis con moderación (2-4 por post).
- El copy debe leerse en 5 seg (gancho) + 15 seg (detalle).

PILARES NARRATIVOS:
1. Conexión, no fragmentación → "Un ecosistema que fluye, no 8 herramientas sueltas"
2. Resultados concretos → "60 clientes, 3 años. Software que funciona."
3. Para tu negocio real → "Hecho para la pyme colombiana que vende por WhatsApp"
4. Empieza simple → "Plan gratis o demo. Sin contratos eternos."
5. Tecnología humana → "Software que entiende cómo trabaja tu equipo"

ESTRUCTURA DE POST IDEAL:
[Gancho emocional — pain point en 1 línea]
[Solución — qué hace el producto en 2 líneas]
[Prueba social o dato: "60 negocios ya lo usan" / "Desde $30.000/mes"]
[CTA con URL directa del producto]
[3-5 hashtags relevantes]

REGLAS ABSOLUTAS:
✅ Usar URL del producto específico, NUNCA prizma.cloud genérico (salvo awareness).
✅ Incluir CTA claro con precio o beneficio.
✅ Mencionar Colombia o contexto pyme.
❌ NUNCA decir "Prizma" como si fuera un producto.
❌ NUNCA promocionar HubCentral (orquestador interno, no es producto de venta).
❌ NUNCA usar lenguaje corporativo vacío.
❌ NUNCA prometer features que no existen.
"""


class MarketingCerebro:
    def __init__(self, usar_narrativa_completa: bool = True):
        self.model = DEFAULT_COPY_MODEL
        # Si la narrativa completa está disponible y se solicita, usarla
        if usar_narrativa_completa and _NARRATIVA_COMPLETA:
            self.brand_context = (
                "=== NARRATIVA DE MARCA COMPLETA ===\n"
                "Lee y aplica TODA esta narrativa para generar contenido consistente:\n\n"
                f"{_NARRATIVA_COMPLETA}\n\n"
                "=== FIN NARRATIVA ===\n"
            )
        else:
            self.brand_context = BRAND_CONTEXT

    def generar_campana(self, objetivo, publico_objetivo):
        prompt = f"""
{self.brand_context}

=== INSTRUCCIONES ===
Actúa como Director de Marketing experto en Performance y Growth para Prizma S.A.S.
Aplica la narrativa de marca, voz/tono y reglas de contenido detalladas arriba.

OBJETIVO DE LA CAMPAÑA: {objetivo}
PÚBLICO OBJETIVO: {publico_objetivo}

GENERA un JSON con esta estructura exacta:
{{
    "ESTRATEGIA": "nombre de campaña creativo - ángulo psicológico del pilar narrativo usado",
    "COPIES": {{
        "Instagram": "copy corto con emojis para IG (max 200 chars). Gancho + CTA directo.",
        "Facebook": "copy largo persuasivo con pain point → solución → prueba social → CTA con URL del producto. Estructura de post ideal."
    }},
    "PROMPT_IMAGEN": "Descripción detallada para IA generadora de imágenes. SIN texto en la imagen. Usar colores de marca del producto específico (indicar hex). Estilo tech-premium, contexto colombiano pyme. No mockups genéricos. No clip-art. Escena de trabajo real o visualización abstracta de datos/conexiones.",
    "HASHTAGS": ["#tag1", "#tag2", "#tag3", "#tag4", "#tag5"],
    "PILAR_NARRATIVO": "Número y nombre del pilar narrativo aplicado",
    "TIPO_CONTENIDO": "pain_point|tip_educativo|testimonio|bundle|producto_secundario|awareness"
}}

Responde SOLO el JSON, sin markdown ni explicaciones.
"""
        
        response = client.models.generate_content(
            model=self.model,
            contents=prompt,
            config={
                "response_mime_type": "application/json",
            }
        )
        logger.info("Campaña generada — objetivo: %s", objetivo[:60])

        # Parse respuesta (strip markdown fences si existen)
        result_text = response.text.strip()
        if result_text.startswith("```"):
            result_text = result_text.split("```")[1]
            if result_text.startswith("json"):
                result_text = result_text[4:]
            result_text = result_text.strip()

        try:
            return json.loads(result_text)
        except json.JSONDecodeError as e:
            logger.error("Error parseando respuesta de Gemini: %s. Raw: %s", str(e), result_text[:200])
            return {"error": f"Respuesta no es JSON válido: {str(e)}"}

    def generar_calendario_semanal(self, productos_foco: list[str] = None):
        """
        Genera un calendario editorial de 7 días con variedad de contenido.
        Retorna lista de 7 objetos con tipo, producto, objetivo y público.
        """
        if not productos_foco:
            productos_foco = ["emw", "graf", "talaria", "sinergia"]

        prompt = f"""
{self.brand_context}

=== INSTRUCCIONES ===
Genera un calendario editorial de 7 días (lunes a domingo) para las redes de Prizma.
Productos en foco esta semana: {', '.join(productos_foco)}

Sigue esta distribución de tipos de contenido:
- Lunes: Pain point + solución (producto estrella)
- Martes: Tip educativo
- Miércoles: Testimonio / caso de éxito
- Jueves: Bundle / cross-sell
- Viernes: Producto secundario
- Sábado: Behind the scenes / equipo
- Domingo: Awareness de marca

Para cada día genera:
{{
    "dia": "lunes",
    "tipo_contenido": "pain_point|tip_educativo|testimonio|bundle|producto_secundario|behind_scenes|awareness",
    "producto": "key del producto (emw, graf, talaria, sinergia, agora, terminal, fiar, prizma=Prizma)",
    "objetivo": "Descripción del objetivo del post",
    "publico": "Público objetivo específico",
    "gancho": "Primera línea del post (gancho emocional)"
}}

Retorna un JSON array de 7 objetos. Solo JSON, sin markdown.
"""
        response = client.models.generate_content(
            model=self.model,
            contents=prompt,
            config={
                "response_mime_type": "application/json",
            }
        )
        logger.info("Calendario semanal generado — productos: %s", productos_foco)
        return response.text

    def evaluar_calidad_post(self, copy: str, producto_key: str) -> dict:
        """
        Evalúa un copy contra las reglas de narrativa de marca.
        Retorna score (0-100) y feedback.
        """
        prompt = f"""
{BRAND_CONTEXT}

=== EVALUACIÓN DE CALIDAD ===
Evalúa el siguiente copy de marketing contra las reglas de narrativa de marca.
Producto: {producto_key}

COPY A EVALUAR:
\"\"\"{copy}\"\"\"

Evalúa en estas dimensiones (0-100 cada una):
1. Consistencia de voz/tono (¿suena a Prizma?)
2. Pain point claro (¿identifica el dolor del cliente?)
3. CTA efectivo (¿tiene URL del producto y acción clara?)
4. Reglas cumplidas (¿respeta las reglas absolutas?)
5. Engagement potencial (¿genera interacción?)

Retorna JSON:
{{
    "score_total": 85,
    "dimensiones": {{
        "voz_tono": 90,
        "pain_point": 80,
        "cta": 85,
        "reglas": 90,
        "engagement": 80
    }},
    "feedback": "Feedback constructivo en 2-3 líneas",
    "mejoras": ["mejora 1", "mejora 2"],
    "aprobado": true
}}

Solo JSON, sin markdown.
"""
        response = client.models.generate_content(
            model=self.model,
            contents=prompt,
            config={
                "response_mime_type": "application/json",
            }
        )
        result = json.loads(response.text)
        logger.info("Calidad evaluada — producto: %s, score: %s", producto_key, result.get("score_total", "?"))
        return result


if __name__ == "__main__":
    cerebro = MarketingCerebro()
    # Prueba rápida
    resultado = cerebro.generar_campana(
        "Vender suscripciones de EMW para automatizar ventas por WhatsApp",
        "Dueños de tiendas de e-commerce en Colombia que están colapsados de chats"
    )
    print(resultado)
