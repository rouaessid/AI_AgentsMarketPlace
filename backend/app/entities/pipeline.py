from __future__ import annotations

from sqlalchemy import Column, String, Text

from app.repo.database import Base


class PipelineTask(Base):
    """
    Orchestration pipeline — état local uniquement.
    buyer_wallet et tx_hash → on-chain (EscrowManager).
    final_output → IPFS (immuable), seul le CID est stocké ici.
    """
    __tablename__ = "pipeline_tasks"

    id                    = Column(String, primary_key=True)
    task_prompt           = Column(Text,   nullable=False)
    mode                  = Column(String, nullable=False)
    plan_json             = Column(Text,   nullable=True)
    selected_agents_json  = Column(Text,   nullable=True)
    steps_json            = Column(Text,   nullable=True)
    status                = Column(String, nullable=False, default="planning")
    final_output_ipfs_cid = Column(String, nullable=True)
    val_task_id           = Column(String, nullable=True)
    pack_id               = Column(String, nullable=True)
    pack_name             = Column(String, nullable=True)
    buyer_wallet          = Column(String, nullable=True)
    access_granted_at     = Column(String, nullable=True)
    access_expires_at     = Column(String, nullable=True)
    created_at            = Column(String, nullable=False)
    finished_at           = Column(String, nullable=True)
