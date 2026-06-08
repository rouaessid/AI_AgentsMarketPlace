"""
auth.py — Sign-In With Ethereum (SIWE) authentication endpoints.

Flow:
  1. GET  /auth/nonce?wallet=0x...  → platform generates a nonce message
  2. POST /auth/verify              → wallet signs nonce, platform verifies → JWT
  3. GET  /auth/me                  → returns wallet + auto-detected roles (JWT required)

Roles are derived from DB state — no manual role selection:
  - provider : wallet has at least one registered agent (owner_address)
  - buyer    : wallet has at least one access grant    (buyer_wallet)
  - both     : possible and fully supported
"""
from __future__ import annotations

import secrets
import time
from typing import Optional

from eth_account import Account
from eth_account.messages import encode_defunct
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from pydantic import BaseModel

from app.core.config import get_settings

router  = APIRouter(prefix="/auth", tags=["auth"])
_bearer = HTTPBearer(auto_error=False)

# In-memory nonce store: {wallet_lower: (nonce, message, expires_at)}
_nonces: dict[str, tuple[str, str, float]] = {}
_NONCE_TTL = 300  # 5 minutes


# ── Helpers ───────────────────────────────────────────────────────────────────

def _settings():
    return get_settings()


def _build_message(wallet: str, nonce: str) -> str:
    ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    return (
        f"Sign in to AgentMarket\n\n"
        f"Wallet: {wallet}\n"
        f"Nonce: {nonce}\n"
        f"Issued At: {ts}"
    )


def _detect_roles(wallet: str) -> dict[str, bool]:
    """Derive provider/buyer roles from DB — no manual selection."""
    from app.services.agent_service import _records
    from app.repo.access_repo import verify_access

    wallet_lower = wallet.lower()
    is_provider  = any(
        (r.owner_address or "").lower() == wallet_lower
        for r in _records.values()
    )
    # is_buyer : vérifié on-chain si une access_grant existe pour ce wallet
    try:
        from app.repo.database import get_session
        from app.entities.access import AccessGrant
        with get_session() as s:
            grants = s.query(AccessGrant).all()
        is_buyer = any(
            verify_access(g.agent_id, wallet_lower)
            for g in grants
        )
    except Exception:
        is_buyer = False

    return {"isProvider": is_provider, "isBuyer": is_buyer}


def _make_token(wallet: str, roles: dict) -> str:
    settings = _settings()
    payload = {
        "wallet": wallet.lower(),
        "roles":  roles,
        "exp":    int(time.time()) + 60 * 60 * 24,  # 24h
        "iat":    int(time.time()),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def _verify_token(credentials: Optional[HTTPAuthorizationCredentials]) -> dict:
    if not credentials:
        raise HTTPException(401, "Authentication required")
    try:
        settings = _settings()
        return jwt.decode(credentials.credentials, settings.jwt_secret, algorithms=["HS256"])
    except JWTError:
        raise HTTPException(401, "Invalid or expired token")


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/nonce")
def get_nonce(wallet: str = Query(..., description="Wallet address (0x...)")):
    """Generate a sign-in challenge for the given wallet."""
    wallet = wallet.lower().strip()
    if not wallet.startswith("0x") or len(wallet) != 42:
        raise HTTPException(400, "Invalid wallet address")

    nonce   = secrets.token_hex(8)
    message = _build_message(wallet, nonce)

    _nonces[wallet] = (nonce, message, time.time() + _NONCE_TTL)
    return {"wallet": wallet, "message": message, "nonce": nonce}


class VerifyRequest(BaseModel):
    wallet:    str
    signature: str


@router.post("/verify")
def verify_signature(body: VerifyRequest):
    """Verify MetaMask signature → return JWT with auto-detected roles."""
    wallet = body.wallet.lower().strip()
    sig    = body.signature.strip()

    stored = _nonces.get(wallet)
    if not stored:
        raise HTTPException(400, "No nonce found — request /auth/nonce first")

    nonce, message, expires_at = stored
    if time.time() > expires_at:
        _nonces.pop(wallet, None)
        raise HTTPException(400, "Nonce expired — request a new one")

    # Recover the signer address from the signature
    msg_hash = encode_defunct(text=message)
    try:
        recovered = Account.recover_message(msg_hash, signature=sig).lower()
    except Exception as e:
        raise HTTPException(400, f"Invalid signature: {e}")

    if recovered != wallet:
        raise HTTPException(401, "Signature mismatch — wrong wallet")

    # Consume the nonce (prevent replay)
    _nonces.pop(wallet, None)

    roles = _detect_roles(wallet)
    token = _make_token(wallet, roles)

    return {
        "token":  token,
        "wallet": wallet,
        "roles":  roles,
    }


@router.get("/me")
def get_me(credentials: HTTPAuthorizationCredentials = Depends(_bearer)):
    """Return authenticated wallet + current roles (re-derived from DB)."""
    payload = _verify_token(credentials)
    wallet  = payload["wallet"]
    roles   = _detect_roles(wallet)
    return {"wallet": wallet, "roles": roles}


@router.post("/refresh")
def refresh_token(credentials: HTTPAuthorizationCredentials = Depends(_bearer)):
    """Issue a fresh token (re-derives roles from current DB state)."""
    payload = _verify_token(credentials)
    wallet  = payload["wallet"]
    roles   = _detect_roles(wallet)
    token   = _make_token(wallet, roles)
    return {"token": token, "wallet": wallet, "roles": roles}
