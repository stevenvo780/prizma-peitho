"""
conftest.py — Fixtures compartidos para los tests del marketing autopilot.
"""

import os
import sys
import json
import pytest
from unittest.mock import MagicMock, patch
from pathlib import Path

# Agregar src/ al path para imports directos
SRC_DIR = Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(SRC_DIR))


@pytest.fixture
def mock_env(monkeypatch):
    """Configura variables de entorno de prueba."""
    env_vars = {
        "META_APP_ID": "test_app_id",
        "META_APP_SECRET": "test_app_secret",
        "META_ACCESS_TOKEN": "test_access_token",
        "META_AD_ACCOUNT_ID": "act_123456",
        "META_PAGE_ID": "1045986888587355",
        "META_INSTAGRAM_ID": "17841446993293838",
        "META_PAGE_TOKEN": "test_page_token",
        "META_LONG_LIVED_TOKEN": "test_ll_token",
        "GOOGLE_API_KEY": "test_google_key",
    }
    for key, val in env_vars.items():
        monkeypatch.setenv(key, val)
    return env_vars


@pytest.fixture
def sample_estrategia():
    """Estrategia de ejemplo que devolvería cerebro.generar_campana()."""
    return {
        "ESTRATEGIA": "WhatsApp Masivo — Dolor de contactos dormidos",
        "COPIES": {
            "Instagram": "¿Miles de contactos en tu celular y 0 ventas? 🚀 Actívalos con EMW.",
            "Facebook": (
                "¿Tienes una base de contactos gigante pero no la usas?\n\n"
                "EMW te permite enviar campañas segmentadas por WhatsApp "
                "para recuperar clientes dormidos.\n\n"
                "Más de 60 pymes ya lo usan. Desde $88.000/mes.\n\n"
                "👉 emw.prizma.cloud\n\n"
                "#pymescolombia #whatsappmarketing #emw"
            ),
        },
        "PROMPT_IMAGEN": "Tech-premium workspace with WhatsApp marketing dashboard",
        "HASHTAGS": ["#pymescolombia", "#whatsappmarketing", "#emw"],
        "PILAR_NARRATIVO": "3. Para tu negocio real",
        "TIPO_CONTENIDO": "pain_point",
    }


@pytest.fixture
def sample_evaluacion():
    """Evaluación de ejemplo que devolvería cerebro.evaluar_calidad_post()."""
    return {
        "score_total": 85,
        "dimensiones": {
            "voz_tono": 90,
            "pain_point": 80,
            "cta": 85,
            "reglas": 90,
            "engagement": 80,
        },
        "feedback": "Buen copy, pain point claro.",
        "mejoras": ["Agregar más prueba social"],
        "aprobado": True,
    }


@pytest.fixture
def mock_requests():
    """Mock de requests para evitar llamadas reales a APIs."""
    with patch("requests.post") as mock_post, patch("requests.get") as mock_get:
        # Default: respuesta exitosa de Graph API
        mock_post.return_value = MagicMock(
            json=MagicMock(return_value={"id": "123_456", "success": True}),
            status_code=200,
        )
        mock_get.return_value = MagicMock(
            json=MagicMock(return_value={"data": [], "is_valid": True}),
            status_code=200,
        )
        yield {"post": mock_post, "get": mock_get}


@pytest.fixture
def tmp_queue_dir(tmp_path):
    """Directorio temporal para la cola de publicaciones."""
    queue_dir = tmp_path / "queue"
    queue_dir.mkdir()
    return queue_dir
