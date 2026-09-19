"""本地模型网关: 把 Ollama 封装成 OpenAI 兼容接口对外提供调用。

为什么加这层而不是直接暴露 Ollama:
1. 团队其他业务代码都用 OpenAI SDK, 只改 base_url 就能接入;
2. 可以在这里统一加鉴权、限流、日志, 而不用动模型层。
"""
import sys
import time
import uuid
from pathlib import Path

import httpx
from fastapi import FastAPI
from pydantic import BaseModel

sys.path.append(str(Path(__file__).resolve().parent.parent))
import config

app = FastAPI(title="Local LLM Gateway", version="0.1.0")


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatCompletionRequest(BaseModel):
    model: str | None = None
    messages: list[ChatMessage]
    temperature: float | None = None
    stream: bool = False  # 网关版先只支持非流式


@app.get("/health")
def health():
    try:
        r = httpx.get(f"{config.OLLAMA_URL}/api/version", timeout=5)
        return {"status": "ok", "ollama": r.json()["version"], "model": config.MODEL_NAME}
    except Exception as exc:  # noqa: BLE001
        return {"status": "degraded", "error": str(exc)}


@app.get("/v1/models")
def list_models():
    return {"object": "list", "data": [{"id": config.MODEL_NAME, "object": "model"}]}


@app.post("/v1/chat/completions")
def chat_completions(req: ChatCompletionRequest):
    payload = {
        "model": req.model or config.MODEL_NAME,
        "messages": [m.model_dump() for m in req.messages],
        "stream": False,
        "options": {
            "temperature": req.temperature if req.temperature is not None else config.TEMPERATURE,
            "num_ctx": config.NUM_CTX,
        },
    }
    resp = httpx.post(f"{config.OLLAMA_URL}/api/chat", json=payload, timeout=300)
    resp.raise_for_status()
    data = resp.json()

    return {
        "id": f"chatcmpl-{uuid.uuid4().hex[:12]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": payload["model"],
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": data["message"]["content"]},
            "finish_reason": "stop",
        }],
        "usage": {
            "prompt_tokens": data.get("prompt_eval_count", 0),
            "completion_tokens": data.get("eval_count", 0),
            "total_tokens": data.get("prompt_eval_count", 0) + data.get("eval_count", 0),
        },
    }
