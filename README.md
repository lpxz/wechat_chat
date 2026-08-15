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
# Key can live in ~/.env (GROQ_API_KEY=...) or a local .env — never commit either.
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
