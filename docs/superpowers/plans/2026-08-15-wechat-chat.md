# WeChat-like Groq Chat Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a WeChat-like chat page whose messages travel over a WebSocket; the server streams Groq tokens back into a live bot bubble.

**Architecture:** FastAPI serves `chat_ui.html` at `GET /` and a `/ws` socket. Each connection keeps a short in-memory history. On `{"type":"user","text":"..."}` the server calls Groq (`stream=True`) over `httpx` and forwards each delta as `{"type":"token","text":"..."}`, then `{"type":"done"}`.

**Tech Stack:** Python 3.9+, FastAPI, Uvicorn, httpx, python-dotenv, Groq Chat Completions (`llama-3.1-8b-instant`).

**Spec:** `docs/superpowers/specs/2026-08-15-wechat-chat-design.md`

## Global Constraints

- Manual testing only — no pytest, no mock Groq suite
- Never commit `.env` or `GROQ_API_KEY`
- WebSocket types only: client `user`; server `token`, `done`, `error`
- Model pinned: `llama-3.1-8b-instant`
- Groq via raw `httpx` to `https://api.groq.com/openai/v1/chat/completions` (no SDK)
- Session = one WebSocket; last 20 turns (40 messages); reconnect = empty history
- UI: `#ededed` background, `#95ec69` self bubbles, white bot bubbles, header title `Groq`
- Enter sends, Shift+Enter newline; empty send ignored
- Errors are a red system line, not a bot bubble

---

### Task 1: Scaffold project files

**Files:**
- Create: `requirements.txt`
- Create: `.gitignore`
- Create: `.env.example`

**Interfaces:**
- Consumes: nothing
- Produces: installable deps (`fastapi`, `uvicorn`, `httpx`, `python-dotenv`); `.env.example` with `GROQ_API_KEY=`

- [ ] **Step 1: Write `requirements.txt`**

```
fastapi
uvicorn
httpx
python-dotenv
```

- [ ] **Step 2: Write `.gitignore`**

```
venv/
.venv/
.env
__pycache__/
*.pyc
.DS_Store
```

- [ ] **Step 3: Write `.env.example`**

```
GROQ_API_KEY=
```

- [ ] **Step 4: Commit**

```bash
git add requirements.txt .gitignore .env.example
git commit -m "Add chat app scaffold files."
```

---

### Task 2: WeChat-like page and WebSocket client

**Files:**
- Create: `chat_ui.html`

**Interfaces:**
- Consumes: server at `GET /` and `ws://<host>/ws`
- Produces: client that sends `{"type":"user","text": string}` and handles `token` / `done` / `error`

- [ ] **Step 1: Write `chat_ui.html`**

Single file. Requirements to hit:

- Header text exactly `Groq`, background `#ededed`, self bubbles `#95ec69` right-aligned, bot bubbles white left-aligned with a small round avatar
- Composer: `#input` textarea + Send button; Enter sends, Shift+Enter inserts newline
- On send: ignore empty/whitespace; append a right green bubble immediately; send `JSON.stringify({type:"user", text})`
- On first `token` of a reply: create one left bot bubble and keep appending `text` into it; on `done` freeze it (next `token` starts a new bubble)
- On `error`: append a red system line with `text`, do not create a bot bubble
- Connect with `new WebSocket((location.protocol === "https:" ? "wss://" : "ws://") + location.host + "/ws")`

Use this implementation:

```html
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Groq</title>
<style>
  html, body { height: 100%; margin: 0; }
  body {
    font-family: -apple-system, "PingFang SC", "Hiragino Sans GB", sans-serif;
    background: #ededed;
    display: flex;
    justify-content: center;
  }
  .phone {
    width: 420px;
    max-width: 100%;
    height: 100%;
    display: flex;
    flex-direction: column;
    background: #ededed;
    box-shadow: 0 0 0 1px #ddd;
  }
  header {
    background: #2e2e2e;
    color: #fff;
    text-align: center;
    padding: 14px 12px 12px;
    font-size: 17px;
    font-weight: 600;
  }
  #log {
    flex: 1;
    overflow-y: auto;
    padding: 12px 10px 8px;
  }
  .row { display: flex; margin: 8px 0; align-items: flex-end; gap: 8px; }
  .row.me { justify-content: flex-end; }
  .row.bot { justify-content: flex-start; }
  .avatar {
    width: 36px; height: 36px; border-radius: 4px;
    background: #3d8bfd; color: #fff;
    display: flex; align-items: center; justify-content: center;
    font-size: 13px; flex-shrink: 0;
  }
  .bubble {
    max-width: 72%;
    padding: 8px 10px;
    border-radius: 4px;
    line-height: 1.45;
    font-size: 15px;
    white-space: pre-wrap;
    word-break: break-word;
  }
  .me .bubble { background: #95ec69; }
  .bot .bubble { background: #fff; }
  .sys {
    text-align: center;
    color: #c00;
    font-size: 12px;
    margin: 8px 0;
  }
  .composer {
    display: flex;
    gap: 8px;
    padding: 8px;
    background: #f7f7f7;
    border-top: 1px solid #ddd;
  }
  #input {
    flex: 1;
    resize: none;
    height: 44px;
    border: 1px solid #ddd;
    border-radius: 4px;
    padding: 8px;
    font: inherit;
  }
  #send {
    background: #07c160;
    color: #fff;
    border: none;
    border-radius: 4px;
    padding: 0 16px;
    font-size: 15px;
    cursor: pointer;
  }
</style>
</head>
<body>
<div class="phone">
  <header>Groq</header>
  <div id="log"></div>
  <div class="composer">
    <textarea id="input" placeholder="Type a message"></textarea>
    <button id="send" type="button">Send</button>
  </div>
</div>
<script>
  const logEl = document.getElementById("log");
  const input = document.getElementById("input");
  const sendBtn = document.getElementById("send");
  const proto = location.protocol === "https:" ? "wss://" : "ws://";
  const ws = new WebSocket(proto + location.host + "/ws");

  let liveBot = null;

  function addRow(kind, text) {
    if (kind === "sys") {
      const div = document.createElement("div");
      div.className = "sys";
      div.textContent = text;
      logEl.appendChild(div);
      logEl.scrollTop = logEl.scrollHeight;
      return null;
    }
    const row = document.createElement("div");
    row.className = "row " + kind;
    if (kind === "bot") {
      const av = document.createElement("div");
      av.className = "avatar";
      av.textContent = "G";
      row.appendChild(av);
    }
    const bubble = document.createElement("div");
    bubble.className = "bubble";
    bubble.textContent = text;
    row.appendChild(bubble);
    logEl.appendChild(row);
    logEl.scrollTop = logEl.scrollHeight;
    return bubble;
  }

  function send() {
    const text = input.value.trim();
    if (!text) return;
    input.value = "";
    addRow("me", text);
    liveBot = null;
    ws.send(JSON.stringify({ type: "user", text }));
  }

  sendBtn.addEventListener("click", send);
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      send();
    }
  });

  ws.addEventListener("message", (ev) => {
    let msg;
    try { msg = JSON.parse(ev.data); } catch { return; }
    if (msg.type === "token") {
      if (!liveBot) liveBot = addRow("bot", "");
      liveBot.textContent += msg.text || "";
      logEl.scrollTop = logEl.scrollHeight;
    } else if (msg.type === "done") {
      liveBot = null;
    } else if (msg.type === "error") {
      liveBot = null;
      addRow("sys", msg.text || "error");
    }
  });

  ws.addEventListener("close", () => addRow("sys", "Disconnected from server"));
</script>
</body>
</html>
```

- [ ] **Step 2: Commit**

```bash
git add chat_ui.html
git commit -m "Add WeChat-like chat window and WebSocket client."
```

---

### Task 3: FastAPI server, Groq stream, session history

**Files:**
- Create: `chat_server.py`

**Interfaces:**
- Consumes: `chat_ui.html`; env `GROQ_API_KEY`; client frames `{type:"user", text:str}`
- Produces:
  - `GET /` → `FileResponse("chat_ui.html")`
  - `WS /ws` → `{type:"token", text:str}` | `{type:"done"}` | `{type:"error", text:str}`
  - `async def groq_stream(messages: list[dict]) -> AsyncIterator[str]`
  - History: `list[dict]` with `role`/`content`, trimmed to last 40 messages (20 turns)

- [ ] **Step 1: Write `chat_server.py`**

```python
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
```

- [ ] **Step 2: Manual check — page loads**

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
uvicorn chat_server:app --port 8080 --reload
```

Open http://localhost:8080 — WeChat-like window, header `Groq`, composer at the bottom.

- [ ] **Step 3: Manual check — live Groq stream**

Put a real key in `.env` as `GROQ_API_KEY=...` (file is gitignored). Restart if needed. Send `say hi in three words`. Expect a green self bubble, then a growing left bubble, then it stops. Send a follow-up that refers to the first message; the reply should use session history.

- [ ] **Step 4: Manual check — missing key**

Temporarily unset the key, send a message, expect a red system line mentioning `GROQ_API_KEY`, not a bot bubble.

- [ ] **Step 5: Commit**

```bash
git add chat_server.py
git commit -m "Add WebSocket server that streams Groq tokens."
```

Do not `git add .env`.

---

### Task 4: README

**Files:**
- Create: `README.md`

**Interfaces:**
- Consumes: run commands and protocol from Tasks 2–3
- Produces: how to run and how to test by hand

- [ ] **Step 1: Write `README.md`**

```markdown
# WeChat-like Groq Chat

A WeChat-style chat window. Each send goes over a **WebSocket**. The server calls **Groq** and streams tokens back into a live bot bubble.

## Requirements

- Python 3.9+
- A free Groq API key from https://console.groq.com

## Run

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# edit .env and set GROQ_API_KEY
uvicorn chat_server:app --port 8080 --reload
```

Open http://localhost:8080

## Try

1. Send a short message — green bubble on the right, then a growing white bubble on the left.
2. Send a follow-up that refers to the first message — the model should remember this tab’s session.
3. If `GROQ_API_KEY` is missing, a red system line appears instead of a bot reply.

## Protocol

Client → server: `{"type":"user","text":"..."}`

Server → client: `{"type":"token","text":"..."}` then `{"type":"done"}`, or `{"type":"error","text":"..."}`.
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "Add run and manual test instructions."
```

---

## Spec coverage

| Spec item | Task |
| --- | --- |
| FastAPI + one HTML page | 2, 3 |
| `GET /` and `/ws` | 3 |
| Raw httpx Groq stream, `llama-3.1-8b-instant` | 3 |
| Session history, 20 turns, reconnect clears | 3 |
| WeChat colors / header `Groq` / Enter vs Shift+Enter | 2 |
| `user` / `token` / `done` / `error` only | 2, 3 |
| Empty send ignored | 2, 3 |
| Missing key / Groq failure → red system line | 2, 3 |
| Manual testing, README | 3, 4 |
| `.env` not committed | 1, 3 |
