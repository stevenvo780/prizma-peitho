"""social/ — Integración con redes sociales (Meta / Facebook / Instagram)."""

from social.publisher import MetaAdsManager
from social.analytics import SocialAnalytics
from social.token_manager import TokenManager

__all__ = [
    "MetaAdsManager",
    "SocialAnalytics",
    "TokenManager",
]
