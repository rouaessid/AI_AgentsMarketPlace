from __future__ import annotations

from dataclasses import dataclass


@dataclass
class AgentMatch:
    subtask_id:   str
    agent_id:     str
    cosine_score: float
    trust_score:  float
    final_score:  float
