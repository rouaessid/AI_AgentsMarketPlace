# ─────────────────────────────────────────────────────────────────────────────
#  ResearchBot — Seller-provided agent image
#  Image tag: agentmarket/researcher:v1
#
#  This is ALL the seller writes.
#  The platform handles:
#    - Running this container behind its proxy (trace capture)
#    - IPFS upload of traces
#    - On-chain validationRequest()
#    - Stake & escrow management
#
#  The seller provides ONLY:
#    - This Dockerfile
#    - agent.py (business logic)
#    - server.py (HTTP server)
#    - requirements.txt
#    - manifest.json (filled via the registration form)
#
#  Build:
#    docker build -t agentmarket/researcher:v1 .
# ─────────────────────────────────────────────────────────────────────────────

# Platform base image — already has the proxy CA cert injected
# so ALL outgoing HTTPS calls (Groq, Tavily) are captured by the platform proxy
FROM agentmarket/base:v1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir --default-timeout=300 --retries 10 -r requirements.txt

COPY agent.py  .
COPY server.py .

ENV LLM_MODEL=llama-3.3-70b-versatile
ENV TAVILY_MAX_RESULTS=5
ENV PORT=8000
ENV PYTHONUNBUFFERED=1

HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
  CMD curl -f http://localhost:${PORT}/health || exit 1

EXPOSE ${PORT}

CMD ["sh", "-c", "uvicorn server:app --host 0.0.0.0 --port ${PORT}"]
