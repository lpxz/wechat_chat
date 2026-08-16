# Knowledge: WeChat-like Groq chat

How this app is put together — WebSocket, FastAPI, Uvicorn, Groq streaming.

## The path of one message

```
you type  →  green bubble  →  WebSocket {"type":"user","text":"..."}
                                    ↓
                         FastAPI  WS /ws  (chat_ws)
                                    ↓
                    groq_stream  (httpx, stream=True)
                                    ↓
         {"type":"token"} {"type":"token"} … {"type":"done"}
                                    ↓
                         left bubble grows
```

The calculator used `POST /calc` (one request, one JSON reply). Chat keeps a connection open so the server can push many small `token` frames as the model generates them.

## Who does what

| Piece | Role |
| --- | --- |
| **Uvicorn** | Process that listens on port 8080. Speaks HTTP and WebSockets. Loads `chat_server:app`. |
| **FastAPI** | The app. You write the endpoints. Same `app` can do REST and WebSockets. |
| **ASGI** | Contract between Uvicorn and FastAPI. Async; long-lived connections OK. |
| **Groq** | Inference API (`api.groq.com`). Runs **Meta’s Llama**, not a Groq-trained model. |
| **`llama-3.1-8b-instant`** | The model this app calls. Fast 8B Llama hosted by Groq. |

```bash
uvicorn chat_server:app --port 8080 --reload
```

- `chat_server:app` — import `chat_server.py`, use the `app` object
- `--port 8080` — listen here
- `--reload` — restart on file save (dev only)

Browser talks to Uvicorn → Uvicorn hands the connection to FastAPI → FastAPI runs your functions.

## WSGI vs ASGI

**WSGI** (Web Server Gateway Interface): one request, one response. Enough for `POST /calc`. Typical server: Gunicorn.

**ASGI** (Asynchronous Server Gateway Interface): that, plus **streaming** and **WebSockets**. Typical server: Uvicorn.

For simplicity: WSGI = one shot. ASGI = that, plus streaming and WebSockets.

FastAPI is an ASGI app, so one process can serve both:

- **REST / HTTP:** `GET /` returns `chat_ui.html`
- **WebSocket:** `/ws` stays open for chat frames

## Key entry points

### `chat_ui.html`

1. **Open the socket** (the only connection to the server):

```js
const proto = location.protocol === "https:" ? "wss://" : "ws://";
const ws = new WebSocket(proto + location.host + "/ws");
```

2. **`send()`** — Send / Enter. Paint a green bubble, then one JSON frame. Does not wait for Groq.

3. **`ws` `message` handler** — `token` grows `liveBot`; `done` freezes it; `error` is a red system line.

4. **`addRow`** — creates me / bot / sys rows. `liveBot` is the bubble currently being typed.

There is no `POST`. Send writes onto the existing `/ws` connection.

### `chat_server.py`

1. **`GET /`** → `serve_ui()` → `FileResponse("chat_ui.html")`

2. **`@app.websocket("/ws")` → `chat_ws`** — receives every send. `history` is one list per tab; close the tab and it is gone.

3. **`groq_stream`** — raw `httpx` POST to `https://api.groq.com/openai/v1/chat/completions` with `stream: True`. Groq replies in SSE lines (`data: {...}`). Each `delta.content` is `yield`ed as a token.

4. **The loop** — receive user → append to history → stream tokens over the socket → `done`. On failure, send `error` and drop that user turn from history.

If you only read four things: `send()` → `chat_ws` → `groq_stream` → the `message` listener.

## WebSocket

A WebSocket is not a visible element. A button is a DOM node you can see and click. `ws` is a JavaScript object: a pipe to the server. Same `addEventListener` pattern, no physical appearance.

```js
sendBtn.addEventListener("click", send);          // user clicked Send
ws.addEventListener("message", (ev) => { ... });  // server sent data
```

`new WebSocket(...)` runs when the parser hits the `<script>` at the bottom of `<body>` — during HTML parsing (`document.readyState === "loading"`), not `onload`. Elements above the script (`#log`, `#input`, `#send`) already exist.

### Standard events (exactly four)

These are the WebSocket API, not something this page invented:

| Event | When |
| --- | --- |
| `"open"` | Connected and ready to `send()` |
| `"message"` | The other side sent data (`ev.data`) |
| `"error"` | The **pipe** failed (details usually arrive on `"close"`) |
| `"close"` | Connection ended (`ev.code`, `ev.reason`, `ev.wasClean`) |

This page listens to `"message"` and `"close"`. `"open"` and `"error"` exist but are unused.

There is no `"send"` event. Browser WebSockets also do not expose ping/pong as events.

### `send` is an API call, not an event

Events notify you of things that happen *to* you. Outbound data is something **you** do, so it is a method:

```js
ws.send(JSON.stringify({ type: "user", text }));
```

That queues JSON on the socket. Nothing fires because of it. You already know you called it.

Same idea as the button: `sendBtn.click()` is a method you trigger; `"click"` is an event the user triggers.

### Two layers of "error"

The `"message"` handler also branches on `msg.type === "error"`. That is **not** the WebSocket `"error"` event. It is JSON *inside* a normal `"message"`.

| Layer | What | Meaning |
| --- | --- | --- |
| Transport | `"error"` / `"close"` events | The **pipe** broke |
| App protocol | `{"type":"error","text":"..."}` | The pipe is fine; **Groq failed** |

If Groq throws, the server still uses the open socket:

```python
await ws.send_text(json.dumps({"type": "error", "text": str(e)}))
```

The browser gets a `"message"`; the handler shows a red sys row. If the socket itself died, there is no such JSON — the `"close"` listener shows "Disconnected from server".

### Protocol

Client → server:

```json
{"type": "user", "text": "hello"}
```

Server → client:

```json
{"type": "token", "text": "Hi"}
{"type": "token", "text": " there"}
{"type": "done"}
```

On failure:

```json
{"type": "error", "text": "..."}
```

Empty text is ignored. Unknown types are ignored.

### Server: `await ws.receive_text()`

`chat_ws` starts when the browser runs `new WebSocket(... + "/ws")`. FastAPI calls `chat_ws(ws)` and passes **this tab's** connection as `ws`. The name `ws` is not magic; the association is that the coroutine awaits methods on that object.

```python
await ws.accept()                 # handshake; browser then gets "open"
raw = await ws.receive_text()     # park until the next inbound text (or disconnect)
```

The `while True` **does** start right after `accept()`. It stops at `receive_text()`. On connect, nothing after that `await` runs yet. The coroutine is idle, waiting.

`await` suspends this coroutine; the thread is free for other connections. When bytes arrive, the **event loop** (Uvicorn / asyncio) resumes it — not the OS calling your function directly.

What that `await` waits for: **the next incoming text frame on this connection**, or a disconnect. It is not a general “`ws` state changed” wait. `"open"` already happened (`accept()`). `send_text()` does not wake it.

There is no `"receive_text"` event. Browser incoming data is `addEventListener("message", ...)`. Server incoming data is a **call that waits**: `await ws.receive_text()`. Same fact (“text arrived”), different style. You pull the next message.

The scheduler never hears the name `receive_text`. That function is a translation layer: app “next text please” down to a wait the runtime already understands.

```
await ws.receive_text()          # app (FastAPI): next text on this ws
        ↓
await asgi_receive()             # Starlette: next ASGI message
        ↓
await queue.get()                # Uvicorn: this connection's queue
        ↓
Future / “fd 17 is readable”     # asyncio + kqueue (macOS)
```

Each tab is its own chain: this coroutine → this `ws` → this TCP socket (a file descriptor). The loop keeps a table like fd 17 → connection A, fd 23 → connection B. `history` is just a list; it has no socket.

The kernel does **not** register “data only, ignore close.” It usually watches the socket for **readable**, which covers both “data arrived” and “peer closed.” Uvicorn interprets the bytes:

- text frame → `receive_text()` returns the string
- disconnect → the same `await` raises `WebSocketDisconnect`

### Separation of duties

| Layer | Sees | Does |
| --- | --- | --- |
| Kernel | bytes on a socket (readable) | Wakes the event loop |
| Uvicorn | WebSocket frames → ASGI (`websocket.receive` / `websocket.disconnect`) | Fills this connection's queue |
| FastAPI `receive_text()` | ASGI message | Return text, or raise `WebSocketDisconnect` |
| `chat_ws` | chat JSON (`type: user`) | History, Groq, `token` / `done` / `error` frames |

The kernel never sees WebSocket or `receive_text`. Your code never sees kqueue. Each layer only sees its own.

## Groq vs Grok

No connection. The names just look alike.

- **Groq** — Groq, Inc. Fast inference chips + API. This app uses it.
- **Grok** — xAI’s chatbot/model. Not used here.

Groq hosts other people’s models. This app uses Meta’s Llama, not Grok, and not a Groq-trained LLM.

## API key and limits

The key lives in `~/.env` as `GROQ_API_KEY=...` (or a local `.env`). The server loads it; the browser never sees it. **Never commit `.env` or the key.** `.gitignore` blocks `.env` and `**/.env`. Only `.env.example` (empty value) is in git.

Free ≠ unlimited. Free ≠ safe to publish. The key is the meter. Limits are per **account**, not per extra key.

For `llama-3.1-8b-instant` on Groq’s free plan (check the console; numbers move):

| Limit | Amount |
| --- | --- |
| Requests per minute | 30 |
| Requests per day | 14,400 |
| Tokens per minute | 6,000 |
| Tokens per day | 500,000 |

Each chat send is one request. 30/min is a lot for one person typing; it is small if many users share one key. Over the cap, Groq returns **429** and the UI shows a red error line.

Live quota: https://console.groq.com/settings/limits  
Docs: https://console.groq.com/docs/rate-limits  
Free key: https://console.groq.com/keys

## Why a follow-up remembers the first message

After a successful reply, the server appends `{role: assistant, content: full text}` to that socket’s `history`. The next Groq call sends the whole list (plus a short system prompt), capped at 20 turns (40 messages, pairs kept aligned). A failed call pops the last user message so a broken turn is not kept.

## Files

| File | Role |
| --- | --- |
| `chat_ui.html` | WeChat-like window + WebSocket client |
| `chat_server.py` | FastAPI: `GET /`, `/ws`, Groq stream, in-memory history |
| `requirements.txt` | fastapi, uvicorn, websockets, httpx, python-dotenv |
| `.env.example` | `GROQ_API_KEY=` (empty; safe to commit) |
| `README.md` | How to run |
