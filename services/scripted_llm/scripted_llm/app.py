"""A deterministic, OpenAI-compatible chat model.

It sits behind the LLM gateway exactly like a real provider, so budgets, rate limits
and spend logs are exercised in CI without an API key. Without tools it echoes a fixed
string; with tools it follows the procurement scenario in scenario.py. Token usage is a
word count so cost attribution is non-zero and predictable.
"""

import json
import time
import uuid
from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel, ConfigDict

from .scenario import next_step

MODEL_ID = "scripted"

app = FastAPI(title="scripted-llm")


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    model: str
    messages: list[dict[str, Any]]
    tools: list[dict[str, Any]] | None = None


def count_tokens(text: str) -> int:
    return max(1, len(text.split()))


def _text(message: dict) -> str:
    content = message.get("content") or ""
    if isinstance(content, list):  # OpenAI content parts
        content = " ".join(part.get("text", "") for part in content if isinstance(part, dict))
    return str(content)


def reply_for(messages: list[dict]) -> str:
    last_user = next((_text(m) for m in reversed(messages) if m.get("role") == "user"), "")
    return f"[scripted] Received {count_tokens(last_user)} words. No real model was called."


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}


@app.get("/v1/models")
def models() -> dict:
    return {"object": "list", "data": [{"id": MODEL_ID, "object": "model", "owned_by": "local"}]}


@app.post("/v1/chat/completions")
def chat_completions(request: ChatRequest) -> dict:
    if request.tools:
        tool_names = {t.get("function", {}).get("name") for t in request.tools}
        message = next_step(request.messages, tool_names)
    else:
        message = {"role": "assistant", "content": reply_for(request.messages)}

    prompt_tokens = sum(count_tokens(_text(m)) for m in request.messages)
    completion_tokens = count_tokens(_text(message) or json.dumps(message.get("tool_calls")))
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": MODEL_ID,
        "choices": [
            {
                "index": 0,
                "message": message,
                "finish_reason": "tool_calls" if message.get("tool_calls") else "stop",
            }
        ],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        },
    }
