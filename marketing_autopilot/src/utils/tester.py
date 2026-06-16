import argparse
import json
import os
import sys
import requests
from dotenv import load_dotenv

from config import get_logger, GRAPH_API_BASE
from core.cerebro import MarketingCerebro
from social.publisher import MetaAdsManager

load_dotenv()

logger = get_logger("tester")

def test_brain():
    print("\n🧠 [TEST: CEREBRO] Generando estrategia con Gemini...")
    cerebro = MarketingCerebro()
    try:
        resultado = cerebro.generar_campana(
            "Vender Graf a duenos de restaurantes", 
            "Emprendedores gastronomicos en Bogota"
        )
        data = json.loads(resultado)
        # Gemini a veces devuelve un array con un solo elemento
        if isinstance(data, list):
            data = data[0]
        print("✅ Conexion Exitosa con Gemini.")
        print(f"   Estrategia: {data.get('ESTRATEGIA', 'N/A')}")
        print(f"   Copy IG: {data['COPIES']['Instagram'][:100]}...")
        return data
    except Exception as e:
        print(f"❌ Error en el Cerebro: {e}")
        return None

def test_meta_auth():
    print("\n🔐 [TEST: META AUTH] Verificando tokens y permisos...")
    token = os.getenv("META_ACCESS_TOKEN")
    account_id = os.getenv("META_AD_ACCOUNT_ID")
    page_id = os.getenv("META_PAGE_ID")
    
    if not token or not account_id:
        print("❌ Faltan credenciales en el archivo .env")
        return False

    # 1. Verificar token y usuario
    print("  1/4 Verificando token de usuario...")
    r = requests.get(f"{GRAPH_API_BASE}/me", params={"access_token": token})
    if r.status_code == 200:
        user = r.json()
        print(f"  ✅ Token valido. Usuario: {user.get('name', 'N/A')} (ID: {user.get('id')})")
    else:
        print(f"  ❌ Token invalido: {r.json().get('error', {}).get('message', r.text)}")
        return False

    # 2. Verificar cuenta publicitaria
    print(f"  2/4 Verificando Ad Account {account_id}...")
    r = requests.get(f"{GRAPH_API_BASE}/{account_id}", params={
        "fields": "name,account_status,currency,balance,amount_spent",
        "access_token": token
    })
    if r.status_code == 200:
        acc = r.json()
        status_map = {1: "ACTIVE", 2: "DISABLED", 3: "UNSETTLED", 7: "PENDING_RISK_REVIEW"}
        acc_status = status_map.get(acc.get("account_status"), "UNKNOWN")
        print(f"  ✅ Ad Account OK. Status: {acc_status}, Currency: {acc.get('currency')}")
        print(f"     Gastado total: {acc.get('amount_spent', '0')} centavos")
    else:
        print(f"  ❌ Error Ad Account: {r.json().get('error', {}).get('message', r.text)}")

    # 3. Verificar pagina
    print(f"  3/4 Verificando Page {page_id}...")
    r = requests.get(f"{GRAPH_API_BASE}/{page_id}", params={
        "fields": "name,category,fan_count,followers_count",
        "access_token": token
    })
    if r.status_code == 200:
        page = r.json()
        print(f"  ✅ Pagina OK: {page.get('name')} ({page.get('category')})")
        print(f"     Fans: {page.get('fan_count', 0)} | Followers: {page.get('followers_count', 0)}")
    else:
        print(f"  ❌ Error Page: {r.json().get('error', {}).get('message', r.text)}")

    # 4. Obtener Page Access Token
    print("  4/4 Obteniendo Page Access Token...")
    r = requests.get(f"{GRAPH_API_BASE}/me/accounts", params={
        "access_token": token
    })
    if r.status_code == 200:
        pages = r.json().get("data", [])
        page_token = None
        for p in pages:
            if p["id"] == page_id:
                page_token = p["access_token"]
                break
        if page_token:
            print(f"  ✅ Page Token obtenido para {page_id} ({len(page_token)} chars)")
        else:
            print(f"  ⚠️  Page Token no encontrado para ID {page_id}. Paginas disponibles:")
            for p in pages:
                print(f"     - {p['name']} (ID: {p['id']})")
    else:
        print(f"  ❌ Error obteniendo paginas: {r.json().get('error', {}).get('message', r.text)}")

    return True

def run_simulation():
    print("\n🚀 [SIMULACION COMPLETA] Ejecutando flujo sin inyeccion de dinero...")
    
    # Paso 1: Generar estrategia
    estrategia = test_brain()
    if not estrategia:
        print("❌ Abortado: no se pudo generar estrategia.")
        return
    
    # Paso 2: Verificar auth
    auth_ok = test_meta_auth()
    if not auth_ok:
        print("❌ Abortado: fallo de autenticacion.")
        return
    
    # Paso 3: Simular publicacion
    print(f"\n👉 PASO FINAL: Se publicaria en la pagina:")
    print(f"   Campana: '{estrategia.get('ESTRATEGIA', 'N/A')}'")
    print(f"   Copy FB: {estrategia['COPIES']['Facebook'][:120]}...")
    print(f"   Hashtags: {' '.join(estrategia.get('HASHTAGS', []))}")
    print(f"   Presupuesto: $20.000 COP/dia")
    print("🛑 [DRY RUN] Operacion detenida antes de la publicacion/inyeccion real.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Prizma Ads Tester")
    parser.add_argument("--test-brain", action="store_true", help="Probar generación de IA")
    parser.add_argument("--test-meta-auth", action="store_true", help="Probar conexión con Meta")
    parser.add_argument("--dry-run", action="store_true", help="Simular flujo completo sin gasto")
    
    args = parser.parse_args()

    if len(sys.argv) == 1:
        parser.print_help()
    else:
        if args.test_brain: test_brain()
        if args.test_meta_auth: test_meta_auth()
        if args.dry_run: run_simulation()
