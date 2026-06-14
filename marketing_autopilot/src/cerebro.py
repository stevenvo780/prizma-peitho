import os
from pathlib import Path
import google.generativeai as genai
from dotenv import load_dotenv

# Cargar configuración
load_dotenv()
genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))

class MarketingCerebro:
    def __init__(self):
        self.model = genai.GenerativeModel("gemini-1.5-flash")
        self.narrativa = self._cargar_narrativa()

    def _cargar_narrativa(self):
        narrativa_path = (
            Path(__file__).resolve().parents[4]
            / "HumanizarSystems"
            / "Imagen de marca"
            / "NARRATIVA_MARCA.md"
        )
        try:
            return narrativa_path.read_text(encoding="utf-8")
        except OSError:
            # Fallback minimo para no romper la generacion si el archivo no existe.
            return (
                "Humanizar Systems es un ecosistema de software colombiano para pymes. "
                "No promocionar HubCentral. Usar lenguaje directo, practico y enfocado "
                "en resultados medibles con CTA y URL especifica del producto."
            )

    def generar_campana(self, objetivo, publico_objetivo):
        prompt = f"""
        Actúa como un Director de Marketing experto en Performance y Growth.
        Tu objetivo es crear una campaña publicitaria para Humanizar Systems.

        FUENTE UNICA DE VERDAD (narrativa oficial):
        {self.narrativa}

        REGLAS OBLIGATORIAS:
        - Nunca promociones HubCentral.
        - Nunca hables de Humanizar como si fuera un producto individual.
        - Evita buzzwords vacios.
        - Usa tono directo, practico y confiable.
        - Incluye CTA claro con URL especifica de producto.
        - Contextualiza para pymes en Colombia.

        OBJETIVO DE LA CAMPAÑA: {objetivo}
        PÚBLICO OBJETIVO: {publico_objetivo}
        
        GENERA:
        1. ESTRATEGIA: Un nombre de campaña y el ángulo psicológico (ej: urgencia, ahorro de tiempo, crecimiento).
        2. COPIES (Texto):
           - Un copy corto para Instagram (enfocado en visual y emojis).
           - Un copy persuasivo para Facebook (formato largo con beneficios).
        3. PROMPT PARA IMAGEN: Una descripción detallada para una IA generadora de imágenes (como Imagen 3 o DALL-E) que represente la propuesta de valor sin usar texto dentro de la imagen.

        Responde en formato JSON puro para ser procesado por el sistema.
        """

        response = self.model.generate_content(
            prompt,
            generation_config={"response_mime_type": "application/json"}
        )
        return response.text

if __name__ == "__main__":
    cerebro = MarketingCerebro()
    # Prueba rápida
    resultado = cerebro.generar_campana(
        "Vender suscripciones de EMW para automatizar ventas por WhatsApp",
        "Dueños de tiendas de e-commerce en Colombia que están colapsados de chats"
    )
    print(resultado)
