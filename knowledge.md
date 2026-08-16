# Knowledge: WeChat-like Groq chat

## Path of one message

```
you type → green bubble → WS {"type":"user","text"}
                              ↓
                    chat_ws  (/ws)
                              ↓
                    groq_stream  (HTTP POST, SSE)
                              ↓
         {"type":"token"}*  {"type":"done"}   or  {"type":"error"}
                              ↓
                    left bubble grows
```

Calculator: `POST /calc` (one request, one reply). Chat: one open `/ws` so the server can push many `token` frames.

**Four things:** `send()` → `chat_ws` → `groq_stream` → the `message` listener.

## Who does what

| Piece | Role |
| --- | --- |
| **Uvicorn** | Process on port 8080. HTTP + WebSockets. Loads `chat_server:app`. |
| **FastAPI** | Your endpoints. REST and WebSockets on the same `app`. |
| **ASGI** | Contract between them. Async; long-lived connections OK. (WSGI = one shot.) |
| **Groq** | Inference API. Hosts **Meta’s Llama**, not a Groq-trained model. |
| **`llama-3.1-8b-instant`** | The model this app calls. |

```bash
uvicorn chat_server:app --port 8080 --reload
```

`chat_server:app` is **module:variable**, not a `main()`. Uvicorn **imports** `chat_server` (`chat_server.py`) — top-level code runs, `app = FastAPI(...)` is built, `@app.get` / `@app.websocket` register on it — then serves **that object**. Not `python chat_server.py`; there is no `__main__`. Rename the variable to `server` and the command would be `uvicorn chat_server:server`.

`GET /` → `chat_ui.html`. `/ws` stays open for chat.

## Entry points

**`chat_ui.html`** — script at end of `<body>` runs during parse (`readyState === "loading"`), not `onload`.

```js
const ws = new WebSocket((https ? "wss://" : "ws://") + location.host + "/ws");
```

- `send()` — green bubble, then `ws.send({type:"user", text})`. Does not wait for Groq.
- `"message"` — `token` grows `liveBot`; `done` freezes it; `error` is a red sys line.
- `addRow` — me / bot / sys. No `POST`; send writes on the existing `/ws`.

**`chat_server.py`**

- `GET /` → `FileResponse("chat_ui.html")`
- `chat_ws` — one coroutine + `history` per tab
- `groq_stream` — httpx POST, `stream: True`; `yield`s `delta.content` strings
- Loop: receive user → history → stream `token`s → `done`. On failure: `error`, drop that user turn.

## WebSocket

`ws` is a JS object (a pipe), not a DOM node. Same `addEventListener` pattern as a button; no appearance.

```js
sendBtn.addEventListener("click", send);          // user clicked Send
ws.addEventListener("message", (ev) => { ... });  // server sent data
ws.send(JSON.stringify({ type: "user", text }));  // you send; no event
```

**Four standard events:** `"open"`, `"message"`, `"error"`, `"close"`. This page uses `"message"` and `"close"`. There is no `"send"` event — `send()` is a method. Ping/pong are not exposed.

**Two "error"s**

| Layer | What | Meaning |
| --- | --- | --- |
| Transport | `"error"` / `"close"` | The **pipe** broke |
| App | `{"type":"error","text"}` inside `"message"` | Pipe is fine; **Groq failed** |

**Protocol:** client `{type:"user", text}` → server `{type:"token", text}*` then `{type:"done"}`, or `{type:"error", text}`. Empty / unknown types ignored.

### Server

`new WebSocket("/ws")` → FastAPI calls `chat_ws(ws)` with **this tab’s** connection. The name `ws` is not magic; you `await` methods on that object.

```python
await ws.accept()                 # handshake; browser gets "open"
raw = await ws.receive_text()     # park until next text, or disconnect
```

`while True` starts after `accept()` and **stops** at `receive_text()`. No `"receive_text"` event: browser **listens**; server **pulls**. `send_text()` does not wake this wait.

Kernel watches the socket for **readable** (data *or* peer close). Uvicorn interprets: text → string; disconnect → `WebSocketDisconnect`.

Each tab: this coroutine → this `ws` → this fd. `history` is just a list.

| Layer | Sees |
| --- | --- |
| Kernel | bytes, socket readable |
| Uvicorn | frames → ASGI `websocket.receive` / `disconnect` |
| `receive_text()` | return text or raise |
| `chat_ws` | chat JSON; Groq; `token` / `done` / `error` |

## Async

Mental model:

- Like a person: park in a lot, wait for the owner, then continue. `await` Uber, then travel; `await` the barista, then drink. Sequential `await`s are several stops in one trip. The **coroutine** is the car; the **runtime** is the attendant (many cars; does not know Uber vs coffee).
- Runtime: recursive **wait** and **resume** only. It does not care about app details. Translation APIs map down; in this program the bottom is usually a **socket** (timers/queues exist too).
- Wait family: `await` / `async for` / `async with`. `async def f` then `f()` → awaitable coroutine.
- `async def` + `yield` **creates** the async iterator. Each `yield x` is one item. No `append`. `async for` pulls.

`await` / `async for` / `async with` all **pause**. `async def` only allows pausing.

| | Picture | You need |
| --- | --- | --- |
| `await x` | one job | coroutine / Future |
| `async for x in y` | each item in a stream | async iterator |
| `async with x` | borrow; always put back | `__aenter__` / `__aexit__` |

**`async def f`** = coroutine **function**. **`f()`** = coroutine **object** (awaitable). Usually `await f()`. If `f` also `yield`s (`groq_stream`), `f()` is an async generator → `async for`, not `await`. Producer `yield`s; consumer `async for`s. `collected.append` is a normal list.

**`await f()`** does not read `f`’s source. Drive the coroutine until it **returns** or **parks** on a Future. Then resume. Transitive: nested `await`s until a primitive the loop understands.

**Scheduler** only: **stop** (task waits on X), **resume** (X done). It never sees `receive_text`. The coroutine *hands it* X.

**Type checker** (mypy/pyright) looks at the type after `in`, not at “we are in `async def`.” `for` needs `Iterable` (`list`). `async for` needs `AsyncIterable` (`async def` + `yield` ⇒ async generator, or `-> AsyncIterator[str]`). Wrong loop = type error. Missing `await` on a coroutine is also flagged. `async def` may still contain a plain `for` over a list. CPython will not catch `for` vs `async for` at parse time — without a checker you get `TypeError` when that line runs. `await` / `async for` / `async with` inside a plain `def` is a **SyntaxError**.

**Iceberg** — you write `await ws.receive_text()`; the socket wait is hidden:

```
await ws.receive_text()      # app
  → asgi_receive()           # Starlette
    → queue.get()            # Uvicorn
      → Future / fd readable # asyncio + kernel  ← actual stop
```

`async for line in resp.aiter_lines()` parks on the **Groq HTTP** socket, same idea.

**`async with`** = `with`, but enter/exit can wait:

```python
client = await httpx.AsyncClient(timeout=60.0).__aenter__()
try:
    ...
finally:
    await client.__aexit__(...)
```

Nested `async with client.stream(...) as resp`: inner `__aexit__` ends **this POST/SSE**. `async with` on the **client** (or `aclose()`) ends the **session**.

## HTTP + SSE (Groq)

HTTP = one `POST`. SSE = Groq writes the **response body as `data: ...` lines** while it generates (`"stream": True`). Connection stays open until `[DONE]` / body ends. Not a WebSocket; Groq never sees `/ws`. Handle is `resp`; you **pull** lines (`aiter_lines()`), you do not `addEventListener`.

Three nested objects:

```
http_client          session (AsyncClient) — many possible trips
    └── resp         this POST / this SSE body  (client.stream(...))
            └── aiter_lines()   next line, next line, …
```

- **`http_client`** — the session. “I talk to Groq.” Owns the pool. Lives with the Uvicorn process (`lifespan`: create at startup, `aclose()` at shutdown). Not one request. Keeping the object and not closing it is what makes it long-lived; `async with AsyncClient` would kill it when that block ends.
- **`resp`** — one POST. Inner `async with` ends this trip; the session stays. TCP may return to the pool.
- **`aiter_lines()`** — not a third connection. Async iterator over `resp`’s body: next `\n`-terminated line.

Phone / ride picture: client = Uber account; `resp` = this ride; `aiter_lines()` = GPS updates until `[DONE]`.

`timeout=60.0` is **not** session lifetime. It is: if this call **stalls** (no new bytes) for 60s, fail this POST. Tokens that keep arriving may run longer than 60s. Stall = no progress, not “whole reply must finish in 60s.”

**Both push and pull**

| Layer | Mode |
| --- | --- |
| Groq → TCP | **Push** — writes the next line when it has a token |
| Kernel | Bytes land in the **socket receive buffer**, then **fd readable** |
| Python | **Pull** — `async for line in resp.aiter_lines()` |

Order: Groq push → kernel buffer → notify (readable) → httpx reads into process memory → `line`. Not stored as a Groq inbox you poll. Slow pull: bytes sit in **your** kernel buffer; TCP can slow Groq.

## Groq vs Grok

Unrelated names. **Groq** = this API (Llama). **Grok** = xAI; unused.

Key in `~/.env` as `GROQ_API_KEY`. Browser never sees it. Never commit `.env`. Free ≠ unlimited; 429 → red sys line.

| Limit (free, check console) | Amount |
| --- | --- |
| Requests / min, / day | 30, 14,400 |
| Tokens / min, / day | 6,000, 500,000 |

https://console.groq.com/settings/limits · https://console.groq.com/keys

**History:** one list per socket, 20 turns. Success appends the full assistant text. Failure pops the last user message.

## Files

| File | Role |
| --- | --- |
| `chat_ui.html` | UI + WebSocket client |
| `chat_server.py` | `GET /`, `/ws`, Groq stream, history |
| `requirements.txt` | fastapi, uvicorn, websockets, httpx, python-dotenv |
| `.env.example` | `GROQ_API_KEY=` (empty) |
| `README.md` | How to run |
