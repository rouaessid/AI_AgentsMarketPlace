from __future__ import annotations
import asyncio
import json
import logging
import re
import shutil
import subprocess
import threading
from pathlib import Path
from typing import Optional

from app.core.config import get_settings

logger   = logging.getLogger(__name__)
settings = get_settings()

_ENDPOINTS_FILE = Path(settings.storage_path) / "endpoints.json"
_tunnel_url: str | None = None
_cf_process: Optional[subprocess.Popen] = None


def _load_endpoints() -> dict[str, str]:
    try:
        if _ENDPOINTS_FILE.exists():
            return json.loads(_ENDPOINTS_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning("Erreur lecture endpoints.json: %s", e)
    return {}


def _save_endpoints(endpoints: dict[str, str]) -> None:
    try:
        _ENDPOINTS_FILE.parent.mkdir(parents=True, exist_ok=True)
        _ENDPOINTS_FILE.write_text(
            json.dumps(endpoints, indent=2, ensure_ascii=False),
            encoding="utf-8"
        )
    except Exception as e:
        logger.warning("Erreur sauvegarde endpoints.json: %s", e)


def _update_all_endpoints() -> None:
    if not _tunnel_url:
        return
    endpoints = _load_endpoints()
    if not endpoints:
        logger.info("Aucun agent enregistre — endpoints.json sera mis a jour au /confirm")
        return
    updated = {
        agent_id: f"{_tunnel_url}/api/v1/agents/{agent_id}/run"
        for agent_id in endpoints
    }
    _save_endpoints(updated)
    logger.info(
        "endpoints.json mis a jour — %d agents: %s",
        len(updated),
        list(updated.keys())
    )


async def _start_cloudflare_tunnel() -> str | None:
    global _cf_process

    cf_path = shutil.which("cloudflared")
    if not cf_path:
        logger.warning("cloudflared non trouve dans PATH")
        return None

    logger.info("cloudflared path: %s", cf_path)

    loop      = asyncio.get_event_loop()
    url_event = asyncio.Event()
    found_url = [None]

    def run_cloudflared():
        global _cf_process
        try:
            _cf_process = subprocess.Popen(
                [
                    cf_path, "tunnel", "--url",
                    f"http://localhost:{settings.backend_port}",
                    "--no-autoupdate",
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
            )

            logger.info("cloudflared PID: %s", _cf_process.pid)

            for line in _cf_process.stderr:
                line = line.strip()
                if line:
                    logger.debug("CF: %s", line)

                match = re.search(
                    r"https://[a-z0-9][a-z0-9\-]+\.trycloudflare\.com",
                    line
                )
                if match:
                    url = match.group(0).strip().rstrip("/")

                    # Exclure l'URL de l'API cloudflare — pas un tunnel
                    # Ex: "https://api.trycloudflare.com" depuis les messages d'erreur
                    if url in (
                        "https://api.trycloudflare.com",
                        "https://update.trycloudflare.com",
                    ):
                        logger.debug("CF: URL API ignoree: %s", url)
                        continue

                    found_url[0] = url
                    logger.info("URL trouvee: %s", found_url[0])
                    loop.call_soon_threadsafe(url_event.set)
                    # Continuer à lire stderr pour garder le tunnel actif
                    for _ in _cf_process.stderr:
                        pass
                    break

        except Exception as e:
            logger.warning("cloudflared thread error: %s", e)
            loop.call_soon_threadsafe(url_event.set)

    thread = threading.Thread(target=run_cloudflared, daemon=True)
    thread.start()

    try:
        await asyncio.wait_for(url_event.wait(), timeout=30)
    except asyncio.TimeoutError:
        logger.warning("Timeout 30s — URL cloudflare non trouvee")
        return None

    return found_url[0]


async def start_ngrok() -> str | None:
    global _tunnel_url

    # Priorité 1 — URL fixe dans .env
    base_url = settings.tunnel_base_url or settings.ngrok_base_url
    if base_url:
        _tunnel_url = base_url.rstrip("/")
        logger.info("Tunnel URL (static): %s", _tunnel_url)
        _update_all_endpoints()
        return _tunnel_url

    # Priorité 2 — cloudflared automatique
    _tunnel_url = await _start_cloudflare_tunnel()

    if _tunnel_url:
        _update_all_endpoints()
        return _tunnel_url

    # Priorité 3 — localhost fallback
    _tunnel_url = f"http://localhost:{settings.backend_port}"
    logger.info(
        "Pas de tunnel cloudflare — fallback localhost: %s",
        _tunnel_url
    )
    _update_all_endpoints()
    return _tunnel_url


def register_agent_endpoint(agent_id: str) -> str | None:
    if _tunnel_url:
        endpoint = f"{_tunnel_url}/api/v1/agents/{agent_id}/run"
    else:
        endpoint = (
            f"http://localhost:{settings.backend_port}"
            f"/api/v1/agents/{agent_id}/run"
        )
    endpoints = _load_endpoints()
    endpoints[agent_id] = endpoint
    _save_endpoints(endpoints)
    logger.info("Endpoint enregistre: %s → %s", agent_id, endpoint)
    return endpoint


def get_agent_endpoint(agent_id: str) -> str | None:
    if _tunnel_url:
        return f"{_tunnel_url}/api/v1/agents/{agent_id}/run"
    return _load_endpoints().get(agent_id)


def get_ngrok_url() -> str | None:
    return _tunnel_url


def get_all_endpoints() -> dict[str, str]:
    return _load_endpoints()


async def stop_ngrok() -> None:
    global _cf_process
    if _cf_process:
        try:
            _cf_process.terminate()
            logger.info("cloudflared arrete")
        except Exception:
            pass
        _cf_process = None