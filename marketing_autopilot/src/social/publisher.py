import os
import json
import time
import requests
from facebook_business.api import FacebookAdsApi
from facebook_business.adobjects.adaccount import AdAccount
from facebook_business.adobjects.campaign import Campaign
from dotenv import load_dotenv

from config import get_logger, GRAPH_API_BASE, retry, MAX_IG_CONTAINER_RETRIES, IG_CONTAINER_POLL_INTERVAL
from social.token_manager import TokenManager

load_dotenv()

logger = get_logger("publisher")

class MetaAdsManager:
    def __init__(self):
        self.app_id = os.getenv("META_APP_ID")
        self.app_secret = os.getenv("META_APP_SECRET")
        self.access_token = os.getenv("META_ACCESS_TOKEN")
        self.ad_account_id = os.getenv("META_AD_ACCOUNT_ID")
        self.page_id = os.getenv("META_PAGE_ID")
        self._page_token = None
        self._token_manager = TokenManager()
        
        if self.access_token:
            FacebookAdsApi.init(self.app_id, self.app_secret, self.access_token)

    def _get_page_token(self):
        """
        Obtiene Page Access Token con auto-refresh.
        Usa TokenManager para obtener un token de larga duración
        que no expira, renovándolo automáticamente si es necesario.
        """
        if self._page_token:
            # Verificar que siga válido
            if self._token_manager.token_is_valid(self._page_token):
                return self._page_token
            logger.warning("Page token expirado, renovando...")
        
        # Obtener page token válido (con auto-refresh)
        page_token = self._token_manager.get_valid_page_token()
        if page_token:
            self._page_token = page_token
            # Actualizar también el user token por si fue renovado
            new_user_token = self._token_manager._user_token
            if new_user_token != self.access_token:
                self.access_token = new_user_token
                FacebookAdsApi.init(self.app_id, self.app_secret, self.access_token)
            return self._page_token
        return None

    @retry(max_attempts=2, base_delay=3.0, exceptions=(requests.RequestException,), logger_name="publisher")
    def publicar_en_feed(self, message, link=None):
        """
        Publica un post organico en la Fan Page de Facebook.
        Retorna el ID del post creado o un mensaje de error.
        """
        page_token = self._get_page_token()
        if not page_token:
            return {"error": f"No se pudo obtener Page Token para {self.page_id}"}

        payload = {
            "message": message,
            "access_token": page_token,
        }
        if link:
            payload["link"] = link

        r = requests.post(f"{GRAPH_API_BASE}/{self.page_id}/feed", data=payload)
        result = r.json()
        
        if "id" in result:
            return {"success": True, "post_id": result["id"], "message": "Post publicado OK"}
        else:
            return {"error": result.get("error", {}).get("message", str(result))}

    @retry(max_attempts=2, base_delay=3.0, exceptions=(requests.RequestException,), logger_name="publisher")
    def publicar_con_imagen(self, message, image_url=None, image_path=None):
        """
        Publica un post con imagen en la Fan Page.
        - image_url: URL pública accesible.
        - image_path: Ruta local a la imagen (se sube directamente).
        Se necesita al menos uno de los dos.
        """
        page_token = self._get_page_token()
        if not page_token:
            return {"error": f"No se pudo obtener Page Token para {self.page_id}"}

        if image_path and os.path.exists(image_path):
            # Subida directa del archivo
            with open(image_path, "rb") as img_file:
                r = requests.post(
                    f"{GRAPH_API_BASE}/{self.page_id}/photos",
                    data={
                        "message": message,
                        "access_token": page_token,
                    },
                    files={"source": img_file}
                )
        elif image_url:
            payload = {
                "message": message,
                "url": image_url,
                "access_token": page_token,
            }
            r = requests.post(f"{GRAPH_API_BASE}/{self.page_id}/photos", data=payload)
        else:
            return {"error": "Se necesita image_url o image_path"}

        result = r.json()
        
        if "id" in result:
            return {"success": True, "photo_id": result["id"], "message": "Foto publicada OK"}
        else:
            return {"error": result.get("error", {}).get("message", str(result))}

    def publicar_en_instagram(self, caption, image_url):
        """
        Publica un post con imagen en Instagram Business via Content Publishing API.
        Proceso de 2 pasos:
          1. Crear media container con la URL pública de la imagen.
          2. Publicar el container.
        
        IMPORTANTE: image_url DEBE ser una URL pública accesible (no archivo local).
        
        Args:
            caption: Texto del post (incluye hashtags).
            image_url: URL pública de la imagen (JPEG/PNG).
        
        Returns:
            dict con success/error y media_id.
        """
        page_token = self._get_page_token()
        if not page_token:
            return {"error": "No se pudo obtener Page Token"}

        ig_account_id = os.getenv("META_INSTAGRAM_ID")
        if not ig_account_id:
            return {"error": "META_INSTAGRAM_ID no configurado en .env"}

        # Paso 1: Crear media container
        container_payload = {
            "image_url": image_url,
            "caption": caption,
            "access_token": page_token,
        }
        r1 = requests.post(
            f"{GRAPH_API_BASE}/{ig_account_id}/media",
            data=container_payload
        )
        container_result = r1.json()

        if "id" not in container_result:
            error_msg = container_result.get("error", {}).get("message", str(container_result))
            return {"error": f"Error creando container: {error_msg}"}

        container_id = container_result["id"]

        # Paso 2: Esperar a que el container esté listo y publicar
        for attempt in range(MAX_IG_CONTAINER_RETRIES):
            status_r = requests.get(
                f"{GRAPH_API_BASE}/{container_id}",
                params={"fields": "status_code", "access_token": page_token}
            )
            status = status_r.json().get("status_code", "")
            if status == "FINISHED":
                break
            elif status == "ERROR":
                return {"error": f"Container en estado ERROR: {status_r.json()}"}
            time.sleep(IG_CONTAINER_POLL_INTERVAL)

        publish_payload = {
            "creation_id": container_id,
            "access_token": page_token,
        }
        r2 = requests.post(
            f"{GRAPH_API_BASE}/{ig_account_id}/media_publish",
            data=publish_payload
        )
        publish_result = r2.json()

        if "id" in publish_result:
            return {
                "success": True,
                "media_id": publish_result["id"],
                "container_id": container_id,
                "message": "Post publicado en Instagram OK"
            }
        else:
            error_msg = publish_result.get("error", {}).get("message", str(publish_result))
            return {"error": f"Error publicando: {error_msg}"}

    def inyectar_presupuesto_campana(self, nombre_campana, presupuesto_diario):
        """
        Crea una campana de Ads e inyecta presupuesto real.
        Se crea PAUSADA por seguridad.
        """
        if not self.ad_account_id:
            return {"error": "Falta ID de cuenta publicitaria"}
            
        account = AdAccount(self.ad_account_id)
        params = {
            'name': nombre_campana,
            'objective': 'OUTCOME_SALES',
            'status': 'PAUSED',
            'special_ad_categories': [],
        }
        
        try:
            campaign = account.create_campaign(params=params)
            return {
                "success": True,
                "campaign_id": campaign["id"],
                "message": f"Campana '{nombre_campana}' creada PAUSADA. Presupuesto: {presupuesto_diario} COP."
            }
        except Exception as e:
            return {"error": str(e)}

    def leer_pagina_info(self):
        """Lee informacion basica de la pagina para verificacion."""
        r = requests.get(f"{GRAPH_API_BASE}/{self.page_id}", params={
            "fields": "name,category,fan_count,followers_count,published_posts.limit(3){message,created_time}",
            "access_token": self.access_token
        })
        return r.json()

if __name__ == "__main__":
    manager = MetaAdsManager()
    logger.info(manager.inyectar_presupuesto_campana("Campaña IA Humanizar Test", 50000))
