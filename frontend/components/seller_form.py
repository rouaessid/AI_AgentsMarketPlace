from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st
from utils.api import register_agent, confirm_agent
from utils.blockchain import sign_and_send


def render_seller_form(owner_address: str, private_key: str) -> None:
    st.markdown("## 📝 Enregistrer un nouvel agent")

    with st.form("register_form"):
        st.markdown("### Identité")
        col1, col2 = st.columns(2)
        agent_id = col1.text_input(
            "Agent ID *", placeholder="ex: search-1",
            help="Identifiant unique, minuscules et tirets"
        )
        name = col2.text_input("Nom *", placeholder="ex: Search Agent Pro")

        description = st.text_area(
            "Description *",
            placeholder="Décrivez ce que fait votre agent...",
            height=100
        )

        readme = st.text_area(
            "README (Markdown)",
            placeholder="## Mon Agent\n\n### Utilisation\n...",
            height=200
        )

        st.markdown("### Docker")
        col1, col2 = st.columns(2)
        docker_image = col1.text_input(
            "Image Docker *", placeholder="ex: username/agent:v1"
        )
        version = col2.text_input("Version", value="1.0.0")

        env_var_keys_raw = st.text_input(
            "Clés API requises",
            placeholder="GROQ_API_KEY, TAVILY_API_KEY",
        )

        st.markdown("### Capacités")
        col1, col2, col3 = st.columns(3)
        llm_model    = col1.selectbox("Modèle LLM", ["llama-3.3-70b", "gpt-4o", "claude-3-5-sonnet"])
        cpu_limit    = col2.number_input("CPU limit", 1, 8, 1)
        ram_limit_mb = col3.number_input("RAM (MB)", 128, 8192, 512)
        timeout_sec  = st.slider("Timeout (sec)", 10, 600, 120)

        st.markdown("### Pricing")
        col1, col2, col3 = st.columns(3)
        price_per_task       = col1.number_input("Prix / tâche (USDC)", 0.0, 100.0, 0.10)
        access_duration_days = col2.number_input("Durée accès (jours)", 1, 365, 30)
        max_calls_per_day    = col3.number_input("Appels max / jour", 1, 10000, 100)
        stake_amount         = st.number_input("Stake (ETH)", 0.0, 100.0, 0.5)

        submitted = st.form_submit_button("🚀 Enregistrer l'agent", type="primary")

    if submitted:
        errors = []
        if not agent_id:     errors.append("Agent ID requis")
        if not name:         errors.append("Nom requis")
        if not description:  errors.append("Description requise")
        if not docker_image: errors.append("Image Docker requise")

        if errors:
            for e in errors:
                st.error(e)
            return

        env_var_keys = [k.strip() for k in env_var_keys_raw.split(",") if k.strip()]

        with st.status("Enregistrement en cours...", expanded=True) as status:
            try:
                st.write("📤 Envoi au backend...")
                reg_data = register_agent({
                    "agent_id":            agent_id,
                    "name":                name,
                    "description":         description,
                    "version":             version,
                    "agent_type":          "provider",
                    "owner_address":       owner_address,
                    "readme":              readme,
                    "docker_image":        docker_image,
                    "env_var_keys":        env_var_keys,
                    "llm_model":           llm_model,
                    "framework":           "raw_api",
                    "language":            "python",
                    "supported_tasks":     [],
                    "price_per_task":      price_per_task,
                    "access_duration_days": int(access_duration_days),
                    "max_calls_per_day":   int(max_calls_per_day),
                    "stake_amount":        stake_amount,
                    "cpu_limit":           int(cpu_limit),
                    "ram_limit_mb":        int(ram_limit_mb),
                    "timeout_sec":         int(timeout_sec),
                })

                registration_id = reg_data["registration_id"]
                agent_uri       = reg_data["agent_uri"]
                st.write(f"✅ registration_id: `{registration_id[:16]}...`")

                st.write("🔐 Signature de la transaction...")
                tx_hash, token_id = sign_and_send(
                    private_key=private_key,
                    agent_id=agent_id,
                    agent_type=0,
                    agent_uri=agent_uri,
                    version=version,
                )
                st.write(f"✅ tx_hash: `{tx_hash[:20]}...`")
                st.write(f"✅ tokenId: `{token_id}`")

                st.write("📋 Confirmation on-chain...")
                confirmed = confirm_agent(registration_id, tx_hash, token_id)

                status.update(label="✅ Agent enregistré !", state="complete")
                st.success(f"Agent **{name}** enregistré avec succès !")

                col1, col2 = st.columns(2)
                col1.metric("Token ID", token_id)
                col2.metric("Status", confirmed.get("status", "active"))
                st.code(confirmed.get("docker_image", ""), language="text")
                st.info(f"🔗 Endpoint: `{confirmed.get('platform_endpoint', '')}`")

            except Exception as e:
                status.update(label="❌ Erreur", state="error")
                st.error(f"Erreur: {e}")