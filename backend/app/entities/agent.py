from __future__ import annotations

from sqlalchemy import Column, Float, String, Text

from app.repo.database import Base


class AgentEmbedding(Base):
    """
    Registre minimal — une ligne par agentId.
    registration_status : état transitoire (pending_signature / pending_index / active).
    capability_embedding : vecteur ML calculé après indexation The Graph.
    """
    __tablename__ = "agent_embeddings"

    agent_id             = Column(String, primary_key=True)
    registration_status  = Column(String, nullable=False, default="active")
    capability_embedding = Column(Text, nullable=True)


class AgentTelemetry(Base):
    """
    Métriques runtime sandbox — les seules qui ne peuvent pas venir d'ailleurs.
    avg_response_time : mesuré par le proxy en ms (pas on-chain).
    """
    __tablename__ = "agent_telemetry"

    agent_id          = Column(String, primary_key=True)
    avg_response_time = Column(Float, nullable=True)
