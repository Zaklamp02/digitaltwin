# Ask my agent

Self-hosted chatbot that represents Sebastiaan den Boer to anyone who lands on it
via the QR code on his CV. Speaks **about** him in the third person, knows his
career deeply, declines commercial questions cleanly.

See [`PRD.md`](./PRD.md) for the full spec and [`backlog.md`](./backlog.md) for
live build progress.

## Stack

- **Backend:** Python 3.11 + FastAPI + Uvicorn, ChromaDB, watchdog, slowapi.
- **Frontend:** Vite + React 18 + TypeScript + Tailwind.
- **LLM:** Anthropic or OpenAI, swappable via `LLM_PROVIDER`.
- **Voice:** OpenAI Whisper (STT) + OpenAI TTS (streaming).
- **Memory:** markdown folder hot-reloaded into ChromaDB.

## Run locally

```bash
# 1. backend
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -e .
cp ../.env.example ../.env                  # then fill in API keys
cp ../credentials.yaml.example ../credentials.yaml   # generate tokens
uvicorn app.main:app --reload --port 8000

# 2. frontend (separate shell)
cd frontend
npm install
npm run dev                                 # http://localhost:5173
```

Drop a real photo at `frontend/public/avatar.png` before the QR goes live.

## Run with Docker (NAS deploy)

```bash
cp .env.example .env                        # fill in keys
cp credentials.yaml.example credentials.yaml
docker compose up --build -d
```

Expose `http://<nas>:5173` through Cloudflare Tunnel when ready.

## Editing content

The Obsidian vault is the source of truth. Edit the `.md` files in your vault,
then restart the backend or trigger a vault sync from the admin interface.

## Tokens

Hand out tier-specific links by generating URL-safe tokens and adding them to
`credentials.yaml`:

```bash
python -c "import secrets; print('rec-' + secrets.token_urlsafe(8))"
# → rec-kF7vQx3Jn
# then share https://<host>/?t=rec-kF7vQx3Jn
```

## Tests

```bash
cd backend && pytest
```
