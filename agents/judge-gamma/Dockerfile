# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
#  Judge Gamma â€” Seller-provided judge image
#  Image tag: agentmarket/judge-gamma:v1
#
#  Role: Behavioural trace analysis judge â€” no external search tools.
#  Evaluates execution process: tool call logic, trajectory coherence,
#  consistency between process and output, suspicious patterns.
#  Uses temperature 0.3 for a genuinely independent third opinion.
#
#  The judge provider provides ONLY:
#    - This Dockerfile
#    - agent.py (evaluation logic + embedded HTTP server)
#    - requirements.txt
#    - manifest.json (agent_type=judge â€” registered via frontend form)
#
#  Build:
#    docker build -t agentmarket/judge-gamma:v1 .
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

FROM agentmarket/base:v1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir --default-timeout=300 --retries 10 -r requirements.txt

COPY agent.py .

ENV AGENT_ID=judge-gamma
ENV AGENT_NAME="Judge Gamma"
ENV LLM_MODEL=mistral-small-latest
ENV LLM_BASE_URL=https://api.mistral.ai/v1
ENV PORT=8000
ENV PYTHONUNBUFFERED=1

HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
  CMD curl -f http://localhost:${PORT}/health || exit 1

EXPOSE ${PORT}

CMD ["sh", "-c", "uvicorn agent:app --host 0.0.0.0 --port ${PORT}"]
