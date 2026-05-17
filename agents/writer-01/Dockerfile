# ─────────────────────────────────────────────────────────────────────────────
#  WriterBot — Seller-provided agent image
#  Image tag: agentmarket/writer:v1
#
#  Build:
#    docker build -t agentmarket/writer:v1 .
# ─────────────────────────────────────────────────────────────────────────────

FROM agentmarket/base:v1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir --default-timeout=300 --retries 10 -r requirements.txt

COPY agent.py  .
COPY server.py .

ENV LLM_MODEL=llama-3.1-8b-instant
ENV PORT=8000
ENV PYTHONUNBUFFERED=1

HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
  CMD curl -f http://localhost:${PORT}/health || exit 1

EXPOSE ${PORT}

CMD ["sh", "-c", "uvicorn server:app --host 0.0.0.0 --port ${PORT}"]
