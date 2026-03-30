from __future__ import annotations
import hashlib
import json
import logging
from pathlib import Path

import httpx
from app.core.config import get_settings

logger   = logging.getLogger(__name__)
settings = get_settings()


def _sha256(content: str) -> str:
    return "0x" + hashlib.sha256(content.encode()).hexdigest()


def _local_cid(content: str) -> str:
    h = hashlib.sha256(content.encode()).hexdigest()[:40]
    return f"QmLOCAL{h}"


async def _store_local(cid: str, content: str) -> None:
    base = Path(settings.storage_path) / "ipfs_local"
    base.mkdir(parents=True, exist_ok=True)
    (base / f"{cid}.json").write_text(content, encoding="utf-8")


async def _pin_pinata(content: str, name: str) -> str:
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            "https://api.pinata.cloud/pinning/pinJSONToIPFS",
            headers={
                "pinata_api_key":        settings.pinata_api_key,
                "pinata_secret_api_key": settings.pinata_secret,
                "Content-Type":          "application/json",
            },
            json={
                "pinataContent":  json.loads(content),
                "pinataMetadata": {"name": name},
                "pinataOptions":  {"cidVersion": 1},
            },
        )
        resp.raise_for_status()
        return resp.json()["IpfsHash"]


class IPFSService:

    async def upload(
        self,
        content_json: str,
        name: str = "agent",
    ) -> tuple[str, str, str]:
        """Retourne (cid, agent_uri, metadata_hash)."""
        metadata_hash = _sha256(content_json)
        if not settings.use_ipfs:
            cid = _local_cid(content_json)
            await _store_local(cid, content_json)
        else:
            cid = await _pin_pinata(content_json, name)
        return cid, f"ipfs://{cid}", metadata_hash

    async def get(self, cid: str) -> dict:
        if not settings.use_ipfs or cid.startswith("QmLOCAL"):
            p = Path(settings.storage_path) / "ipfs_local" / f"{cid}.json"
            if p.exists():
                return json.loads(p.read_text())
            raise FileNotFoundError(f"Local IPFS: {cid}")
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(f"{settings.ipfs_gateway}/{cid}")
            resp.raise_for_status()
            return resp.json()