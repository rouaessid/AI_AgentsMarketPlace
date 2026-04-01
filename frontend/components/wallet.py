from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))  # Add project root to path



import streamlit as st
from utils.blockchain import get_hardhat_accounts


def connect_wallet(role: str = "seller") -> dict | None:
    st.markdown("### 🦊 Connecter Wallet")

    accounts = get_hardhat_accounts()
    if not accounts:
        st.error("Hardhat node non disponible — lancer: npx hardhat node")
        return None

    options = {
        f"{a['label']} ({a['balance_eth']} ETH)": a
        for a in accounts
    }

    selected_label = st.selectbox(
        "Sélectionner un compte Hardhat",
        list(options.keys()),
        key=f"wallet_{role}"
    )

    account = options[selected_label]

    if st.button("✅ Connecter ce wallet", key=f"connect_{role}"):
        st.session_state[f"{role}_wallet"] = account
        st.success(f"Wallet connecté : {account['address']}")
        st.rerun()

    return st.session_state.get(f"{role}_wallet")