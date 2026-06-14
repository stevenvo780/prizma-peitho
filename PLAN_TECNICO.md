# Sistema de Automatización Publicitaria - Humanizar Ads Automator

## 1. Descripción del Sistema
Este sistema automatizará el ciclo completo de publicidad digital para Humanizar S.A.S., desde la creación creativa hasta la compra de medios.

## 2. Arquitectura de Módulos

### A. CreativeEngine (Motor Creativo)
*   **Función:** Generar textos persuasivos (copy) y diseños visuales (imágenes) alineados con la identidad de marca.
*   **Tecnología:** OpenAI API (GPT-4 para texto, DALL-E 3 para imágenes).

### B. SocialPublisher (Gestor de Publicación Orgánica)
*   **Función:** Publicar el contenido generado en los feeds de redes sociales de la empresa.
*   **Canales:** Instagram Feed, Facebook Page.

### C. AdBidder (Inyección de Pauta y Presupuesto)
*   **Función:** Crear campañas publicitarias pagas (Ads), definir audiencias (targeting) y gestionar la "inyección de dinero" (presupuesto diario/total).
*   **Plataformas:** Meta Ads (Facebook/Instagram Ads).

## 3. Stack Tecnológico Propuesto
*   **Backend:** Python 3.11 + FastAPI (Rápido, tipado y excelente ecosistema para IA/Data).
*   **Cola de Tareas:** Celery + Redis (Para procesos largos de generación de imagen y subida).
*   **Base de Datos:** SQLite (Inicial) -> PostgreSQL (Producción).

## 4. Requerimientos de Credenciales (CRÍTICO)
Para construir y activar este sistema, necesito que configures o me proporciones las siguientes credenciales. El sistema no puede operar sin ellas.

### I. Inteligencia Artificial
1.  **`OPENAI_API_KEY`**: Para generar los anuncios y las imágenes.

### II. Meta (Facebook/Instagram) - Pauta y Publicación
2.  **`META_APP_ID`**: ID de tu App en developers.facebook.com.
3.  **`META_APP_SECRET`**: Secreto de la App.
4.  **`META_ACCESS_TOKEN`**: Token de larga duración.
    *   *Permisos requeridos:* `ads_management`, `ads_read`, `pages_manage_posts`, `instagram_content_publish`, `public_profile`.
5.  **`META_AD_ACCOUNT_ID`**: El ID de la cuenta publicitaria (ej. `act_12345678`) donde se cargará el presupuesto.

### III. Almacenamiento de Assets
6.  **`CLOUDINARY_URL`** (Recomendado) o **AWS S3 Credentials**:
    *   *Razón:* Las APIs de Facebook/Instagram requieren una URL pública (https) de la imagen para poder crear el anuncio o post. No aceptan subida directa de bytes desde local fácilmente en todos los endpoints.

## 5. Próximos Pasos
1.  Inicializar entorno Python.
2.  Instalar dependencias (`fastapi`, `openai`, `facebook_business`, `cloudinary`).
3.  Configurar archivo `.env` con las credenciales.
4.  Desarrollar el script `campaign_runner.py`.
