from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st


def render_agent_card(agent: dict, on_select=None) -> None:
    rf      = agent.get("registration_file") or {}
    pricing = rf.get("pricing") or {}
    caps    = rf.get("capabilities") or {}

    with st.container(border=True):
        col1, col2 = st.columns([3, 1])

        with col1:
            st.markdown(f"### 🤖 {agent.get('name', agent['agent_id'])}")
            st.caption(f"v{agent.get('version', '1.0.0')} · {agent['agent_id']}")
            desc = rf.get("description") or agent.get("name", "")
            st.markdown(desc[:150] + "..." if len(desc) > 150 else desc)
            tasks = caps.get("supported_tasks", [])
            if tasks:
                st.markdown(" ".join([f"`{t}`" for t in tasks]))

        with col2:
            price = pricing.get("price_per_task", 0)
            st.metric("Prix", f"${price} USDC")
            st.caption(f"/{pricing.get('access_duration_days', 30)} jours")
            if on_select:
                if st.button(
                    "🛒 Accéder",
                    key=f"select_{agent['agent_id']}",
                    use_container_width=True,
                ):
                    on_select(agent["agent_id"])