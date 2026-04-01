from __future__ import annotations
import streamlit as st
from frontend.components.wallet import connect_wallet
from frontend.components.agent_card import render_agent_card
from frontend.components.agent_detail import render_agent_detail
from frontend.utils.api import get_all_agents

st.set_page_config(
    page_title="AgentMarket — Marketplace",
    page_icon="🛒",
    layout="wide"
)

st.title("🛒 AgentMarket — Marketplace")
st.caption("Découvrez et accédez aux agents IA disponibles")

st.divider()

# ── Connexion wallet buyer ────────────────────────────────────────────────────
wallet = connect_wallet(role="buyer")

if not wallet:
    st.info("👆 Connectez votre wallet pour accéder aux agents")
    st.stop()

st.success(f"🦊 Wallet connecté : `{wallet['address']}`")

st.divider()

# ── Navigation detail ─────────────────────────────────────────────────────────
if "selected_agent" in st.session_state:
    col1, _ = st.columns([1, 5])
    if col1.button("← Retour"):
        del st.session_state["selected_agent"]
        st.rerun()

    render_agent_detail(st.session_state["selected_agent"])
    st.stop()

# ── Marketplace ───────────────────────────────────────────────────────────────
st.markdown("## 🤖 Agents disponibles")

agents = get_all_agents()

if not agents:
    st.info("Aucun agent disponible pour le moment")
else:
    # Filtres
    col1, col2 = st.columns([3, 1])
    search = col1.text_input("🔍 Rechercher", placeholder="nom, description...")

    if search:
        agents = [
            a for a in agents
            if search.lower() in a.get("name", "").lower()
            or search.lower() in (a.get("registration_file") or {})
                                  .get("description", "").lower()
        ]

    # Grille d'agents
    cols = st.columns(2)
    for i, agent in enumerate(agents):
        with cols[i % 2]:
            render_agent_card(
                agent,
                on_select=lambda aid: (
                    st.session_state.update({"selected_agent": aid}),
                    st.rerun()
                )
            )