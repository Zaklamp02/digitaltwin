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

### 2026-04-26

- [x] **Mindscape canvas restored** — reverted MindscapeCanvas.tsx and App.tsx back to the smooth "wow super cool" version after the navStack rewrite broke zoom/fluidity
- [x] **Mic button** — added STT microphone button to inline chat input bar on the Mindscape landing page
- [x] **Featured toggle fix** — `apiFetch` was double-prefixing `/api/admin` on the featured PATCH endpoint; fixed
- [x] **Dynamic root nodes** — replaced hardcoded `TOP_LEVEL_IDS` with `featured` flag from DB; admin can toggle which nodes appear on landing page via star button
- [x] **LABELS removed** — nodes now show their actual DB title instead of hardcoded overrides
- [x] **Responsive zoom** — `DEFAULT_ZOOM` is 0.9 on mobile (<600px) vs 1.35 on desktop
- [x] **Multi-level graph traversal** — click a child node to dive deeper; camera zooms smoothly, layout rebuilds centered on that child with its own children fanning out
- [x] **Child count badges** — small number badges on child nodes show how many sub-children they have
- [x] **Back navigation** — click empty space while dived to back out one level; click at root to unfocus; goHome resets full dive stack
- [x] **Ring crossfade animation** — children fade in/out during dive/back transitions

---

## Active backlog

### D1 — NAS Deployment 🚀 ✅

Deployed to NAS at `sebastiaandenboer.org` via Cloudflare Tunnel (StoryBrew stack's existing tunnel).

- [x] **D1.1** `docker-compose.yml` — `digital-twin-net` internal network + `cf-tunnel-net` external, service renamed `web` (avoids `frontend` DNS collision with StoryBrew)
- [x] **D1.2** `nginx.conf` listens on port 80 (internal); CF handles TLS
- [x] **D1.3** CF Tunnel ingress configured: `sebastiaandenboer.org → http://digital-twin-frontend:80`
- [x] **D1.4** `Makefile` deploy targets added
- [x] **D1.5** NAS directory + secrets + `.env` set up at `/volume1/docker/digital_twin`

> **Note:** `houtenjong_wordpress_1` was manually connected to `cf-tunnel-net` — ephemeral fix, will break on container restart. Not our compose file; pre-existing issue.

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

### ✅ W1 — Language toggle (NL / EN) ✅ 2026-04-25

Implemented. Backend accepts `language` field, frontend toggle persists in localStorage.

### ✅ W2 — Personal website wrapper (Mindscape) ✅ 2026-04-26

Full interactive canvas landing page at `sebastiaandenboer.org`:
- Smooth 2D canvas with camera lerp, pinch/zoom, particle system
- Knowledge graph nodes driven by `featured` flag (admin-controllable)
- Multi-level depth traversal with animated transitions
- Inline chat with STT mic button
- Responsive zoom for mobile
- Hero section with bio, links, avatar

### V2 — Obsidian Vault as Source of Truth 🗄️

Full PRD: `OBSIDIAN_PRD.md`. Branch: `v2-obsidian`.

**Phase 1: Export DB → vault** (zero-risk, additive only)
- [ ] **V2.1** `scripts/export_vault.py` — export all SQLite nodes as `.md` files with YAML frontmatter (type, roles, links, metadata) + folder hierarchy from notebook containment edges
- [ ] **V2.2** Export `_system.md` (system prompt) and `_config.md` (welcome msg, chips, translation prompt)
- [ ] **V2.3** Copy `data/documents/*` to vault `documents/` folder with companion `.md` stubs
- [ ] **V2.4** Validate: round-trip test — parse exported vault, compare node/edge counts with DB

**Phase 2: Sync pipeline** (new scripts, existing code untouched)
- [ ] **V2.5** `scripts/sync_vault.py` — vault parser (frontmatter + wikilinks + folder hierarchy → nodes + edges)
- [ ] **V2.6** Diff engine — compare parsed vault state vs SQLite, produce changeset
- [ ] **V2.7** SQLite writer — upsert nodes, reconcile edges, update settings from `_config.md`
- [ ] **V2.8** Incremental ChromaDB indexer — only re-embed changed nodes
- [ ] **V2.9** Binary file sync + CLI entry point with `--full` flag
- [ ] **V2.10** Test: sync a copy of exported vault → fresh DB, compare with original

**Phase 3: Backend switchover** (modify existing code)
- [ ] **V2.11** Replace startup `migrate_from_memory()` + `apply_graph_customizations()` + `resync_seed_edges()` with `sync_vault.py` invocation
- [ ] **V2.12** Remove / make read-only: content-editing admin API endpoints (node CRUD, edge CRUD, document upload, memory chat)
- [ ] **V2.13** Add `GET /api/admin/sync-status` endpoint

**Phase 4: Frontend strip** (modify existing code)
- [ ] **V2.14** Remove content-editing components from admin dashboard
- [ ] **V2.15** Add sync status panel (last sync time, file count, warnings)
- [ ] **V2.16** Make content views read-only (system prompt, welcome msg, chips)
- [ ] **V2.17** Local end-to-end test on port 8001/5174

**Phase 5: Deploy** (deferred — needs Sebastiaan)
- [!] **V2.18** Set up Syncthing/rsync from local vault → NAS
- [!] **V2.19** Cron job on NAS running `sync_vault.py` every 5 min
- [!] **V2.20** Cutover: merge branch, rebuild containers, validate

---

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
- **i18n** — Dutch/English toggle (Sebastiaan works bilingually) *(done — see W1)*
- **Notebook conflict resolution V2** — diff modal when offline edits conflict with server version (D3.5 V1 is last-write-wins)

### UX / Admin polish

- [ ] **Remove admin link from settings menu** — the gear / settings menu visible to end-users should not expose a direct link to the admin dashboard; remove or hide behind an auth check
- [ ] **Improve send / mic icons in chat** — icons feel inconsistent (size, weight, style); audit both buttons and align them visually (stroke weight, padding, active states)

### Content / data

- [ ] **Node special effects — images & PDFs** — attach a primary image or PDF to a node and show it as a visual badge/preview in the Mindscape canvas and the knowledge detail panel; reuse existing `has_document` flag plumbing
- [ ] **Better conversation starters on nodes** — current starters are generic; make them context-aware (pull from node body / edges), and model follow-up suggestions based on what was just asked / which related nodes exist
- [ ] **Scrape LinkedIn posts → seed blog nodes** — write a one-off script that pulls Sebastiaan's LinkedIn posts (via li_scraper or manual export), converts each to a `blog` node with body text and a `public` role, and indexes them into the RAG store
- [ ] **New hobby / interest nodes** — add graph nodes for: favourite games (board + video), electronics projects (ESP32 temperature sensors, solar panel monitoring setup), and link them to relevant skill/project nodes
- [ ] **Rename `recruiter` role → `public`** — several nodes in the DB still carry the legacy `recruiter` access tag; audit all nodes with `roles = ["recruiter"]` and change them to `public` (or remove the tag where the node shouldn't be public at all)
- [ ] **Consistent zoom animation on all Mindscape levels** — the first-level dive (e.g. clicking Hobbies) has a smooth camera-zoom transition; deeper dives feel like an instant screen-switch. Apply the same lerp/zoom-in animation to every level transition so the experience is seamless throughout the graph

### Visual QA findings — 2026-04-26

Full browser walkthrough performed against local Docker build after the April sprint. Issues ordered by priority.

- [ ] **VQA-1 "Images" ghost node in Mindscape** — Image indexer creates an `Images` node visible in the public graph even when no images exist in `memory/`. The node has no meaningful content and confuses visitors. Fix: suppress node creation in `image_indexer.py` if there are no images to index, or filter `type="document" AND source_type="image"` nodes from the featured/canvas list until they have actual content.

- [ ] **VQA-2 Second-level dive collapses to root** — After diving into Work (Level 1), double-clicking a child node (e.g. Youwe) collapses the graph all the way back to root instead of diving deeper. The two-phase animation logic in `MindscapeCanvas.tsx` appears to conflict with the existing focus collapse; the second click is treated as a "background click → go home". Needs investigation of the click-target detection in the canvas event handler.

- [ ] **VQA-3 Initial graph layout imbalance** — On first load the 5–6 root nodes cluster in the lower-centre of the canvas, leaving the upper-right ~40% empty. The layout algorithm should distribute root nodes more evenly across the viewport (e.g. circular or golden-angle placement) so the canvas looks balanced before any interaction.

- [ ] **VQA-4 Youwe shown at root AND as child of Work** — Youwe appears both as a standalone root-level node and as a child when Work is expanded, creating visual redundancy. Decide whether Youwe should be a top-level featured node or strictly a child; adjust `featured` flag accordingly.

- [ ] **VQA-5 "See all posts →" links to "#"** — The blog section on the homepage has a live `See all posts →` link that goes nowhere (`href="#"`). Either wire it to a real blog route/page or hide it until blog pagination exists.

- [ ] **VQA-6 Dark mode not visually applied on Mindscape canvas** — Toggling dark mode in the settings menu doesn't change the canvas background or particle colours (canvas `fillStyle` hardcoded to light values). The `/chat` route applies dark mode correctly via Tailwind classes. Canvas rendering in `MindscapeCanvas.tsx` needs to read the current theme and use dark palette values.

- [ ] **VQA-7 Excessive empty space in /chat after short replies** — After one short exchange, the chat history sits near the top of the screen with ~60% blank canvas below before the input bar. Messages should be anchored to the bottom (`flex-col-reverse` or scroll-to-bottom on new message) to reduce the visual emptiness.

- [ ] **VQA-8 Mindscape inline chat placeholder is generic** — The inline input on the landing page always shows "What's your experience with AI agents?" regardless of which node is focused. After a dive, the placeholder should update to match the node context (e.g. "Ask about Work…") to reinforce the conversation starter.

- [ ] **VQA-9 "About ↓" styled same as external links** — In the hero section, "About ↓" (a same-page scroll anchor) is styled identically to "LinkedIn", "GitHub", "Email" (external links). These serve different purposes and should be visually distinguished — e.g. "About ↓" as a subtle scroll indicator, external links as icon+text badges.

- [ ] **VQA-10 No typing indicator in Mindscape inline chat** — When a message is sent from the inline chat on the landing canvas, there is no loading/typing animation while the SSE streams. The `/chat` route shows a typing indicator; the same should be applied to the inline chat component.

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
