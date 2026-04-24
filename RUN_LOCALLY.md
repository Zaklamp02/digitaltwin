# Run locally — first boot

The dev servers have to run on your Mac, not in my sandbox (mine is
network-isolated and can't expose ports to your browser, nor reach
`api.openai.com` for embeddings).

## Option A — Docker (matches your NAS deploy)

From this folder:

```
docker compose up --build
```

When you see both containers healthy, open:

- **Public**: http://localhost:5173
- **Recruiter**: http://localhost:5173/?t=rec-jOuPXS64JEw
- **Personal**: http://localhost:5173/?t=pers-HW3xmo0IsWE

Ctrl-C to stop; `docker compose down` to clean up.

## Option B — Two terminals (faster iteration)

Terminal 1 (backend):

```
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -e .
cd ..
python -m uvicorn app.main:app --app-dir backend --reload --port 8000
```

Terminal 2 (frontend):

```
cd frontend
npm install
npm run dev
```

Open: http://localhost:5173 (Vite proxies `/api` to `:8000`).

## What I verified in the sandbox

- `.env` is read; `LLM_PROVIDER=openai`, `MODEL_NAME=gpt-4o-mini` kicks in.
- `credentials.yaml` parses; three tokens registered (`""`, `rec-…`, `pers-…`).
- Memory palace loads all 20 markdown files.
- Only failures were sandbox-specific (no network egress to OpenAI, FUSE
  mount incompatible with Chroma's SQLite locking). Both work natively
  on macOS / in Docker.

## First-boot expectations

- Cold start: ~5–15 s while Chroma indexes the 20 memory files.
- First token of a reply: 1–3 s over OpenAI streaming.
- Personal tier answers with the full palace; recruiter tier excludes
  `personal/*`; public tier excludes both `personal/*` and `personality.md`
  + `opinions.md`.

## If something's off

- `logs/requests.ndjson` — one line per chat turn with tier, session id,
  retrieved chunks, scores, token counts, latency.
- `docker compose logs backend` / `frontend` — startup errors.
- Swap back to Anthropic any time by setting `LLM_PROVIDER=anthropic` +
  `ANTHROPIC_API_KEY=…` in `.env`; no code change needed.

## Rotating tokens before you put the QR code live

1. Edit `credentials.yaml` — replace the two `rec-…` / `pers-…` strings.
2. Update `tokens.txt` so you don't forget which is which.
3. No restart needed; the app re-reads credentials per request.
