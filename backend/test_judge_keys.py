"""
test_judge_keys.py — vérifie que chaque config LLM juge fonctionne.
Lance depuis backend/ : python test_judge_keys.py
"""
import os, httpx

# Load .env
for line in open("../.env", encoding="utf-8"):
    line = line.strip()
    if "=" in line and not line.startswith("#"):
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())

GROQ_URL = "https://api.groq.com/openai/v1"
OR_URL   = "https://openrouter.ai/api/v1"
GEM_URL  = "https://generativelanguage.googleapis.com/v1beta/openai"

JUDGES = [
    {
        "name":     "judge-alpha",
        "key":      os.environ.get("JUDGE_ALPHA_GROQ_KEY") or os.environ.get("GROQ_API_KEY"),
        "base_url": GROQ_URL,
        "model":    "llama-3.1-8b-instant",
    },
    {
        "name":     "judge-beta",
        "key":      os.environ.get("JUDGE_BETA_OR_KEY") or os.environ.get("JUDGE_BETA_GROQ_KEY"),
        "base_url": OR_URL if os.environ.get("JUDGE_BETA_OR_KEY") else GROQ_URL,
        "model":    "meta-llama/llama-3.1-8b-instruct" if os.environ.get("JUDGE_BETA_OR_KEY") else "llama-3.1-8b-instant",
    },
    {
        "name":     "judge-gamma",
        "key":      os.environ.get("JUDGE_GAMMA_GROQ_KEY") or os.environ.get("GROQ_API_KEY"),
        "base_url": GROQ_URL,
        "model":    "llama-3.1-8b-instant",
    },
    {
        "name":     "judge-delta",
        "key":      os.environ.get("JUDGE_DELTA_GEMINI_KEY") or os.environ.get("JUDGE_DELTA_GROQ_KEY"),
        "base_url": GEM_URL if os.environ.get("JUDGE_DELTA_GEMINI_KEY") else GROQ_URL,
        "model":    "gemini-2.5-flash" if os.environ.get("JUDGE_DELTA_GEMINI_KEY") else "llama-3.1-8b-instant",
    },
    {
        "name":     "judge-epsilon",
        "key":      os.environ.get("JUDGE_EPSILON_OR_KEY") or os.environ.get("JUDGE_EPSILON_GROQ_KEY"),
        "base_url": OR_URL if os.environ.get("JUDGE_EPSILON_OR_KEY") else GROQ_URL,
        "model":    "meta-llama/llama-3.1-8b-instruct" if os.environ.get("JUDGE_EPSILON_OR_KEY") else "llama-3.1-8b-instant",
    },
]

def test(judge: dict) -> str:
    if not judge["key"]:
        return "FAIL  NO KEY"
    try:
        r = httpx.post(
            f"{judge['base_url']}/chat/completions",
            headers={"Authorization": f"Bearer {judge['key']}", "Content-Type": "application/json"},
            json={"model": judge["model"], "messages": [{"role": "user", "content": "Say OK"}], "max_tokens": 5},
            timeout=15,
        )
        if r.status_code == 200:
            reply = r.json()["choices"][0]["message"]["content"].strip()
            return f"OK  {r.status_code} — {reply!r}"
        return f"FAIL  {r.status_code} — {r.text[:120]}"
    except Exception as e:
        return f"FAIL  ERROR — {e}"

print(f"{'Judge':<16} {'Provider/Model':<42} Result")
print("-" * 90)
for j in JUDGES:
    provider = j["base_url"].split("/")[2].split(".")[0]  # groq / openrouter / googleapis
    label    = f"{provider} / {j['model']}"
    result   = test(j)
    print(f"{j['name']:<16} {label:<42} {result}")
