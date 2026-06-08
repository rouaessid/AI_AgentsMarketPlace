from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class EigenTrustResult:
    agent_ids:       list[str]
    token_ids:       list[int]
    pre_trust:       list[float]
    global_trust:    list[float]
    final_scores:    list[float]
    user_feedback:   list[float]
    iterations:      int
    converged:       bool
    scores_by_agent: dict[str, dict] = field(default_factory=dict)
