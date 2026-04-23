# ─────────────────────────────────────────────────────────────────────────────
#  Judge Beta — Seller-provided judge image
#  Image tag: agentmarket/judge-beta:v1
#
#  Role: Pure LLM reasoning judge — no external search tools.
#  Evaluates output correctness, completeness, coherence, and
#  absence of hallucinations using Groq only.
#
#  The judge provider provides ONLY:
#    - This Dockerfile
#    - agent.py (evaluation logic)
#    - server.py (HTTP server — same /run contract as any agent)
#    - requirements.txt
#    - manifest.json (agent_type=judge — registered via frontend form)
#
#  Build:
#    docker build -t agentmarket/judge-beta:v1 .
# ─────────────────────────────────────────────────────────────────────────────

FROM agentmarket/base:v1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir --default-timeout=300 --retries 10 -r requirements.txt

COPY agent.py  .
COPY server.py .
COPY .env      .

ENV AGENT_ID=judge-beta
ENV AGENT_NAME="Judge Beta"
ENV LLM_MODEL=llama-3.3-70b-versatile
ENV PORT=8000
ENV PYTHONUNBUFFERED=1

HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
  CMD curl -f http://localhost:${PORT}/health || exit 1

EXPOSE ${PORT}

CMD ["sh", "-c", "set -a && . ./.env && set +a && uvicorn server:app --host 0.0.0.0 --port ${PORT}"]
