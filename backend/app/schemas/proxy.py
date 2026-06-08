from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ApiCall:
    seq:               int
    tool:              str
    tool_category:     str
    url:               str
    method:            str
    status:            int
    latency_ms:        float
    timestamp:         str
    tokens_prompt:     int   = 0
    tokens_completion: int   = 0
    tokens_total:      int   = 0
    cost_usd:          float = 0.0
    error:             str  | None = None
    request_messages:  list | None = None
    request_query:     str  | None = None
    response_content:  str  | None = None
    response_results:  int  | None = None

    def to_dict(self) -> dict:
        return {
            "seq":               self.seq,
            "tool":              self.tool,
            "tool_category":     self.tool_category,
            "url":               self.url,
            "method":            self.method,
            "status":            self.status,
            "latency_ms":        round(self.latency_ms, 1),
            "timestamp":         self.timestamp,
            "tokens_prompt":     self.tokens_prompt,
            "tokens_completion": self.tokens_completion,
            "tokens_total":      self.tokens_total,
            "cost_usd":          round(self.cost_usd, 8),
            "error":             self.error,
            "request_messages":  self.request_messages,
            "request_query":     self.request_query,
            "response_content":  self.response_content,
            "response_results":  self.response_results,
        }


@dataclass
class ProxyTrace:
    run_id:           str
    agent_id:         str
    started_at:       str
    finished_at:      str   = ""
    total_tokens:     int   = 0
    total_cost_usd:   float = 0.0
    total_latency_ms: float = 0.0
    errors_count:     int   = 0
    tools_used:       list  = field(default_factory=list)
    categories_used:  list  = field(default_factory=list)
    llm_calls:        int   = 0
    search_calls:     int   = 0
    calls:            list  = field(default_factory=list)
    proxy_hash:       str   = ""

    def to_dict(self) -> dict:
        return {
            "run_id":           self.run_id,
            "agent_id":         self.agent_id,
            "started_at":       self.started_at,
            "finished_at":      self.finished_at,
            "total_tokens":     self.total_tokens,
            "total_cost_usd":   round(self.total_cost_usd, 6),
            "total_latency_ms": round(self.total_latency_ms, 1),
            "errors_count":     self.errors_count,
            "tools_used":       self.tools_used,
            "categories_used":  self.categories_used,
            "llm_calls":        self.llm_calls,
            "search_calls":     self.search_calls,
            "trajectory":       [c.to_dict() for c in self.calls],
            "proxy_hash":       self.proxy_hash,
        }
