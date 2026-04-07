from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st
from components.wallet import connect_wallet
from components.seller_form import render_seller_form
from utils.api import get_agents_by_owner
from utils.blockchain import get_stake_amount, is_eligible_provider

st.set_page_config(
    page_title="AgentMarket — Seller",
    page_icon="🏪",
    layout="wide"
)

st.title("🏪 AgentMarket — Seller Dashboard")
st.caption("Enregistrez et gérez vos agents IA")
st.divider()

wallet = connect_wallet(role="seller")

if not wallet:
    st.info("👆 Connectez votre wallet pour commencer")
    st.stop()

# ── Wallet info ───────────────────────────────────────────────────────────────
col1, col2, col3 = st.columns(3)
col1.metric("Wallet",   f"{wallet['address'][:6]}...{wallet['address'][-4:]}")
col2.metric("Balance",  f"{wallet['balance_eth']} ETH")

stake = get_stake_amount(wallet["address"])
col3.metric("Stake",    f"{stake} ETH")

eligible = is_eligible_provider(wallet["address"])
if eligible:
    st.success("✅ Provider éligible — stake suffisant")
elif stake > 0:
    st.warning(f"⚠️ Stake insuffisant ({stake} ETH) — minimum 0.1 ETH requis")
else:
    st.info("ℹ️ Aucun stake — vous devrez staker lors de l'enregistrement")

st.divider()

tab1, tab2 = st.tabs(["➕ Nouvel Agent", "📋 Mes Agents"])

with tab1:
    render_seller_form(
        owner_address=wallet["address"],
        private_key=wallet["private_key"],
    )

with tab2:
    st.markdown("## 📋 Mes Agents")
    agents = get_agents_by_owner(wallet["address"])

    if not agents:
        st.info("Aucun agent enregistré pour ce wallet")
    else:
        for agent in agents:
            rf      = agent.get("registration_file") or {}
            pricing = rf.get("pricing") or {}
            with st.container(border=True):
                col1, col2, col3, col4 = st.columns([3, 1, 1, 1])
                col1.markdown(f"**{agent.get('name', agent['agent_id'])}**")
                col1.caption(
                    f"`{agent['agent_id']}` · v{agent.get('version', '1.0.0')}"
                )
                col2.metric("Token ID", agent.get("current_token_id", "—"))
                col3.metric("Status",   agent.get("status", "—"))
                col4.metric("Prix",     f"${pricing.get('price_per_task', 0)} USDC")
                st.caption(f"🐳 `{agent.get('docker_image', '—')}`")
                st.caption(f"🔗 `{agent.get('platform_endpoint', '—')}`")