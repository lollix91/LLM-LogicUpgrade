import os
import re
import httpx

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
OPENROUTER_URL = "https://openrouter.ai/api/v1"

# Mutable runtime state
_backend: str = "openrouter" if os.getenv("OPENROUTER_API_KEY") else "ollama"
_api_key: str = os.getenv("OPENROUTER_API_KEY", "")
_current_model: str = (
    os.getenv("OPENROUTER_MODEL", "qwen/qwen3.5-9b")
    if _backend == "openrouter"
    else os.getenv("OLLAMA_MODEL", "qwen3.5:9b")
)

_THINK_RE = re.compile(r"<think>.*?</think>\s*", re.DOTALL)


def get_backend() -> str:
    return _backend


def set_backend(backend: str):
    global _backend, _current_model
    if backend not in ("ollama", "openrouter"):
        raise ValueError(f"Unknown backend: {backend}")
    _backend = backend
    if backend == "ollama":
        _current_model = os.getenv("OLLAMA_MODEL", "qwen3.5:9b")
    else:
        _current_model = os.getenv("OPENROUTER_MODEL", "qwen/qwen3.5-9b")


def get_api_key() -> str:
    return _api_key


def set_api_key(key: str):
    global _api_key
    _api_key = key


def get_model() -> str:
    return _current_model


def set_model(model: str):
    global _current_model
    _current_model = model


async def chat(
    messages: list[dict],
    temperature: float = 0.7,
    max_tokens: int | None = None,
    think: bool = True,
) -> str:
    if _backend == "openrouter":
        return await _chat_openrouter(messages, temperature, max_tokens, think)
    return await _chat_ollama(messages, temperature, max_tokens, think)


async def _chat_openrouter(
    messages: list[dict],
    temperature: float,
    max_tokens: int | None,
    think: bool = True,
) -> str:
    payload = {
        "model": _current_model,
        "messages": messages,
        "temperature": temperature,
    }
    if max_tokens is not None:
        payload["max_tokens"] = max_tokens

    is_qwen = "qwen" in _current_model.lower()

    if not think:
        if is_qwen:
            payload["reasoning"] = {"effort": "none", "enabled": False}
            payload["provider"] = {
                "order": ["Together", "DeepInfra", "Venice"],
                "allow_fallbacks": True,
            }
            if messages and messages[0]["role"] == "system":
                messages = list(messages)
                messages[0] = {
                    "role": "system",
                    "content": messages[0]["content"] + "\n\n/no_think"
                }

    headers = {
        "Authorization": f"Bearer {_api_key}",
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
        if response.status_code != 200:
            err_body = response.text[:500]
            print(f"[ERROR] OpenRouter {response.status_code}: {err_body}", flush=True)
        response.raise_for_status()
        data = response.json()
        msg = data["choices"][0]["message"]
        content = msg.get("content") or ""
        if not content:
            reasoning = msg.get("reasoning_content") or msg.get("reasoning") or ""
            if reasoning:
                content = reasoning
        content = _THINK_RE.sub("", content).strip()
        return content


async def _chat_ollama(
    messages: list[dict],
    temperature: float,
    max_tokens: int | None,
    think: bool,
) -> str:
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
        content = _THINK_RE.sub("", content).strip()
        return content


async def list_models() -> list[str]:
    """List available models for the current backend."""
    if _backend == "openrouter":
        return await _list_openrouter_models()
    return await _list_ollama_models()


async def _list_ollama_models() -> list[str]:
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(f"{OLLAMA_URL}/api/tags")
            response.raise_for_status()
            data = response.json()
            return [m["name"] for m in data.get("models", [])]
    except Exception:
        return []


async def _list_openrouter_models() -> list[str]:
    if not _api_key:
        return [_current_model]
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(
            f"{OPENROUTER_URL}/models",
            headers={"Authorization": f"Bearer {_api_key}"},
        )
        if response.status_code != 200:
            return [_current_model]
        data = response.json()
        models = data.get("data", [])
        return [m["id"] for m in models[:100]]


async def pull_model(model: str) -> bool:
    """Pull a model (Ollama only, no-op for OpenRouter)."""
    if _backend == "openrouter":
        return True
    async with httpx.AsyncClient(timeout=600.0) as client:
        response = await client.post(
            f"{OLLAMA_URL}/api/pull",
            json={"name": model, "stream": False},
        )
        return response.status_code == 200
