import os
import re
import httpx

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_URL = "https://openrouter.ai/api/v1"
OPENROUTER_DEFAULT_MODEL = "qwen/qwen3.5-9b"

_current_model = os.getenv("OLLAMA_MODEL", "qwen3.5:9b")
if OPENROUTER_API_KEY:
    _current_model = os.getenv("OPENROUTER_MODEL") or OPENROUTER_DEFAULT_MODEL

# Safety regex to strip <think> blocks that may leak into content
_THINK_RE = re.compile(r"<think>.*?</think>\s*", re.DOTALL)


def _using_openrouter() -> bool:
    return bool(OPENROUTER_API_KEY)


def get_model() -> str:
    return _current_model


def get_backend() -> str:
    return "openrouter" if _using_openrouter() else "ollama"


def set_model(model: str):
    global _current_model
    _current_model = model


async def chat(
    messages: list[dict],
    temperature: float = 0.7,
    max_tokens: int | None = None,
    think: bool = True,
) -> str:
    """Send a chat completion request to Ollama or OpenRouter.

    Args:
        think: Enable extended thinking (Qwen3.5). Disable for structured/JSON outputs.
        max_tokens: Max tokens for the response. None = model default.
    """
    if _using_openrouter():
        return await _chat_openrouter(messages, temperature, max_tokens, think)
    return await _chat_ollama(messages, temperature, max_tokens, think)


async def _chat_openrouter(
    messages: list[dict],
    temperature: float,
    max_tokens: int | None,
    think: bool = True,
) -> str:
    """OpenRouter backend (OpenAI-compatible API)."""
    payload = {
        "model": _current_model,
        "messages": messages,
        "temperature": temperature,
    }
    if max_tokens is not None:
        payload["max_tokens"] = max_tokens
    if not think:
        payload["reasoning"] = {"effort": "none", "enabled": False}
        # Route to providers with best latency and structured output support
        payload["provider"] = {
            "order": ["Together", "DeepInfra", "Venice"],
            "allow_fallbacks": True,
        }
        # Instruct model not to think (works even if provider ignores reasoning param)
        if messages and messages[0]["role"] == "system":
            messages = list(messages)
            messages[0] = {
                "role": "system",
                "content": messages[0]["content"] + "\n\n/no_think"
            }

    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/lollix91/LLM-LogicUpgrade",
        "X-Title": "LLM-LogicUpgrade",
    }

    async with httpx.AsyncClient(timeout=300.0) as client:
        response = await client.post(
            f"{OPENROUTER_URL}/chat/completions",
            json=payload,
            headers=headers,
        )
        response.raise_for_status()
        data = response.json()
        msg = data["choices"][0]["message"]
        content = msg.get("content") or ""

        # If content is empty, try to get reasoning content (Qwen3.5 thinking mode)
        if not content:
            reasoning = msg.get("reasoning_content") or msg.get("reasoning") or ""
            if reasoning:
                content = reasoning

        # Safety: strip any <think> blocks that leak into content
        content = _THINK_RE.sub("", content).strip()

        return content


async def _chat_ollama(
    messages: list[dict],
    temperature: float,
    max_tokens: int | None,
    think: bool,
) -> str:
    """Ollama backend (local inference)."""
    payload = {
        "model": _current_model,
        "messages": messages,
        "stream": False,
        "think": think,
        "options": {
            "temperature": temperature,
        },
    }
    if max_tokens is not None:
        payload["options"]["num_predict"] = max_tokens

    async with httpx.AsyncClient(timeout=300.0) as client:
        response = await client.post(
            f"{OLLAMA_URL}/api/chat",
            json=payload,
        )
        response.raise_for_status()
        data = response.json()
        content = data["message"]["content"]

        # Safety: strip any <think> blocks that leak into content
        content = _THINK_RE.sub("", content).strip()

        return content


async def list_models() -> list[str]:
    """List available models."""
    if _using_openrouter():
        return [_current_model]
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(f"{OLLAMA_URL}/api/tags")
        response.raise_for_status()
        data = response.json()
        return [m["name"] for m in data.get("models", [])]


async def pull_model(model: str) -> bool:
    """Pull a model (Ollama only, no-op for OpenRouter)."""
    if _using_openrouter():
        return True
    async with httpx.AsyncClient(timeout=600.0) as client:
        response = await client.post(
            f"{OLLAMA_URL}/api/pull",
            json={"name": model, "stream": False},
        )
        return response.status_code == 200
