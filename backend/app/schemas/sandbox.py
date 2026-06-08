from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class SandboxInput:
    task_id:     str
    agent_id:    str
    task_prompt: str
    task_params: dict = field(default_factory=dict)
    token_id:    int | None = None


@dataclass
class ExecutionManifest:
    run_id:            str
    registration_id:   str
    agent_id:          str
    token_id:          int | None
    docker_image:      str
    task_id:           str
    exit_code:         int
    output:            Any
    output_raw:        str
    logs:              str
    output_hash:       str
    manifest_hash:     str
    platform_sig:      str
    started_at:        str
    finished_at:       str
    duration_sec:      float
    status:            str
    error:             str | None
    platform_endpoint: str | None = None
    proxy_hash:        str | None = None
    proxy_cid:         str | None = None
    proxy_metrics:     dict | None = None

    def to_dict(self):
        return {
            "run_id":            self.run_id,
            "registration_id":   self.registration_id,
            "agent_id":          self.agent_id,
            "token_id":          self.token_id,
            "docker_image":      self.docker_image,
            "task_id":           self.task_id,
            "exit_code":         self.exit_code,
            "output_hash":       self.output_hash,
            "manifest_hash":     self.manifest_hash,
            "platform_sig":      self.platform_sig,
            "started_at":        self.started_at,
            "finished_at":       self.finished_at,
            "duration_sec":      self.duration_sec,
            "status":            self.status,
            "error":             self.error,
            "platform_endpoint": self.platform_endpoint,
            "logs_preview":      (self.logs or "")[:2000],
            "output":            self.output,
            "output_preview":    str(self.output or "")[:500],
            "proxy_hash":        self.proxy_hash,
            "proxy_cid":         self.proxy_cid,
            "proxy_metrics":     self.proxy_metrics,
        }
