from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st
from utils.api import get_agent_readme, run_agent, get_tunnel_info


def render_agent_detail(agent_id: str) -> None:
    readme_data = get_agent_readme(agent_id)
    if not readme_data:
        st.error(f"Agent '{agent_id}' introuvable")
        return

    tunnel   = get_tunnel_info()
    endpoint = tunnel.get("endpoints", {}).get(agent_id, "")

    st.markdown(f"# 🤖 {readme_data.get('name', agent_id)}")
    st.caption(f"v{readme_data.get('version', '1.0.0')} · `{agent_id}`")

    pricing = readme_data.get("pricing", {})
    col1, col2, col3 = st.columns(3)
    col1.metric("Prix", f"${pricing.get('price_per_task', 0)} USDC")
    col2.metric("Durée accès", f"{pricing.get('access_duration_days', 30)} jours")
    col3.metric("Appels/jour", pricing.get("max_calls_per_day", 100))
    st.divider()

    tab1, tab2, tab3 = st.tabs(["📖 README", "💻 Intégration", "🧪 Test Live"])

    with tab1:
        readme = readme_data.get("readme", "Aucune documentation.")
        st.markdown(readme)
        st.download_button(
            label="📥 Download README.md",
            data=readme,
            file_name=f"{agent_id}_README.md",
            mime="text/markdown",
        )

    with tab2:
        st.markdown("### Comment utiliser cet agent dans votre code")
        env_keys = readme_data.get("env_var_keys", [])
        params_example = "\n".join(
            [f'                "{k}": "votre_{k.lower()}",' for k in env_keys]
        )
        code = f'''import requests

ENDPOINT = "{endpoint}"

response = requests.post(
    ENDPOINT,
    json={{
        "prompt": "Votre question ou tâche ici",
        "params": {{
{params_example}
        }}
    }},
    timeout=120,
)

result = response.json()
print("Status  :", result["status"])
print("Output  :", result["output"])
print("Manifest:", result["manifest_hash"])
'''
        st.code(code, language="python")
        st.download_button(
            label="📥 Download script Python",
            data=code,
            file_name=f"use_{agent_id}.py",
            mime="text/plain",
        )
        st.info(f"🔗 Endpoint : `{endpoint}`")

    with tab3:
        st.markdown("### Tester l'agent directement")
        env_keys = readme_data.get("env_var_keys", [])

        prompt = st.text_area(
            "Prompt",
            placeholder="Ex: Analyse les tendances IA 2026",
            height=100,
            key=f"prompt_{agent_id}"
        )

        st.markdown("**Clés API requises :**")
        params = {}
        for key in env_keys:
            val = st.text_input(
                key,
                type="password",
                placeholder=f"Votre {key}",
                key=f"param_{agent_id}_{key}"
            )
            if val:
                params[key] = val

        if st.button("▶️ Lancer", key=f"run_{agent_id}", type="primary"):
            if not prompt:
                st.warning("Entrer un prompt")
            elif len(params) < len(env_keys):
                missing = [k for k in env_keys if k not in params]
                st.warning(f"Clés manquantes : {missing}")
            else:
                with st.spinner("Exécution en cours..."):
                    try:
                        result = run_agent(agent_id, prompt, params)
                        st.success(
                            f"✅ Status: {result['status']} ({result['duration_sec']}s)"
                        )
                        output = result.get("output", {})
                        if isinstance(output, dict):
                            st.markdown("### Output")
                            st.markdown(output.get("output", ""))
                        else:
                            st.markdown(str(output))

                        with st.expander("🔍 Détails manifest"):
                            st.json({
                                "run_id":        result.get("run_id"),
                                "token_id":      result.get("token_id"),
                                "docker_image":  result.get("docker_image"),
                                "manifest_hash": result.get("manifest_hash"),
                                "platform_sig":  result.get("platform_sig"),
                            })
                    except Exception as e:
                        st.error(f"Erreur: {e}")