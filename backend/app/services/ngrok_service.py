from __future__ import annotations
import logging
from app.core.config import get_settings

logger   = logging.getLogger(__name__)
settings = get_settings()
_ngrok_url: str | None = None


async def start_ngrok() -> str | None:
    global _ngrok_url
    if settings.ngrok_base_url:
        _ngrok_url = settings.ngrok_base_url.rstrip("/")
        return _ngrok_url
    if not settings.ngrok_authtoken:
        return None
    try:
        from pyngrok import conf, ngrok as pyngrok
        conf.get_default().auth_token = settings.ngrok_authtoken
        tunnel = pyngrok.connect(settings.backend_port, "http")
        _ngrok_url = tunnel.public_url.rstrip("/")
        logger.info("Ngrok: %s", _ngrok_url)
        return _ngrok_url
    except Exception as e:
        logger.warning("Ngrok echec: %s", e)
        return None


def get_ngrok_url() -> str | None:
    return _ngrok_url


def get_agent_endpoint(agent_id: str) -> str | None:
    if not _ngrok_url:
        return None
    return f"{_ngrok_url}/api/v1/agents/{agent_id}/run"


async def stop_ngrok() -> None:
    try:
        from pyngrok import ngrok as pyngrok
        pyngrok.kill()
    except Exception:
        pass