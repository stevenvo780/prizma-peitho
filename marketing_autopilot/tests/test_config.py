"""
test_config.py — Tests para config.py (fundamento del sistema).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from config import (
    PRODUCTOS, VISUAL_GUIDELINES, PAIN_POINTS,
    GRAPH_API_BASE, GRAPH_API_VERSION,
    QUALITY_THRESHOLD, MAX_IG_CONTAINER_RETRIES,
    get_logger, build_utm_url, generar_caption_ig,
    PROJECT_ROOT, SRC_DIR, OUTPUT_DIR,
)


class TestProductos:
    """Verifica integridad del catálogo de productos."""

    def test_ocho_productos(self):
        assert len(PRODUCTOS) == 8

    def test_keys_esperadas(self):
        expected = {"prizma", "emw", "graf", "talaria", "sinergia", "agora", "terminal", "fiar"}
        assert set(PRODUCTOS.keys()) == expected

    def test_cada_producto_tiene_campos_requeridos(self):
        campos = ["nombre", "tipo", "descripcion", "slogan", "color_primario", "url", "logos"]
        for key, prod in PRODUCTOS.items():
            for campo in campos:
                assert campo in prod, f"Producto '{key}' falta campo '{campo}'"

    def test_urls_son_https(self):
        for key, prod in PRODUCTOS.items():
            assert prod["url"].startswith("https://"), f"URL de '{key}' no es HTTPS: {prod['url']}"

    def test_prizma_es_marca_no_producto(self):
        assert PRODUCTOS["prizma"]["tipo"] == "marca"

    def test_productos_tienen_tipo_producto(self):
        for key in ["emw", "graf", "talaria", "sinergia", "agora", "terminal", "fiar"]:
            assert PRODUCTOS[key]["tipo"] == "producto", f"'{key}' debería ser tipo 'producto'"

    def test_emw_no_es_erp(self):
        """EMW es WhatsApp marketing, NO ERP."""
        desc = PRODUCTOS["emw"]["descripcion"].lower()
        assert "whatsapp" in desc
        assert "erp" not in desc
        assert "nómina" not in desc

    def test_graf_no_es_bi(self):
        """Graf es catálogo/carrito, NO BI/dashboards."""
        desc = PRODUCTOS["graf"]["descripcion"].lower()
        assert "catálogo" in desc or "carrito" in desc
        assert "dashboard" not in desc
        assert "business intelligence" not in desc


class TestPainPoints:
    def test_tiene_7_productos(self):
        assert len(PAIN_POINTS) == 7  # No prizma (es marca)

    def test_todos_los_productos_activos(self):
        for key in ["emw", "graf", "talaria", "sinergia", "agora", "terminal", "fiar"]:
            assert key in PAIN_POINTS


class TestGraphAPI:
    def test_version(self):
        assert GRAPH_API_VERSION == "v24.0"

    def test_base_url(self):
        assert GRAPH_API_BASE == "https://graph.facebook.com/v24.0"


class TestLogger:
    def test_crea_logger_con_nombre(self):
        log = get_logger("test_logger_unit")
        assert log.name == "test_logger_unit"

    def test_mismo_logger_misma_instancia(self):
        log1 = get_logger("test_same")
        log2 = get_logger("test_same")
        assert log1 is log2


class TestBuildUtmUrl:
    def test_url_basica(self):
        url = build_utm_url("https://emw.prizma.cloud")
        assert "utm_source=social" in url
        assert "utm_medium=organic" in url

    def test_url_con_campana(self):
        url = build_utm_url("https://graf.com.co", campaign="lanzamiento")
        assert "utm_campaign=lanzamiento" in url

    def test_url_con_content(self):
        url = build_utm_url("https://graf.com.co", content="post_fb")
        assert "utm_content=post_fb" in url


class TestGenerarCaptionIg:
    def test_prizma_caption(self):
        caption = generar_caption_ig("prizma")
        assert "ecosistema" in caption.lower() or "prizma" in caption.lower() or "humanizar" in caption.lower()
        assert "prizma.cloud" in caption  # domain kept until R4

    def test_emw_caption_correcto(self):
        caption = generar_caption_ig("emw")
        assert "whatsapp" in caption.lower()
        assert "iris.prizma.cloud" in caption
        # No debe decir ERP
        assert "erp" not in caption.lower().replace("enterprice", "")

    def test_graf_caption_correcto(self):
        caption = generar_caption_ig("graf")
        assert "catálogo" in caption.lower() or "carrito" in caption.lower() or "pedidos" in caption.lower()
        assert "graf.com.co" in caption

    def test_producto_inexistente(self):
        caption = generar_caption_ig("inexistente_xyz")
        assert caption == ""

    def test_todos_los_productos_generan_caption(self):
        for key in PRODUCTOS:
            caption = generar_caption_ig(key)
            assert len(caption) > 50, f"Caption de '{key}' es muy corto: {len(caption)} chars"


class TestPaths:
    def test_project_root_existe(self):
        assert PROJECT_ROOT.exists()

    def test_src_dir_existe(self):
        assert SRC_DIR.exists()

    def test_output_dir_existe(self):
        assert OUTPUT_DIR.exists()


class TestConstants:
    def test_quality_threshold_razonable(self):
        assert 0 < QUALITY_THRESHOLD <= 100

    def test_max_retries_razonable(self):
        assert 1 <= MAX_IG_CONTAINER_RETRIES <= 30
