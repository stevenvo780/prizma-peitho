"""
token_manager.py — Gestión automática de tokens Meta (Facebook / Instagram).

Flujo:
  1. Lee el token actual de .env (puede ser short-lived ~1-2 h).
  2. Lo intercambia por un user token long-lived (~60 días).
  3. Con el user-LL obtiene un page token long-lived (NO EXPIRA).
  4. Persiste ambos tokens en .env para próximas ejecuciones.

Uso:
  from token_manager import TokenManager
  tm = TokenManager()
  page_token = tm.get_valid_page_token()
"""

import os
import json
import time
import requests
from datetime import datetime, timezone
from dotenv import load_dotenv, set_key, dotenv_values

from config import get_logger, GRAPH_API_BASE, ENV_PATH as _ENV_PATH

load_dotenv()

GRAPH_API = GRAPH_API_BASE
ENV_PATH = str(_ENV_PATH)

logger = get_logger("token_manager")


class TokenManager:
    def __init__(self):
        self.app_id = os.getenv("META_APP_ID")
        self.app_secret = os.getenv("META_APP_SECRET")
        self.page_id = os.getenv("META_PAGE_ID")
        self._user_token = os.getenv("META_ACCESS_TOKEN")
        self._page_token = os.getenv("META_PAGE_TOKEN", "")
        self._ll_user_token = os.getenv("META_LONG_LIVED_TOKEN", "")

    # ------------------------------------------------------------------ #
    #  DIAGNÓSTICO
    # ------------------------------------------------------------------ #
    def debug_token(self, token: str) -> dict:
        """Inspecciona un token usando la API de Meta."""
        r = requests.get(f"{GRAPH_API}/debug_token", params={
            "input_token": token,
            "access_token": f"{self.app_id}|{self.app_secret}",
        })
        return r.json().get("data", {})

    def token_is_valid(self, token: str) -> bool:
        """Retorna True si el token sigue activo."""
        if not token:
            return False
        info = self.debug_token(token)
        return info.get("is_valid", False)

    def token_expires_soon(self, token: str, margin_seconds: int = 3600) -> bool:
        """True si el token expira dentro de `margin_seconds` o ya expiró."""
        info = self.debug_token(token)
        expires_at = info.get("expires_at", 0)
        if expires_at == 0:
            return False  # token que no expira
        return (expires_at - time.time()) < margin_seconds

    # ------------------------------------------------------------------ #
    #  EXCHANGE: short-lived → long-lived USER token (~60 días)
    # ------------------------------------------------------------------ #
    def exchange_for_long_lived(self, short_token: str = None) -> str:
        """Cambia un user token de corta duración por uno de larga (~60 d)."""
        token = short_token or self._user_token
        r = requests.get(f"{GRAPH_API}/oauth/access_token", params={
            "grant_type": "fb_exchange_token",
            "client_id": self.app_id,
            "client_secret": self.app_secret,
            "fb_exchange_token": token,
        })
        data = r.json()
        if "access_token" in data:
            ll_token = data["access_token"]
            expires_in = data.get("expires_in", "desconocido")
            logger.info("Long-lived USER token obtenido (expira en %ss ≈ %dd)", expires_in, int(expires_in)//86400)
            self._ll_user_token = ll_token
            self._persist_env("META_LONG_LIVED_TOKEN", ll_token)
            self._persist_env("META_ACCESS_TOKEN", ll_token)
            self._user_token = ll_token
            return ll_token
        else:
            error = data.get("error", {}).get("message", str(data))
            logger.error("Error intercambiando token: %s", error)
            return ""

    # ------------------------------------------------------------------ #
    #  PAGE TOKEN de larga duración (NO EXPIRA)
    # ------------------------------------------------------------------ #
    def get_long_lived_page_token(self, user_ll_token: str = None) -> str:
        """
        Obtiene un Page Access Token de larga duración (no expira) 
        usando un user token long-lived.
        """
        token = user_ll_token or self._ll_user_token or self._user_token
        r = requests.get(f"{GRAPH_API}/me/accounts", params={
            "access_token": token,
        })
        data = r.json()
        for page in data.get("data", []):
            if page["id"] == self.page_id:
                page_token = page["access_token"]
                # Verificar si realmente no expira
                info = self.debug_token(page_token)
                expires_at = info.get("expires_at", 0)
                if expires_at == 0:
                    logger.info("Page token obtenido (NO EXPIRA) para '%s'", page.get('name'))
                else:
                    remaining = int(expires_at - time.time())
                    logger.warning("Page token obtenido (expira en %dh) para '%s'", remaining//3600, page.get('name'))
                self._page_token = page_token
                self._persist_env("META_PAGE_TOKEN", page_token)
                return page_token
        
        logger.error("No se encontró la página %s en las cuentas del usuario", self.page_id)
        return ""

    # ------------------------------------------------------------------ #
    #  MÉTODO PRINCIPAL — obtiene page token válido, renovando si es necesario
    # ------------------------------------------------------------------ #
    def get_valid_page_token(self) -> str:
        """
        Método principal: retorna un page token válido.
        Renueva automáticamente si es necesario.
        
        Cascada:
          1. Si hay META_PAGE_TOKEN guardado y es válido → úsalo.
          2. Si hay META_LONG_LIVED_TOKEN → genera page token desde él.
          3. Si solo hay META_ACCESS_TOKEN → intercámbialo primero.
        """
        # 1) Probar page token existente
        if self._page_token and self.token_is_valid(self._page_token):
            if not self.token_expires_soon(self._page_token):
                logger.info("Page token actual sigue válido")
                return self._page_token

        # 2) Probar con long-lived user token
        if self._ll_user_token and self.token_is_valid(self._ll_user_token):
            logger.info("Regenerando page token desde LL user token...")
            pt = self.get_long_lived_page_token(self._ll_user_token)
            if pt:
                return pt

        # 3) Intentar exchange del token actual
        if self._user_token and self.token_is_valid(self._user_token):
            logger.info("Intercambiando user token por long-lived...")
            ll = self.exchange_for_long_lived(self._user_token)
            if ll:
                pt = self.get_long_lived_page_token(ll)
                if pt:
                    return pt

        logger.error("No se pudo obtener un page token válido. Regenera el token desde Graph Explorer.")
        return ""

    # ------------------------------------------------------------------ #
    #  REPORTE DE ESTADO
    # ------------------------------------------------------------------ #
    def status_report(self) -> dict:
        """Diagnóstico completo de todos los tokens guardados."""
        report = {}
        tokens = {
            "META_ACCESS_TOKEN": self._user_token,
            "META_LONG_LIVED_TOKEN": self._ll_user_token,
            "META_PAGE_TOKEN": self._page_token,
        }
        for name, token in tokens.items():
            if not token:
                report[name] = {"status": "NO_CONFIGURADO"}
                continue
            info = self.debug_token(token)
            expires_at = info.get("expires_at", 0)
            scopes = info.get("scopes", [])
            report[name] = {
                "valid": info.get("is_valid", False),
                "type": info.get("type", "desconocido"),
                "expires_at": datetime.fromtimestamp(expires_at, tz=timezone.utc).isoformat() if expires_at else "NUNCA",
                "remaining_hours": round((expires_at - time.time()) / 3600, 1) if expires_at else "∞",
                "scopes": scopes,
            }
        return report

    # ------------------------------------------------------------------ #
    #  UTILIDADES PRIVADAS
    # ------------------------------------------------------------------ #
    def _persist_env(self, key: str, value: str):
        """Guarda o actualiza una variable en el archivo .env."""
        env_path = os.path.abspath(ENV_PATH)
        try:
            set_key(env_path, key, value)
        except Exception:
            # Fallback manual
            lines = []
            found = False
            with open(env_path, "r") as f:
                for line in f:
                    if line.startswith(f"{key}="):
                        lines.append(f"{key}={value}\n")
                        found = True
                    else:
                        lines.append(line)
            if not found:
                lines.append(f"{key}={value}\n")
            with open(env_path, "w") as f:
                f.writelines(lines)


# ------------------------------------------------------------------ #
#  CLI
# ------------------------------------------------------------------ #
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Meta Token Manager — Prizma")
    parser.add_argument("--status", action="store_true", help="Ver estado de todos los tokens")
    parser.add_argument("--refresh", action="store_true", help="Renovar tokens automáticamente")
    parser.add_argument("--exchange", action="store_true", help="Forzar exchange short→long-lived")
    args = parser.parse_args()

    tm = TokenManager()

    if args.status:
        print("📊 Estado de tokens Meta:")
        print("=" * 60)
        report = tm.status_report()
        for name, info in report.items():
            print(f"\n  {name}:")
            for k, v in info.items():
                print(f"    {k}: {v}")

    elif args.refresh:
        print("🔄 Renovando tokens...")
        page_token = tm.get_valid_page_token()
        if page_token:
            print(f"\n✅ Page token listo: {page_token[:30]}...")
        else:
            print("\n❌ Fallo al renovar. Ve a Graph Explorer y regenera el token base.")

    elif args.exchange:
        print("🔄 Forzando exchange...")
        ll = tm.exchange_for_long_lived()
        if ll:
            tm.get_long_lived_page_token(ll)

    else:
        parser.print_help()
