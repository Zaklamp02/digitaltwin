# Backlog — digital twin

Living document. `[ ]` pending · `[~]` in progress · `[x]` done · `[!]` needs Sebastiaan

---

## Active bugs

*(none)*

---

## Session log

### 2026-04-25

- [x] **DEPLOY_PRD.md** — full deployment PRD written (D1–D4 milestones, security, PWA offline, ops)
- [x] **Sync strategy** — decided cloud-first (NAS always reachable via CF Tunnel); offline writes deferred
- [x] **CF Tunnel** — confirmed same account as StoryBrew; `cert.pem` reusable, no re-login needed
- [x] **Git setup** — repo initialised, `.gitignore` hardened (secrets, data, memory, CF creds, tokens.txt), pushed to [github.com/Zaklamp02/digitaltwin](https://github.com/Zaklamp02/digitaltwin)
- [x] **OpenAI key rotation** — key that leaked into `.env.example` during initial commit has been rotated

---

## Active backlog

### D1 — NAS Deployment 🚀

Deploy to NAS at `sebastiaandenboer.org` via Cloudflare Tunnel. See [DEPLOY_PRD.md](./DEPLOY_PRD.md) for full spec.

- [ ] **D1.1** Update `docker-compose.yml` — add `cloudflared` service, `digital-twin-net` network, remove external port 5173
- [ ] **D1.2** Change `nginx.conf` `listen` to port 80 (internal-only; CF handles TLS)
- [ ] **D1.3** Provision new CF tunnel (`cloudflared tunnel create digital-twin`), add DNS routes for `sebastiaandenboer.org` + `www.`
- [ ] **D1.4** Add `Makefile` deploy targets (`make deploy`, `make restart`, `make logs`)
- [ ] **D1.5** Initial NAS directory + secrets setup (one-time manual step)

### D2 — Security Hardening 🔒

- [ ] **D2.1** Secrets hygiene: rotate all API keys before first deploy, set `chmod 600` on secrets files
- [ ] **D2.2** CF Zero Trust Access rules for `/admin/*` paths (email OTP gate)
- [ ] **D2.3** CF Transform Rule: inject `X-Frame-Options`, `X-Content-Type-Options`, `Referrer-Policy` headers
- [ ] **D2.4** Tighten rate limit for public tier (`/api/chat` → 20 req/hour)
- [ ] **D2.5** nginx `server_tokens off` + host header guard

### D3 — PWA / Offline Notebook 📓

> **Revised (2026-04-25):** Cloud-first approach — NAS is always accessible via CF Tunnel. Offline reads (D3.1) are worth doing cheaply. Offline writes (D3.2+) deferred until actually needed.

- [ ] **D3.1** Add `vite-plugin-pwa` — Workbox `NetworkFirst` for `/api/knowledge/`, installable manifest (half day)
- [ ] *(deferred)* **D3.2** `useOfflineQueue.ts` — IndexedDB write queue
- [ ] *(deferred)* **D3.3** `PageEditor.tsx` offline save → enqueue
- [ ] *(deferred)* **D3.4** Sync indicator in Knowledge tab header
- [ ] *(deferred)* **D3.5** Flush queue on `window online` event

### D4 — Production Operations ⚙️

- [ ] **D4.1** Backup script on NAS (Synology Task Scheduler) — daily SQLite + memory tar, 30-day retention
- [ ] **D4.2** UptimeRobot (or CF Notifications) monitoring `sebastiaandenboer.org/api/health`
- [ ] **D4.3** SQLite WAL mode (`PRAGMA journal_mode=WAL`) to protect against power-loss corruption

---

### M34 — Telegram quality fixes ✅ 2026-04-24 CEST

Root causes found: stale `.md` chunks polluting retrieval, no conversation logging, LLM not sending PDF links.

- [x] **Stale chunk cleanup** — `rag.py _reindex_from_knowledge` now also removes legacy `.md`-based chunks in knowledge-DB mode; clears ~140 stale chunks that were diluting retrieval (family, publications, etc.)
- [x] **Full conversation logging** — every Telegram turn (user + assistant) is written to the shared NDJSON log with `"channel": "telegram"`. Visible in the admin Logs tab immediately. Turn counter resets on `/reset`.
- [x] **`/cv` command** — directly sends CV PDF by reading `file_path` from the `cv` KnowledgeDB node; no LLM round-trip
- [x] **Document manifest injection** — `_doc_manifest()` dynamically builds a list of all document-linked nodes and appends it to the system prompt each turn, so the LLM includes `[Title](/documents/FILENAME.pdf)` links → auto-sent as Telegram file attachments by the existing `_MD_DOC_RE` regex

### M35 — Public-facing Telegram bot

A second bot token accepting messages from *anyone*, backed by the same RAG stack with tier detection.

**Approach**:
- Register a second bot via BotFather (`TELEGRAM_PUBLIC_BOT_TOKEN` in `.env`)
- Refactor `TelegramBot` to accept a `mode: "owner" | "public"` param; public mode lifts the owner-only guard
- **Tier detection**: user sends `/start <token>` → session upgraded to that tier; default = `public`
- **Rate limiting**: reuse `SessionStore` keyed on `telegram_user_id` (not IP)
- **Context isolation**: per-user conversation history dict, max 20 turns each
- **Onboarding**: `/start` message explains the twin + invites token entry for richer access
- Recruiter-tier notifications fire to owner chat on first message from a new user

**Effort**: ~1 day. RAG/LLM stack is already wired; this is purely bot session and routing work.

### ✅ M36 — Eval harness for continuous quality testing

Implemented: `tests/golden_qa.yaml`, `tests/test_golden.py`, `tests/eval_ragas.py`. Makefile targets `test-golden` and `eval-ragas` added.

---

## Next up

### M18 — Image support in memory palace
- [ ] Extend `app/indexer.py` to detect `*.png / *.jpg / *.webp` in the `memory/` tree
- [ ] For each image, call OpenAI Vision (`gpt-4o`) at index time to generate a caption; store as a chunk with `source_type: image` + `image_path` metadata
- [ ] RAG: when an image chunk is in context, attach `image_url` in SSE metadata
- [ ] Frontend: `ChatStream.tsx` renders an inline `<img>` card when `image_url` is present in chunk metadata

### M19 — Video support (deferred / stretch)
- [ ] Support MP4/MOV in `memory/` — extract audio with `ffmpeg`, transcribe via Whisper at index time
- [ ] Store transcript chunks with `source_type: video` + timestamp offset; optionally surface thumbnail + link in chat

### ✅ M24 — OpenAI TTS/STT improvements ✅ 2026-04-24 CEST

Switched to OpenAI-only TTS/STT stack with the following upgrades:

- [x] **PCM streaming TTS** — `/api/speak` now returns raw PCM (24 kHz, 16-bit mono); `useTTS.ts` streams audio directly into Web Audio API `AudioBufferSourceNode` chain, starting playback before the full audio is received.
- [x] **Default model upgrade** — TTS default changed to `gpt-4o-mini-tts` (13 voices, tone/accent control); configurable per-deployment via admin Config tab.
- [x] **STT model selection** — `whisper-1`, `gpt-4o-mini-transcribe`, `gpt-4o-transcribe` all selectable from admin Config tab.
- [x] **VAD (voice activity detection)** — `useSTT.ts` uses Web Audio API `AnalyserNode` to detect silence; recording auto-stops after 1.5 s of silence post-speech — no manual stop click needed.
- [x] **Config tab — Voice & audio section** — TTS model, default voice (filtered by model), and STT model are grouped together in the admin Config tab.
- [x] **Voice cloning investigated** — OpenAI does support custom voice cloning (`/v1/audio/voices` API): upload a ≤30 s consent + sample recording, get back a `voice_id` usable in TTS. Gated to eligible organisations (contact `sales@openai.com`). Once enabled, pass `voice: { id: "voice_xyz" }` to the speech endpoint. Not wired up yet — add as M37 if needed.

### M35 — Public-facing Telegram bot

A second bot token accepting messages from *anyone*, backed by the same RAG stack with tier detection.

**Approach**:
- Register a second bot via BotFather (`TELEGRAM_PUBLIC_BOT_TOKEN` in `.env`)
- Refactor `TelegramBot` to accept a `mode: "owner" | "public"` param; public mode lifts the owner-only guard
- **Tier detection**: user sends `/start <token>` → session upgraded to that tier; default = `public`
- **Rate limiting**: reuse `SessionStore` keyed on `telegram_user_id` (not IP)
- **Context isolation**: per-user conversation history dict, max 20 turns each
- **Onboarding**: `/start` message explains the twin + invites token entry for richer access
- Recruiter-tier notifications fire to owner chat on first message from a new user

**Effort**: ~1 day. RAG/LLM stack is already wired; this is purely bot session and routing work.

---

## Parking lot / ideas

- **Voice cloning (M37)** — OpenAI custom voices are available for eligible orgs (contact sales). Once enabled: record consent phrase + 30 s sample → `POST /v1/audio/voice_consents` then `POST /v1/audio/voices` → use returned `voice_id` in `/api/speak`. Would make the digital twin sound like Sebastiaan.
- **Animated avatar / lip-sync** — Simli or HeyGen API; significant complexity, nice V3 demo feature
- **Rate limit UI** — show remaining turns to user so conversation end is less abrupt
- **Shareable conversation link** — read-only URL for a transcript (needs persistence layer)
- **i18n** — Dutch/English toggle (Sebastiaan works bilingually)
- **Notebook conflict resolution V2** — diff modal when offline edits conflict with server version (D3.5 V1 is last-write-wins)

## Open questions
- [!] Concrete anecdotes to seed personal memory (kids' stories, Maerlyn)
- [!] Explicit topic blocklist (former clients by name, specific projects)
- [!] Privacy/cookie notice copy for public launch (GDPR — NL)
- [x] **Domain confirmed: sebastiaandenboer.org** — same CF account as StoryBrew ✓ (`cert.pem` reusable, no re-login needed)
- [!] Tone calibration on the "anti-statement" joke
- [!] NAS SSH user for digital_twin: same `Storybrew` user as StoryBrew, or separate?
- [!] Should M35 (public Telegram bot) be bundled in the initial deploy or a follow-up release?

---

---

# Release history

<details>
<summary><strong>v1.0 — initial build (2026-04-22)</strong></summary>

| # | Summary |
|---|---------|
| M1 | Scaffold: folder tree, `.env.example`, `.gitignore`, README, pyproject.toml, package.json |
| M2 | Seed memory palace: 20 markdown files across public/recruiter/personal tiers |
| M3 | Backend core: FastAPI, pydantic-settings, NDJSON logger, `/api/health` |
| M4 | Auth + rate limiting: token resolver, tier enum, session store, quotas; 6 tests green |
| M5 | RAG layer: embedders, MemoryPalace, indexer (tiktoken + char fallback), ChromaDB retrieval; 9 tests green |
| M6 | LLM providers: Anthropic + OpenAI streaming behind `LLMProvider` protocol |
| M7 | `/api/chat` SSE: prompt assembly, turn logging, session/quota gates, `conversation_end` event |
| M8 | Audio: `/api/transcribe` (Whisper) + `/api/speak` (OpenAI TTS streaming) |
| M9 | Frontend scaffold: Vite + React + TS + Tailwind, header, 720 px layout |
| M10 | Chat wiring: `useChat` SSE parser, `ChatStream`, `InputBar`, `ConversationEnd` |
| M11 | Voice wiring: `useSTT` MediaRecorder, `useTTS` sentence queue + FIFO playback |
| M12 | Polish: empty state, loading indicator, error surface |
| M13 | Docker: backend Dockerfile, frontend multi-stage (Node→nginx), `docker-compose.yml` |
| — | **Final check**: 15/15 pytest green, 157 KB bundle, all routes registered |

</details>

<details>
<summary><strong>v1.1 — UI, graph, admin (2026-04-23 – 2026-04-24)</strong></summary>

| # | Summary |
|---|---------|
| M14 | Markdown rendering: `react-markdown` + `remark-gfm` + `rehype-highlight` |
| M15 | Fullscreen + mobile polish: `100dvh`, safe-area insets, scroll-to-bottom button |
| M16 | UI improvements: suggestion chips, typing indicator, copy button, dark mode toggle |
| M17 | CV endpoint: `GET /api/cv` PDF download + "Download CV" button in BioModal |
| M20 | Telegram bot (owner): long-polling, `/reset /stats /sessions /whoasked /reload /config /cv`; voice notes (Whisper); daily digest 08:00 AMS; image + document auto-send |
| M21 | Owner push alerts: Telegram notification on first turn; recruiter tier flagged 🔔 |
| M22 | Analytics dashboard: stats cards, 30-day timeline, tier breakdown, paginated Logs tab |
| M23 | Suggestion chips: `GET /api/suggestions` seeded from knowledge nodes; Content tab override |
| M25 | Knowledge graph: SQLite `nodes` + `edges`, `migrate_from_memory`, `resync_seed_edges`, `/admin/graph` |
| M26 | Ollama provider: `OllamaProvider`, live model list, switchable from Config tab |
| M27 | Graph visualisation: BFS tier rings, focus-expand animation, lerp loop |
| M28 | Memory chat: tool-calling loop (CRUD nodes + edges); two-tier hub graph structure |
| M29 | Graph power-ups: pan/zoom, node content inspection, cross-tab nav, edge add/delete |
| M30 | Graph overhaul: 34 nodes / 45 edges, family, publications, hobbies, personality hubs |
| M31 | Document attachments: 6 nodes linked to PDFs (CV, ISO cert, DISC, PLDJ, 2× papers) |
| M32 | Graph UI polish: emoji type icons, markdown-preview default, DB-driven (`.md` files removed) |
| M33 | Dashboard content config: `/api/admin/content` + `/api/content-config`; Content tab |
| B1 | Bio modal: dual-card overlay (About Sebastiaan + About this digital twin) |
| B3 | Removed settings cog; auto voice/text mode detection |

</details>
