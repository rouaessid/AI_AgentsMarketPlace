"""
backend/app/services/proxy_service.py
=======================================
Proxy réseau MITM complet — mitmproxy.

Détection providers :
  - Providers CONNUS  → nom lisible depuis _TOOL_MAP (groq, tavily, openai...)
  - Providers INCONNUS → auto-détection depuis structure JSON de la réponse
                         usage{} + choices[] → "llm"
                         results[]           → "search"
                         data[].embedding    → "embedding"
                         sinon               → "external"

Métriques capturées pour TOUT appel (connu ou inconnu) :
  System  : tokens_prompt, tokens_completion, tokens_total,
            cost_usd, latency_ms, total_latency_ms, errors_count
  Tool    : tool_name, tool_category, tools_used, llm_calls, search_calls
  Content : request_messages, request_query, response_content, response_results
  Trace   : trajectory[] — ordre chronologique complet
"""
from __future__ import annotations

import asyncio
import glob
import hashlib
import json
import logging
import socket
import tempfile
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ─── Providers connus ────────────────────────────────────────────────────────

_TOOL_MAP: list[tuple[str, str]] = [
    ("api.groq.com",              "groq"),
    ("api.openai.com",            "openai"),
    ("api.anthropic.com",         "anthropic"),
    ("api.tavily.com",            "tavily"),
    ("api.serper.dev",            "serper"),
    ("api.together.xyz",          "together"),
    ("api.cohere.com",            "cohere"),
    ("generativelanguage.google", "gemini"),
    ("api.mistral.ai",            "mistral"),
    ("api.fireworks.ai",          "fireworks"),
    ("api.perplexity.ai",         "perplexity"),
    ("api.deepseek.com",          "deepseek"),
    ("api.replicate.com",         "replicate"),
    ("huggingface.co",            "huggingface"),
    ("api.searchapi.io",          "searchapi"),
    ("serpapi.com",               "serpapi"),
    ("api.bing.microsoft.com",    "bing"),
    ("api.exa.ai",                "exa"),
    ("api.you.com",               "you"),
]

_TOOL_CATEGORY: dict[str, str] = {
    "groq": "llm", "openai": "llm", "anthropic": "llm",
    "together": "llm", "cohere": "llm", "gemini": "llm",
    "mistral": "llm", "fireworks": "llm", "perplexity": "llm",
    "deepseek": "llm", "replicate": "llm", "huggingface": "llm",
    "tavily": "search", "serper": "search", "searchapi": "search",
    "serpapi": "search", "bing": "search", "exa": "search", "you": "search",
}

_COST_PER_TOKEN: dict[str, float] = {
    "groq":       0.0000008,
    "openai":     0.000003,
    "anthropic":  0.000003,
    "together":   0.0000009,
    "mistral":    0.000001,
    "deepseek":   0.0000005,
    "fireworks":  0.0000009,
    "perplexity": 0.000001,
    "cohere":     0.000001,
    "gemini":     0.0000005,
}

# Estimation par catégorie pour providers inconnus
_CATEGORY_COST: dict[str, float] = {
    "llm":       0.000002,
    "search":    0.0,
    "embedding": 0.0000001,
    "external":  0.0,
}

_LLM_CATEGORIES    = {"llm"}
_SEARCH_CATEGORIES = {"search"}


# ─── Fonctions de détection ───────────────────────────────────────────────────

def _detect_tool(host: str) -> str | None:
    """Retourne le nom du provider si connu, None sinon."""
    for pattern, name in _TOOL_MAP:
        if pattern in host:
            return name
    return None


def _detect_category_from_response(resp_body: dict) -> str:
    """
    Auto-détecte la catégorie fonctionnelle depuis la structure JSON.
    Fonctionne pour n'importe quel provider, connu ou non.
    """
    if not resp_body or not isinstance(resp_body, dict):
        return "external"

    has_usage   = "usage" in resp_body
    has_choices = "choices" in resp_body
    has_content = isinstance(resp_body.get("content"), list)

    # LLM — a usage{} + choices[] (OpenAI/Groq) ou content[] (Anthropic)
    if has_usage and (has_choices or has_content):
        return "llm"

    # Search — a results[] ou organic_results[]
    if "results" in resp_body or "organic_results" in resp_body:
        return "search"

    # Embedding — a data[].embedding
    data = resp_body.get("data", [])
    if (data and isinstance(data, list)
            and isinstance(data[0], dict)
            and "embedding" in data[0]):
        return "embedding"

    return "external"


def _resolve_tool_and_category(host: str, resp_body: dict) -> tuple[str, str]:
    """
    Retourne (tool_name, tool_category).
    - Provider connu  → nom lisible + catégorie connue
    - Provider inconnu → host:port + catégorie auto-détectée depuis réponse
    """
    known = _detect_tool(host)
    if known:
        return known, _TOOL_CATEGORY.get(known, "unknown")

    # Provider inconnu — auto-détecter depuis la réponse
    category = _detect_category_from_response(resp_body)
    return host, category


def _cost(tool: str, category: str, tokens: int) -> float:
    """Coût en USD — précis si provider connu, estimé sinon."""
    if tool in _COST_PER_TOKEN:
        return tokens * _COST_PER_TOKEN[tool]
    return tokens * _CATEGORY_COST.get(category, 0.0)


# ─── Dataclasses ─────────────────────────────────────────────────────────────

@dataclass
class ApiCall:
    seq:               int
    tool:              str          # provider connu ou host:port
    tool_category:     str          # "llm" | "search" | "embedding" | "external"
    url:               str
    method:            str
    status:            int
    latency_ms:        float
    timestamp:         str
    tokens_prompt:     int   = 0
    tokens_completion: int   = 0
    tokens_total:      int   = 0
    cost_usd:          float = 0.0
    error:             str  | None = None
    request_messages:  list | None = None   # messages[] LLM
    request_query:     str  | None = None   # query search
    response_content:  str  | None = None   # réponse LLM
    response_results:  int  | None = None   # nb résultats search

    def to_dict(self) -> dict:
        return {
            "seq":               self.seq,
            "tool":              self.tool,
            "tool_category":     self.tool_category,
            "url":               self.url,
            "method":            self.method,
            "status":            self.status,
            "latency_ms":        round(self.latency_ms, 1),
            "timestamp":         self.timestamp,
            "tokens_prompt":     self.tokens_prompt,
            "tokens_completion": self.tokens_completion,
            "tokens_total":      self.tokens_total,
            "cost_usd":          round(self.cost_usd, 8),
            "error":             self.error,
            "request_messages":  self.request_messages,
            "request_query":     self.request_query,
            "response_content":  self.response_content,
            "response_results":  self.response_results,
        }


@dataclass
class ProxyTrace:
    run_id:           str
    agent_id:         str
    started_at:       str
    finished_at:      str   = ""
    total_tokens:     int   = 0
    total_cost_usd:   float = 0.0
    total_latency_ms: float = 0.0
    errors_count:     int   = 0
    tools_used:       list  = field(default_factory=list)   # noms providers
    categories_used:  list  = field(default_factory=list)   # catégories fonctionnelles
    llm_calls:        int   = 0
    search_calls:     int   = 0
    calls:            list  = field(default_factory=list)   # list[ApiCall]
    proxy_hash:       str   = ""

    def to_dict(self) -> dict:
        return {
            "run_id":           self.run_id,
            "agent_id":         self.agent_id,
            "started_at":       self.started_at,
            "finished_at":      self.finished_at,
            "total_tokens":     self.total_tokens,
            "total_cost_usd":   round(self.total_cost_usd, 6),
            "total_latency_ms": round(self.total_latency_ms, 1),
            "errors_count":     self.errors_count,
            "tools_used":       self.tools_used,
            "categories_used":  self.categories_used,
            "llm_calls":        self.llm_calls,
            "search_calls":     self.search_calls,
            "trajectory":       [c.to_dict() for c in self.calls],
            "proxy_hash":       self.proxy_hash,
        }


# ─── Addon mitmproxy ─────────────────────────────────────────────────────────

class _CaptureAddon:
    """Capture chaque flow HTTP/HTTPS intercepté par mitmproxy."""

    def __init__(self, trace: ProxyTrace, lock: threading.Lock):
        self.trace  = trace
        self.lock   = lock
        self._start: dict[int, float] = {}
        self._seq   = 0

    def request(self, flow: Any) -> None:
        self._start[id(flow)] = time.time() * 1000

    def response(self, flow: Any) -> None:
        latency = time.time() * 1000 - self._start.pop(id(flow), time.time() * 1000)
        host    = flow.request.host or ""

        # ── Parser requête ────────────────────────────────────────────────
        req_messages = None
        req_query    = None
        req_body     = {}
        try:
            req_body = json.loads(flow.request.content.decode(errors="replace"))
            if "messages" in req_body:
                req_messages = req_body["messages"]
            req_query = req_body.get("query") or req_body.get("q")
        except Exception:
            pass

        # ── Parser réponse ────────────────────────────────────────────────
        resp_body     = {}
        tokens_prompt = tokens_completion = tokens_total = 0
        resp_content  = None
        resp_results  = None
        error_msg     = None

        try:
            resp_body = json.loads(flow.response.content.decode(errors="replace"))

            # Tokens — format OpenAI/Groq/Anthropic
            usage             = resp_body.get("usage", {})
            tokens_prompt     = usage.get("prompt_tokens",     0) or usage.get("input_tokens",  0)
            tokens_completion = usage.get("completion_tokens", 0) or usage.get("output_tokens", 0)
            tokens_total      = usage.get("total_tokens",      0) or (tokens_prompt + tokens_completion)

            # Contenu LLM — format OpenAI/Groq
            choices = resp_body.get("choices", [])
            if choices:
                resp_content = choices[0].get("message", {}).get("content", "")
            # Format Anthropic
            for block in resp_body.get("content", []):
                if isinstance(block, dict) and block.get("type") == "text":
                    resp_content = block.get("text", "")
                    break

            # Résultats search
            results = resp_body.get("results", []) or resp_body.get("organic_results", [])
            if results:
                resp_results = len(results)

            if "error" in resp_body:
                error_msg = str(resp_body["error"])

        except Exception:
            pass

        status = flow.response.status_code
        if status >= 400:
            error_msg = error_msg or f"HTTP {status}"

        # ── Résoudre tool + catégorie ─────────────────────────────────────
        tool, category = _resolve_tool_and_category(host, resp_body)

        # ── Enregistrer ───────────────────────────────────────────────────
        with self.lock:
            self._seq += 1
            call = ApiCall(
                seq=self._seq,
                tool=tool,
                tool_category=category,
                url=flow.request.pretty_url,
                method=flow.request.method,
                status=status,
                latency_ms=latency,
                timestamp=datetime.now(timezone.utc).isoformat(),
                tokens_prompt=tokens_prompt,
                tokens_completion=tokens_completion,
                tokens_total=tokens_total,
                cost_usd=_cost(tool, category, tokens_total),
                error=error_msg,
                request_messages=req_messages,
                request_query=req_query,
                response_content=resp_content[:2000] if resp_content else None,
                response_results=resp_results,
            )
            self.trace.calls.append(call)
            self.trace.total_tokens     += tokens_total
            self.trace.total_cost_usd   += call.cost_usd
            self.trace.total_latency_ms += latency

            if status >= 400 or error_msg:
                self.trace.errors_count += 1

            # tools_used — nom du provider (connu ou host)
            if tool not in self.trace.tools_used and category != "external":
                self.trace.tools_used.append(tool)

            # categories_used — catégories fonctionnelles distinctes
            if category not in self.trace.categories_used and category != "external":
                self.trace.categories_used.append(category)

            # Compteurs par type
            if category in _LLM_CATEGORIES:
                self.trace.llm_calls += 1
            elif category in _SEARCH_CATEGORIES:
                self.trace.search_calls += 1

        logger.info(
            "Proxy: [%d] %s %s (%s) → %d tokens=%d %.0fms",
            self._seq, flow.request.method,
            flow.request.pretty_url[:55], category,
            status, tokens_total, latency,
        )

    def error(self, flow: Any) -> None:
        host = flow.request.host if flow.request else "unknown"
        err  = str(flow.error) if flow.error else "Connection error"
        with self.lock:
            self._seq += 1
            self.trace.calls.append(ApiCall(
                seq=self._seq,
                tool=host,
                tool_category="external",
                url=flow.request.pretty_url if flow.request else "unknown",
                method=flow.request.method if flow.request else "?",
                status=0,
                latency_ms=0,
                timestamp=datetime.now(timezone.utc).isoformat(),
                error=err,
            ))
            self.trace.errors_count += 1
        logger.warning("Proxy error: %s — %s", host, err)


# ─── ProxyService ─────────────────────────────────────────────────────────────

class ProxyService:
    """
    Lance mitmproxy MITM dans un thread asyncio séparé.

    Usage dans sandbox_service.py :
        proxy = ProxyService(run_id, agent_id, settings.storage_path)
        proxy_port, ca_cert_path = proxy.start()
        # injecter dans docker : -e HTTP_PROXY -e HTTPS_PROXY
        trace = proxy.stop()
    """

    def __init__(self, run_id: str, agent_id: str, storage_path: str):
        self.run_id       = run_id
        self.agent_id     = agent_id
        self.storage_path = Path(storage_path)
        self._trace       = ProxyTrace(
            run_id=run_id,
            agent_id=agent_id,
            started_at=datetime.now(timezone.utc).isoformat(),
        )
        self._lock        = threading.Lock()
        self._master      = None
        self._thread      = None
        self._ready       = threading.Event()
        self._port        = 0
        self._confdir     = None
        self._ca_cert_path: str | None = None

    def start(self) -> tuple[int, str | None]:
        """Démarre mitmproxy. Retourne (port, ca_cert_path)."""
        self._confdir = str(self.storage_path / "proxy")
        Path(self._confdir).mkdir(parents=True, exist_ok=True)

        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        self._port = s.getsockname()[1]
        s.close()

        def _run():
            async def _inner():
                try:
                    from mitmproxy import options
                    from mitmproxy.tools.dump import DumpMaster
                    opts = options.Options(
                        listen_host="0.0.0.0",
                        listen_port=self._port,
                        confdir=self._confdir,
                        ssl_insecure=True,
                    )
                    self._master = DumpMaster(opts, with_termlog=False, with_dumper=False)
                    self._master.addons.add(_CaptureAddon(self._trace, self._lock))
                    self._ready.set()
                    await self._master.run()
                except Exception as e:
                    logger.error("mitmproxy: %s", e)
                    self._ready.set()
            asyncio.run(_inner())

        self._thread = threading.Thread(target=_run, daemon=True)
        self._thread.start()
        self._ready.wait(timeout=10)
        time.sleep(0.5)

        certs = glob.glob(f"{self._confdir}/mitmproxy-ca-cert.pem")
        if certs:
            self._ca_cert_path = certs[0]

        logger.info("ProxyService port=%d ca_cert=%s", self._port, self._ca_cert_path is not None)
        return self._port, self._ca_cert_path

    def stop(self) -> ProxyTrace:
        """Arrête mitmproxy. Retourne ProxyTrace finale."""
        if self._master:
            try:
                self._master.shutdown()
            except Exception:
                pass
        if self._thread:
            self._thread.join(timeout=3)

        self._trace.finished_at = datetime.now(timezone.utc).isoformat()

        # Hash cryptographique de la trace complète
        trace_json = json.dumps(self._trace.to_dict(), sort_keys=True, ensure_ascii=False)
        self._trace.proxy_hash = "0x" + hashlib.sha256(trace_json.encode()).hexdigest()

        self._save()
        logger.info(
            "ProxyTrace: tokens=%d cost=$%.4f errors=%d tools=%s categories=%s llm=%d search=%d",
            self._trace.total_tokens, self._trace.total_cost_usd,
            self._trace.errors_count, self._trace.tools_used,
            self._trace.categories_used,
            self._trace.llm_calls, self._trace.search_calls,
        )
        return self._trace

    def _save(self) -> None:
        try:
            out = self.storage_path / "proxy_traces"
            out.mkdir(parents=True, exist_ok=True)
            path = out / f"{self.run_id}.json"
            path.write_text(
                json.dumps(self._trace.to_dict(), indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            logger.info("ProxyTrace saved: %s", path)
        except Exception as e:
            logger.warning("Save ProxyTrace: %s", e)

    @property
    def port(self) -> int:
        return self._port

    @property
    def ca_cert_path(self) -> str | None:
        return self._ca_cert_path


# ─── Génération image de base ─────────────────────────────────────────────────

def generate_base_image(output_dir: str | Path) -> None:
    """
    Génère CA cert mitmproxy + Dockerfile dans output_dir.

    À appeler UNE SEULE FOIS depuis le terminal :
        cd backend/
        python -c "
        from app.services.proxy_service import generate_base_image
        generate_base_image('../agent-base/')
        "
        docker build -t agentmarket/base:v1 ../agent-base/
    """
    import shutil
    from mitmproxy.certs import CertStore

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    # Générer CA cert
    tmp = Path(tempfile.mkdtemp())
    CertStore.create_store(tmp, "mitmproxy", 2048, None)
    shutil.copy(tmp / "mitmproxy-ca-cert.pem", out / "mitmproxy-ca-cert.pem")
    shutil.rmtree(tmp)

    # Dockerfile
    (out / "Dockerfile").write_text("""\
# agentmarket/base:v1
# Image de base pour tous les agents AgentMarket.
# Contient le CA cert mitmproxy — permet MITM HTTPS.
# Les agents font : FROM agentmarket/base:v1

FROM python:3.11-slim

COPY mitmproxy-ca-cert.pem /usr/local/share/mitmproxy-ca-cert.pem

RUN apt-get update -qq && \\
    apt-get install -y -qq ca-certificates && \\
    cp /usr/local/share/mitmproxy-ca-cert.pem \\
       /usr/local/share/ca-certificates/mitmproxy-ca.crt && \\
    update-ca-certificates && \\
    apt-get clean && rm -rf /var/lib/apt/lists/*

ENV SSL_CERT_FILE=/usr/local/share/mitmproxy-ca-cert.pem
ENV REQUESTS_CA_BUNDLE=/usr/local/share/mitmproxy-ca-cert.pem
ENV CURL_CA_BUNDLE=/usr/local/share/mitmproxy-ca-cert.pem
ENV NODE_EXTRA_CA_CERTS=/usr/local/share/mitmproxy-ca-cert.pem

RUN pip install certifi --quiet && python -c "
import certifi
with open('/usr/local/share/mitmproxy-ca-cert.pem', 'rb') as f:
    cert = f.read()
with open(certifi.where(), 'ab') as f:
    f.write(b'\\\\n' + cert)
print('certifi patched OK')
"

WORKDIR /app
""", encoding="utf-8")

    print(f"✅ Généré dans : {out.resolve()}")
    print(f"   Prochaine commande :")
    print(f"   docker build -t agentmarket/base:v1 {out.resolve()}")