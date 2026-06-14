"""
test_publisher.py — Tests para publisher.py (publicación en Meta).
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


class TestMetaAdsManagerInit:
    """Verifica inicialización correcta de MetaAdsManager."""

    @patch("social.publisher.FacebookAdsApi")
    @patch("social.publisher.TokenManager")
    def test_init_con_token(self, mock_tm, mock_api, mock_env):
        from social.publisher import MetaAdsManager
        manager = MetaAdsManager()
        assert manager.page_id == "1045986888587355"
        assert manager.app_id == "test_app_id"

    @patch("social.publisher.FacebookAdsApi")
    @patch("social.publisher.TokenManager")
    def test_init_sin_token(self, mock_tm, mock_api, monkeypatch):
        monkeypatch.delenv("META_ACCESS_TOKEN", raising=False)
        from social.publisher import MetaAdsManager
        # No debe crashear sin token
        manager = MetaAdsManager()


class TestPublicarEnFeed:
    """Verifica publicación en feed de Facebook."""

    @patch("social.publisher.FacebookAdsApi")
    @patch("social.publisher.TokenManager")
    @patch("requests.post")
    def test_publicacion_exitosa(self, mock_post, mock_tm, mock_api, mock_env):
        mock_post.return_value = MagicMock(
            json=MagicMock(return_value={"id": "123_456"})
        )

        from social.publisher import MetaAdsManager
        manager = MetaAdsManager()
        manager._page_token = "fake_token"

        # Mock _get_page_token para retornar directamente
        manager._get_page_token = MagicMock(return_value="fake_token")

        result = manager.publicar_en_feed("Test message")
        assert result.get("success") is True
        assert result.get("post_id") == "123_456"

    @patch("social.publisher.FacebookAdsApi")
    @patch("social.publisher.TokenManager")
    @patch("requests.post")
    def test_publicacion_con_error(self, mock_post, mock_tm, mock_api, mock_env):
        mock_post.return_value = MagicMock(
            json=MagicMock(return_value={
                "error": {"message": "Invalid token"}
            })
        )

        from social.publisher import MetaAdsManager
        manager = MetaAdsManager()
        manager._get_page_token = MagicMock(return_value="fake_token")

        result = manager.publicar_en_feed("Test message")
        assert "error" in result

    @patch("social.publisher.FacebookAdsApi")
    @patch("social.publisher.TokenManager")
    def test_publicacion_sin_page_token(self, mock_tm, mock_api, mock_env):
        from social.publisher import MetaAdsManager
        manager = MetaAdsManager()
        manager._get_page_token = MagicMock(return_value=None)

        result = manager.publicar_en_feed("Test message")
        assert "error" in result


class TestPublicarConImagen:
    """Verifica publicación con imagen."""

    @patch("social.publisher.FacebookAdsApi")
    @patch("social.publisher.TokenManager")
    @patch("requests.post")
    def test_publicar_con_url(self, mock_post, mock_tm, mock_api, mock_env):
        mock_post.return_value = MagicMock(
            json=MagicMock(return_value={"id": "photo_789"})
        )

        from social.publisher import MetaAdsManager
        manager = MetaAdsManager()
        manager._get_page_token = MagicMock(return_value="fake_token")

        result = manager.publicar_con_imagen(
            "Test con imagen",
            image_url="https://example.com/img.png"
        )
        assert result.get("success") is True

    @patch("social.publisher.FacebookAdsApi")
    @patch("social.publisher.TokenManager")
    def test_publicar_sin_imagen(self, mock_tm, mock_api, mock_env):
        from social.publisher import MetaAdsManager
        manager = MetaAdsManager()
        manager._get_page_token = MagicMock(return_value="fake_token")

        result = manager.publicar_con_imagen("Test sin imagen")
        assert "error" in result
        assert "image_url o image_path" in result["error"]
