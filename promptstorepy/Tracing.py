from typing import Any, Dict, List, Optional

from pydantic import BaseModel

from .PromptStore import PromptStore


class PromptTemplateOnStart(BaseModel):
    prompt_set_name: str
    message_templates: List[Any]
    prompt_set_version: Optional[str] = None
    args: Optional[Any] = None
    is_batch: Optional[bool] = False


class PromptTemplateEnd(BaseModel):
    messages: Optional[List[Any]] = None
    errors: Optional[Any] = None


class ModelStart(BaseModel):
    provider: str
    request: Any
    llm_params: Any


class ModelEnd(BaseModel):
    errors: Optional[Any]
    response: Optional[Any]


class AgentStart(BaseModel):
    name: str
    model: str
    provider: str
    args: Optional[Any] = None
    tools: Optional[List[Any]] = None
    extra_function_call_params: Optional[Any] = None
    llm_params: Optional[Any] = None


class Trace:
    ps: PromptStore
    id: str
    span_stack: List[Dict[str, Any]]

    def __init__(self):
        self.ps = PromptStore()
        self.id = self.ps.trace({"event": {"type": "trace"}})
        self.span_stack = []

    def span(self, event: Dict[str, Any]):
        self.ps.trace({"event": event, "id": self.id})
        sp = Span(self, self.ps, event)
        self.span_stack.append(sp)
        return sp

    def pop(self):
        return self.span_stack.pop()


class Span:
    ps: PromptStore
    trace: Trace
    event: Dict[str, Any]

    def __init__(self, trace: Trace, ps: PromptStore, event: Dict[str, Any]):
        self.trace = trace
        self.ps = ps
        self.event = event

    def end(self, event: Dict[str, Any]):
        self.ps.trace({"event": event, "id": self.trace.id})
        self.event = {**self.event, **event}
        return self.trace.pop()

    def span(self, event: Dict[str, Any]):
        return self.trace.span(event)

    def generation(self, event: Dict[str, Any]):
        return self.trace.span(event)
