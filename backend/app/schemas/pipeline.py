from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


@dataclass
class SubTask:
    id:          str
    domain:      str
    description: str
    depends_on:  list[str] = field(default_factory=list)
    output_type: str = "text"


@dataclass
class TaskPlan:
    mode:            Literal["solo", "pipeline"]
    subtasks:        list[SubTask]
    reasoning:       str
    pack_name:       str = ""
    pack_rationale:  str = ""


@dataclass
class PipelineStep:
    subtask_id:   str
    agent_id:     str
    input_prompt: str
    output:       str
    status:       str          # "success" | "failed" | "timeout"
    duration_sec: float = 0.0
    error:        str | None = None
    proxy_cid:    str | None = None


@dataclass
class PipelineResult:
    task_id:      str
    steps:        list[PipelineStep]
    final_output: str
    status:       str          # "success" | "partial" | "failed"
    proxy_cid:    str | None = None
