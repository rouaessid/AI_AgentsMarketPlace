# ─────────────────────────────────────────────────────────────────────────────
#  Judge Alpha — Seller-provided judge image
#  Image tag: agentmarket/judge-alpha:v1
#
#  This is ALL the judge provider writes.
#  The platform handles:
#    - Running this container at validation time
#    - Passing the execution trace (from IPFS) as JSON in the prompt field
#    - Collecting the verdict and aggregating with other judges
#    - On-chain commit-reveal via ValidationRegistry
#
#  The judge provider provides ONLY:
#    - This Dockerfile
#    - agent.py (evaluation logic)
#    - server.py (HTTP server — same /run contract as any agent)
#    - requirements.txt
#    - manifest.json (filled via the registration form with agent_type=judge)
#
#  The judge provider knows NOTHING about:
#    - Platform internals
#    - IPFS, escrow, staking
#    - Other judges
#    - How consensus is computed
#
#  Build:
#    docker build -t agentmarket/judge-alpha:v1 .
# ─────────────────────────────────────────────────────────────────────────────

# Platform base image — CA cert injected so all HTTPS calls are captured
FROM agentmarket/base:v1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir --default-timeout=300 --retries 10 -r requirements.txt

COPY agent.py  .
COPY server.py .
COPY .env      .

ENV AGENT_ID=judge-alpha
ENV AGENT_NAME="Judge Alpha"
ENV LLM_MODEL=llama-3.3-70b-versatile
ENV PORT=8000
ENV PYTHONUNBUFFERED=1

HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
  CMD curl -f http://localhost:${PORT}/health || exit 1

EXPOSE ${PORT}

CMD ["sh", "-c", "set -a && . ./.env && set +a && uvicorn server:app --host 0.0.0.0 --port ${PORT}"]
