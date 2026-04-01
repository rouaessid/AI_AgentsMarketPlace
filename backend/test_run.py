"""
test_run.py
===========
Simule un buyer qui appelle l'agent via l'endpoint public.
Lance depuis backend/ : python test_run.py
"""
import json
import sys
import requests
from pathlib import Path
from dotenv import dotenv_values

# ── Config ────────────────────────────────────────────────────────────────────
AGENT_ID   = "strategy-1"
BASE_URL   = "http://localhost:8000"
ENV_FILE   = Path("C:/Users/Roua/Desktop/agent_seller/.env")
PROMPT     = "Analyse les tendances IA et Blockchain 2026"

# ── Charger les clés API du buyer depuis agent_seller/.env ────────────────────
if not ENV_FILE.exists():
    print(f"ERREUR: {ENV_FILE} introuvable")
    sys.exit(1)

env = dotenv_values(ENV_FILE)
GROQ_API_KEY   = env.get("GROQ_API_KEY", "")
TAVILY_API_KEY = env.get("TAVILY_API_KEY", "")

if not GROQ_API_KEY or not TAVILY_API_KEY:
    print("ERREUR: GROQ_API_KEY ou TAVILY_API_KEY manquant dans .env")
    sys.exit(1)

# ── Récupérer l'endpoint depuis la plateforme ─────────────────────────────────
print("Récupération de l'endpoint...")
info     = requests.get(f"{BASE_URL}/tunnel").json()
endpoint = info.get("endpoints", {}).get(AGENT_ID)

if not endpoint:
    print(f"Endpoint non trouvé — utilisation localhost")
    endpoint = f"{BASE_URL}/api/v1/agents/{AGENT_ID}/run"

print(f"Endpoint : {endpoint}")
print(f"Prompt   : {PROMPT}")
print(f"Clés     : GROQ ✅  TAVILY ✅")
print()

# ── Appel /run ────────────────────────────────────────────────────────────────
print("Envoi de la requête...")
try:
    result = requests.post(
        endpoint,
        json={
            "prompt": PROMPT,
            "params": {
                "GROQ_API_KEY":   GROQ_API_KEY,
                "TAVILY_API_KEY": TAVILY_API_KEY,
            }
        },
        timeout=120,
    )
except requests.exceptions.Timeout:
    print("ERREUR: Timeout après 120s")
    sys.exit(1)
except requests.exceptions.ConnectionError as e:
    print(f"ERREUR: Connexion impossible — {e}")
    sys.exit(1)

# ── Résultat ──────────────────────────────────────────────────────────────────
print(f"HTTP Status  : {result.status_code}")

if result.status_code != 200:
    print(f"ERREUR: {result.text}")
    sys.exit(1)

data = result.json()
print(f"Status agent : {data.get('status')}")
print(f"Duration     : {data.get('duration_sec')} s")
print(f"run_id       : {data.get('run_id')}")
print(f"token_id     : {data.get('token_id')}")
print(f"docker_image : {data.get('docker_image')}")
print(f"manifest_hash: {data.get('manifest_hash')}")
print(f"platform_sig : {data.get('platform_sig')}")
print()

output = data.get("output", {})
if isinstance(output, dict):
    print("Output:")
    print(output.get("output", "")[:500])
    print()
    print(f"Tavily results: {output.get('metrics', {}).get('results_count', 0)}")
else:
    print("Output:", str(output)[:500])