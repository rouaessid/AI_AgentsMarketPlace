from __future__ import annotations

from pydantic import BaseModel


class FeedbackBody(BaseModel):
    score:   int
    comment: str = ""


class SimulateValidationBody(BaseModel):
    agent_id: str
    score:    int = 80
