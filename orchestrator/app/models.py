from typing import Optional
from pydantic import BaseModel


class ChatRequest(BaseModel):
    message: str
    conversation_id: Optional[str] = None
    skip_logic: bool = False


class PipelineStep(BaseModel):
    step: str
    title: str
    content: str
    duration_ms: Optional[float] = None


class ChatResponse(BaseModel):
    conversation_id: str
    answer: str
    has_logic: bool
    reasoning_trace: list[PipelineStep]


class ModelChangeRequest(BaseModel):
    model: str


class ModelInfo(BaseModel):
    current_model: str
    available_models: list[str]
    backend: str = "ollama"
    api_key_set: bool = False


class BackendSwitchRequest(BaseModel):
    backend: str  # "ollama" or "openrouter"


class ApiKeyUpdateRequest(BaseModel):
    api_key: str


class ConversationSummary(BaseModel):
    id: str
    title: str
    created_at: str
    message_count: int


class ConversationDetail(BaseModel):
    id: str
    title: str
    created_at: str
    messages: list[dict]
