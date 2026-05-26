from __future__ import annotations
import hashlib
import json
import logging

import httpx
from app.core.config import get_settings

logger   = logging.getLogger(__name__)
settings = get_settings()


def _sha256(content: str) -> str:
    return "0x" + hashlib.sha256(content.encode()).hexdigest()


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
        """Pin to Pinata and return (cid, agent_uri, metadata_hash)."""
        metadata_hash = _sha256(content_json)
        cid = await _pin_pinata(content_json, name)
        return cid, f"ipfs://{cid}", metadata_hash

    async def get(self, cid: str) -> dict:
        for url in [
            f"https://gateway.pinata.cloud/ipfs/{cid}",
            f"https://ipfs.io/ipfs/{cid}",
        ]:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(url)
                if resp.status_code == 200:
                    return resp.json()
        raise FileNotFoundError(f"CID {cid} not found on IPFS")