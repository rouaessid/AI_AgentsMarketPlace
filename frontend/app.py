from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

import streamlit as st

st.set_page_config(
    page_title="AgentMarket",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.title("🤖 AgentMarket")
st.markdown("""
## Marketplace décentralisée d'agents IA

Bienvenue sur AgentMarket.

---

### Navigation

- **🏪 Seller** → Enregistrez vos agents IA
- **🛒 Marketplace** → Découvrez et utilisez des agents
""")

col1, col2 = st.columns(2)
with col1:
    st.page_link("pages/1_seller.py", label="🏪 Seller Dashboard", icon="🏪")
with col2:
    st.page_link("pages/2_marketplace.py", label="🛒 Marketplace Buyer", icon="🛒")