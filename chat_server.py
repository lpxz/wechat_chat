"""
chat_server.py — WeChat-like chat over WebSocket, replies streamed from Groq.

  GET /    → chat_ui.html
  WS  /ws  → {"type":"user","text":"..."}
             ← {"type":"token","text":"..."}*  {"type":"done"}
             ← {"type":"error","text":"..."}
"""

import json
import os
from typing import AsyncIterator, List

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse

load_dotenv()

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "llama-3.1-8b-instant"
MAX_MESSAGES = 40  # 20 turns
SYSTEM = {"role": "system", "content": "You are a friendly chat assistant. Keep replies concise."}

app = FastAPI()


@app.get("/")
async def serve_ui():
    return FileResponse("chat_ui.html")


async def groq_stream(messages: List[dict]) -> AsyncIterator[str]:
    api_key = os.environ.get("GROQ_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("GROQ_API_KEY is not set")

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": GROQ_MODEL,
        "messages": [SYSTEM, *messages],
        "stream": True,
    }

    async with httpx.AsyncClient(timeout=60.0) as client:
        async with client.stream("POST", GROQ_URL, headers=headers, json=payload) as resp:
            if resp.status_code != 200:
                body = (await resp.aread()).decode("utf-8", errors="replace")
                raise RuntimeError(f"Groq request failed: {resp.status_code} {body[:300]}")
            async for line in resp.aiter_lines():
                if not line.startswith("data: "):
                    continue
                data = line[6:].strip()
                if data == "[DONE]":
                    break
                chunk = json.loads(data)
                delta = chunk["choices"][0].get("delta") or {}
                text = delta.get("content") or ""
                if text:
                    yield text


@app.websocket("/ws")
async def chat_ws(ws: WebSocket):
    await ws.accept()
    history: List[dict] = []
    try:
        while True:
            raw = await ws.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if msg.get("type") != "user":
                continue
            text = (msg.get("text") or "").strip()
            if not text:
                continue

            history.append({"role": "user", "content": text})
            history[:] = history[-MAX_MESSAGES:]

            collected = []
            try:
                async for token in groq_stream(history):
                    collected.append(token)
                    await ws.send_text(json.dumps({"type": "token", "text": token}))
                await ws.send_text(json.dumps({"type": "done"}))
            except Exception as e:
                await ws.send_text(json.dumps({"type": "error", "text": str(e)}))
                if history and history[-1]["role"] == "user":
                    history.pop()
                continue

            history.append({"role": "assistant", "content": "".join(collected)})
            history[:] = history[-MAX_MESSAGES:]
    except WebSocketDisconnect:
        return
