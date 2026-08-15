# WeChat-like Groq chat (WebSocket + LLM)

Date: 2026-08-15

## Goal

A small local app that exercises two things: a **WebSocket** between a WeChat-like HTML window and a Python server, and a **live Groq LLM call** whose tokens stream back over that socket into the page.

Manual testing only. No automated test suite.

## Stack

- FastAPI + Uvicorn
- One HTML/CSS/JS page (no frontend framework)
- Groq Chat Completions API, `stream=True`
- `GROQ_API_KEY` from the environment (documented in `.env.example`; never committed)

Sibling of `simple_calculator` at `onsites/cursor/wechat_chat`.

## Files

| File | Role |
| --- | --- |
| `chat_server.py` | Serves the page, `/ws`, Groq stream, in-memory history |
| `chat_ui.html` | WeChat-like window |
| `requirements.txt` | `fastapi`, `uvicorn`, `httpx`, `python-dotenv` |
| `.env.example` | `GROQ_API_KEY=` |
| `README.md` | How to run and how to test by hand |

## Architecture

One browser tab opens one WebSocket (`/ws`). That connection is one session. The server keeps a short in-memory message list for that socket (last 20 turns). Closing the tab drops the history. A reconnect is a new empty chat.

```
browser  --WS-->  FastAPI  --HTTPS stream-->  Groq
         <--tokens--              <--delta chunks--
```

`GET /` returns `chat_ui.html`.

## WebSocket protocol

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
{"type": "error", "text": "Groq request failed: ..."}
```

Empty `text` is ignored. Unknown `type` is ignored. No other message types.

## LLM

- Provider: Groq via raw `httpx` to `https://api.groq.com/openai/v1/chat/completions` (no SDK — the HTTP call stays visible)
- Model: `llama-3.1-8b-instant` (pinned in `chat_server.py`)
- Each user message: append `{role: user}`, call Groq with the session history, stream deltas as `token` frames, then `done`, then append `{role: assistant}` with the full text
- System prompt: short, one line — a friendly chat assistant

## UI

WeChat-like, single page:

- Light gray background (`#ededed`)
- Green header bar, title `Groq`
- Your messages: right-aligned green bubbles (`#95ec69`)
- Bot messages: left-aligned white bubbles plus a small round avatar
- Bottom composer: text field + send; Enter sends, Shift+Enter newline
- On send: append the green bubble immediately, then grow one live left bubble as `token` frames arrive; freeze it on `done`
- `error`: a red system line in the transcript, not a bot bubble

## Errors

- Missing `GROQ_API_KEY`: log on startup; first send returns `error` explaining the missing key
- Groq HTTP/network failure: `error` with a short reason
- Disconnect: drop that connection’s history

Out of scope: auth, multi-user rooms, disk persistence, message search, typing indicators beyond the live bubble.

## Testing (manual)

1. `python3 -m venv venv && source venv/bin/activate && pip install -r requirements.txt`
2. Set `GROQ_API_KEY`, run `uvicorn chat_server:app --port 8080 --reload`
3. Open http://localhost:8080
4. Send a short message; confirm a green bubble, then a growing left bubble, then it stops
5. Send a follow-up that needs the first turn; confirm the model uses session history
6. Optional: Cursor browser MCP (snapshot → type/click send → watch the bot bubble)

## Success

A person can chat in a WeChat-like window, see their text go over a WebSocket, and see Groq tokens stream into the page. Both the socket and the LLM call are visible in a few files.
