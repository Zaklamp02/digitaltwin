# Digital Twin — NAS Deployment & Offline Notebook PRD

**Owner:** Sebastiaan den Boer  
**Target domain:** sebastiaandenboer.org  
**NAS IP (LAN):** 192.168.68.200  
**NAS deploy path:** `/volume1/docker/digital_twin`  
**Reference deployment:** StoryBrew (dromenbrouwer.nl) — same NAS, same CF tunnel account  
**Created:** 2026-04-24

---

## 1. Context & Goals

The digital twin ("Ask My Agent") is feature-complete locally and ready for its first public deployment. It needs to run continuously on the home NAS, be reachable globally under `sebastiaandenboer.org` via Cloudflare Tunnel, and be secure enough to expose publicly (recruiter/visitor tier) while keeping owner features locked down.

A secondary but important goal is making the **Knowledge Notebook** usable while travelling with poor connectivity: pages must be readable and editable offline, with automatic reconciliation when a network connection is restored.

### Non-goals (this PRD)
- CI/CD pipeline (manual rsync deploy for now)
- Multi-user collaboration on the notebook
- Full E2E test suite for production

---

## 2. Architecture Overview

```
┌────────────────────────────────────────────────────┐
│  Cloudflare Edge (HTTPS termination)               │
│  sebastiaandenboer.org  →  CF Tunnel               │
└────────────────┬───────────────────────────────────┘
                 │  (TLS tunnel, no open inbound port)
┌────────────────▼───────────────────────────────────┐
│  Synology NAS  192.168.68.200                      │
│  /volume1/docker/digital_twin                      │
│                                                    │
│  ┌───────────┐  ┌──────────┐  ┌─────────────────┐ │
│  │ cloudflared│  │ frontend │  │    backend       │ │
│  │  container │→ │  nginx   │→ │  FastAPI+Chroma  │ │
│  │  (tunnel)  │  │  :80     │  │  :8000          │ │
│  └───────────┘  └──────────┘  └────────┬────────┘ │
│                                         │           │
│       ┌─────────────────────────────────┘           │
│       │  Volumes (host paths)                       │
│       ├── ./memory         (markdown, hot-reload)   │
│       ├── ./chroma_db      (vector index)           │
│       ├── ./data           (knowledge.db SQLite)    │
│       ├── ./logs           (ndjson request log)     │
│       └── ./credentials.yaml                       │
└────────────────────────────────────────────────────┘

Browser (online)   ←→  sebastiaandenboer.org  ←→  NAS
Browser (offline)  ←→  IndexedDB + Service Worker cache
                        (sync queue flushed on reconnect)
```

The existing StoryBrew CF tunnel (ID `34e7de3b-3768-47f8-b5ba-d30fd9f71a26`) is already running on the NAS. Digital Twin will use its **own separate CF tunnel** to keep the two projects fully independent — different docker-compose stack, different network, no cross-service routing needed. Adding a second ingress hostname to the StoryBrew tunnel would require sharing Docker networks and creates fragile coupling.

---

## 3. Milestones

### D1 — NAS Deployment (Day 1–2)

The core "ship it" milestone: app running on NAS, reachable at `sebastiaandenboer.org`.

#### D1.1 — Production docker-compose

Update `docker-compose.yml` to add:

- `cloudflared` service (mirrors StoryBrew pattern)
- Internal Docker network (`digital-twin-net`) so tunnel can reach frontend by name
- Change nginx to listen on **port 80 internally** (mapped to nothing externally — all traffic via tunnel)
- Remove external port mapping `5173:5173` (tunnel replaces it; no raw port exposed on NAS)
- CORS_ORIGINS updated to include `https://sebastiaandenboer.org`

```yaml
# Additional service to add to docker-compose.yml
tunnel:
  image: cloudflare/cloudflared:latest
  container_name: digital-twin-tunnel
  command: tunnel --no-autoupdate run <TUNNEL_ID>
  volumes:
    - ./.cloudflared:/etc/cloudflared:ro
  depends_on:
    frontend:
      condition: service_started
  restart: unless-stopped
  networks:
    - digital-twin-net
```

`.cloudflared/config.yml`:
```yaml
tunnel: <TUNNEL_ID>
credentials-file: /etc/cloudflared/<TUNNEL_ID>.json

ingress:
  - hostname: sebastiaandenboer.org
    service: http://frontend:80
  - hostname: www.sebastiaandenboer.org
    service: http://frontend:80
  - service: http_status:404
```

#### D1.2 — Nginx port change

Change `nginx.conf` to `listen 80;` (internal-only; Cloudflare handles TLS). No external port binding in docker-compose means port 80 is never exposed on the NAS network interface.

#### D1.3 — CF Tunnel provisioning (one-time, done on dev machine)

Same CF account as StoryBrew — `cert.pem` is already present in `~/.cloudflared/` (or can be copied from `StoryBrew/.cloudflared/cert.pem`). No re-login needed.

```bash
# Create tunnel (no login needed — same account as StoryBrew)
cloudflared tunnel create digital-twin
# → writes <TUNNEL_ID>.json to ~/.cloudflared/

# Add DNS routes (Cloudflare dashboard will show CNAMEs automatically)
cloudflared tunnel route dns digital-twin sebastiaandenboer.org
cloudflared tunnel route dns digital-twin www.sebastiaandenboer.org

# Copy credentials into project
mkdir -p .cloudflared
cp ~/.cloudflared/<TUNNEL_ID>.json .cloudflared/
cp ~/.cloudflared/cert.pem .cloudflared/   # reuse existing cert
```

#### D1.4 — Deploy script / Makefile target

```makefile
NAS_HOST  = Storybrew@192.168.68.200
NAS_PATH  = /volume1/docker/digital_twin

deploy:
	tar --no-xattrs \
	    --exclude='.git' \
	    --exclude='backend/__pycache__' \
	    --exclude='backend/.venv' \
	    --exclude='frontend/node_modules' \
	    --exclude='chroma_db' \
	    --exclude='data' \
	    --exclude='logs' \
	    --exclude='.env' \
	    --exclude='credentials.yaml' \
	    -czf /tmp/digital-twin-deploy.tar.gz .
	scp /tmp/digital-twin-deploy.tar.gz $(NAS_HOST):$(NAS_PATH)/
	ssh $(NAS_HOST) "cd $(NAS_PATH) && tar -xzf digital-twin-deploy.tar.gz && rm digital-twin-deploy.tar.gz && docker compose up --build -d"

restart:
	ssh $(NAS_HOST) "cd $(NAS_PATH) && docker compose restart"

logs:
	ssh $(NAS_HOST) "cd $(NAS_PATH) && docker compose logs --tail=50 -f"
```

Note: `.env`, `credentials.yaml`, `data/`, `chroma_db/`, and `logs/` must be set up manually on the NAS once and are never overwritten by deploy (they are excluded from the tar).

#### D1.5 — Initial NAS setup (one-time checklist)

```bash
ssh Storybrew@192.168.68.200
mkdir -p /volume1/docker/digital_twin/{.cloudflared,data,logs,chroma_db}

# Copy secrets (done from dev machine, never committed)
scp .env Storybrew@192.168.68.200:/volume1/docker/digital_twin/.env
scp credentials.yaml Storybrew@192.168.68.200:/volume1/docker/digital_twin/credentials.yaml
scp .cloudflared/<TUNNEL_ID>.json Storybrew@192.168.68.200:/volume1/docker/digital_twin/.cloudflared/
scp .cloudflared/cert.pem Storybrew@192.168.68.200:/volume1/docker/digital_twin/.cloudflared/
scp .cloudflared/config.yml Storybrew@192.168.68.200:/volume1/docker/digital_twin/.cloudflared/

# Copy existing data (knowledge DB, ChromaDB)
rsync -av data/ Storybrew@192.168.68.200:/volume1/docker/digital_twin/data/
rsync -av chroma_db/ Storybrew@192.168.68.200:/volume1/docker/digital_twin/chroma_db/
```

---

### D2 — Security Hardening (Day 2–3)

#### D2.1 — Secrets hygiene

- `.env` and `credentials.yaml` are in `.gitignore` (already ✓) and excluded from deploy tar
- No secrets in `docker-compose.yml` — all via `env_file: .env`
- Rotate all tokens before first public deployment: `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, access tokens in `credentials.yaml`
- NAS volume permissions: `chmod 600 .env credentials.yaml .cloudflared/*.json`

#### D2.2 — Cloudflare Zero Trust (CF Access) for owner endpoints

Cloudflare Access provides a free login gate in front of specific paths, without touching the app code. Add CF Access Application rules in the CF Zero Trust dashboard:

| Path pattern | Policy |
|---|---|
| `sebastiaandenboer.org/admin/*` | Email OTP or Google SSO (owner only) |
| `sebastiaandenboer.org/api/admin/*` | Same policy |

Public paths (`/`, `/api/chat`, `/api/speak`, `/api/transcribe`) remain open.

> **Note:** CF Access adds a `Cf-Access-Jwt-Assertion` header. The backend can optionally validate it, but the CF edge blocks requests that fail the policy before they even reach the NAS.

#### D2.3 — Security headers via Cloudflare Transform Rules

Add a Cloudflare Transform Rule (free tier) to inject:

```
X-Frame-Options: DENY
X-Content-Type-Options: nosniff
Referrer-Policy: strict-origin-when-cross-origin
Permissions-Policy: camera=(), microphone=(self), geolocation=()
```

The microphone permission is kept for `(self)` because the STT voice feature requires it.

#### D2.4 — Rate limiting review

The existing `slowapi`-based rate limiter is active. For production, review limits in `rag.py` and set `RATE_LIMIT_ENABLED=true` in the production `.env`. Consider tightening `/api/chat` to 20 req/hour for public tier.

#### D2.5 — nginx hardening

Add to `nginx.conf`:

```nginx
server_tokens off;

# Block direct IP access (requires Host header == domain)
if ($host !~* ^(sebastiaandenboer\.org|www\.sebastiaandenboer\.org)$) {
    return 444;
}
```

Since there is no external port exposed (traffic only via the tunnel), direct IP access from the internet is already blocked. This is belt-and-suspenders for LAN access.

#### D2.6 — Telegram bot token rotation

The existing Telegram bot is owner-only. Before public launch:
- Confirm `TELEGRAM_CHAT_ID` is the owner's personal chat
- Verify that public visitors cannot trigger Telegram notifications (they can't — the notification code fires only on session creation for visitor tier)

---

### D3 — Offline-first Knowledge Notebook (deferred — build when needed)

> **Revised approach (2026-04-25):** Start cloud-first. The NAS is reachable from anywhere via CF Tunnel, so the notebook is always available as long as you have any internet connection at all. One database, no sync, no conflicts. Add offline write capability only when you actually hit the pain point.

**Tiers of offline support (implement in order if/when needed):**

**Tier 0 (free, no code) — already covered by Workbox once D3.1 is done:**  
Read-only offline. Once you've loaded the Knowledge page, Workbox serves cached API responses if the connection drops mid-session. Good enough for reading notes on a plane where you loaded the page earlier.

**Tier 1 — PWA shell + read cache (D3.1 only, ~half a day):**  
Add `vite-plugin-pwa`. Workbox `NetworkFirst` strategy for `/api/knowledge/*`. Makes the app installable (Add to Home Screen). Cached reads persist across browser sessions — open the app on the plane even if you haven't pre-loaded.

**Tier 2 — Offline write queue (D3.2–D3.5, ~2 days, defer):**  
IndexedDB pending-writes queue. Flush on reconnect. Sync badge. Only build this if Tier 1 proves insufficient in practice.

**Why not a "local master + cloud replica" architecture:**  
Bi-directional sync between two SQLite instances requires a conflict resolution protocol, a sync engine (e.g. CR-SQLite / Litestream), and either a message bus or polling. For a single-owner notebook the added complexity is not justified. If the data access pattern ever changes (multiple devices writing simultaneously, frequent offline sessions), revisit.

**Current recommendation: implement D3.1 (PWA read cache) alongside D1/D2, defer D3.2+.**

#### D3.1 — PWA manifest + Vite plugin

```bash
npm install -D vite-plugin-pwa
```

`vite.config.ts` additions:

```ts
import { VitePWA } from 'vite-plugin-pwa'

plugins: [
  react(),
  VitePWA({
    registerType: 'autoUpdate',
    workbox: {
      globPatterns: ['**/*.{js,css,html,ico,png,svg,woff2}'],
      runtimeCaching: [
        {
          urlPattern: /^\/api\/knowledge\//,
          handler: 'NetworkFirst',
          options: {
            cacheName: 'knowledge-api',
            expiration: { maxEntries: 500, maxAgeSeconds: 7 * 24 * 60 * 60 },
          },
        },
      ],
    },
    manifest: {
      name: 'Sebastiaan — Notebook',
      short_name: 'Notebook',
      theme_color: '#0f172a',
      icons: [{ src: '/avatar_digitaltwin.png', sizes: '192x192', type: 'image/png' }],
    },
  }),
]
```

#### D3.2–D3.5 — Offline write queue (deferred)

See original design in git history if needed. Implement only if Tier 1 proves insufficient.

---

### D4 — Production Operations (Day 3 + ongoing)

#### D4.1 — Backup script

Daily cron on NAS (Synology Task Scheduler):

```bash
#!/bin/bash
DEST=/volume1/backups/digital_twin
DATE=$(date +%Y-%m-%d)
mkdir -p $DEST

# SQLite (hot backup via sqlite3 .backup command)
sqlite3 /volume1/docker/digital_twin/data/knowledge.db ".backup $DEST/knowledge-$DATE.db"

# Rotate: keep last 30 days
find $DEST -name "*.db" -mtime +30 -delete
find $DEST -name "*.tar.gz" -mtime +30 -delete
```

ChromaDB is a derived index (can be rebuilt from the vault + knowledge.db via the existing reindex endpoint) — no backup needed.

#### D4.2 — Health monitoring

The backend already exposes `/api/health`. Add an uptime check:

- **Option A (free):** UptimeRobot (https://uptimerobot.com) — monitor `https://sebastiaandenboer.org/api/health`, alert by email/Telegram on down
- **Option B:** Cloudflare Health Checks (included in free plan under Notifications)

The Telegram bot can also be used for self-notification: a `/health` command that pings the backend.

#### D4.3 — Update procedure

```bash
# From dev machine:
make deploy           # tars, scps, extracts, docker compose up --build -d

# If data migration needed:
ssh Storybrew@192.168.68.200
cd /volume1/docker/digital_twin
docker compose exec backend python migrate_graph.py   # or relevant script
```

#### D4.4 — Rollback

```bash
# On NAS:
cd /volume1/docker/digital_twin
docker compose down
# restore from backup if data migration was involved
docker compose up -d   # uses previous image (still cached by Docker)
```

For image-level rollback, tag builds before deploying: `docker tag digital_twin-backend nas-backup-$(date +%Y%m%d)`.

---

## 4. Environment Variables — Production `.env` checklist

```env
# LLM
LLM_PROVIDER=anthropic        # or openai
MODEL_NAME=claude-sonnet-4-6
ANTHROPIC_API_KEY=sk-ant-...  # rotate before deploy
OPENAI_API_KEY=sk-...         # rotate before deploy

# Embeddings
EMBEDDING_PROVIDER=openai
EMBEDDING_MODEL=text-embedding-3-small

# Voice
TTS_MODEL=gpt-4o-mini-tts
TTS_VOICE=alloy
STT_MODEL=whisper-1

# Server
CORS_ORIGINS=https://sebastiaandenboer.org,https://www.sebastiaandenboer.org

# Paths (container-local — do NOT change)
CHROMA_DIR=/app/chroma_db
CREDENTIALS_FILE=/app/credentials.yaml
LOG_FILE=/app/logs/requests.ndjson
KNOWLEDGE_DB=/app/data/knowledge.db

# Rate limiting
RATE_LIMIT_ENABLED=true

# Telegram (optional)
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
```

---

## 5. Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| NAS offline when travelling → site down | Medium | High | UptimeRobot alert; Telegram ping; nothing to do remotely except restart via WoL if needed |
| Offline write queue conflicts (two devices) | Low | Medium | V1: last-write-wins; V2: diff modal (D3.5) |
| SQLite corruption on NAS power loss | Low | High | Daily backup (D4.1); WAL mode on SQLite (`PRAGMA journal_mode=WAL`) |
| CF Tunnel credentials leaked | Very Low | High | Never commit `.cloudflared/*.json`; add to `.gitignore` |
| API keys in `.env` leaked | Very Low | High | Keys never committed; rotate post-deploy; set in NAS directly |
| Public bot abuse / scraping | Medium | Medium | Rate limiting (D2.4); CF bot fight mode; public tier context isolation |
| ChromaDB index drift after crash | Low | Low | Reindex endpoint `/api/admin/reindex` available; chroma rebuilt in ~30 s |

---

## 6. Open questions (require Sebastiaan input)

| # | Question | Blocks |
|---|---|---|
| OQ1 | Is the NAS user for digital_twin the same `Storybrew` SSH user, or a separate one? | D1.3 |
| OQ2 | Should `sebastiaandenboer.org` be the public-facing URL for all tiers, or only owner/recruiter? (i.e., should visitors reach the chatbot at the root) | D2.2 |
| OQ3 | ~~CF account: same account as StoryBrew?~~ **Confirmed — same account. `cert.pem` reusable.** | D1.3 ✓ |
| OQ4 | Privacy / cookie notice needed for public launch? (GDPR — NL) | D2 |
| OQ5 | Should the public Telegram bot (M35) be bundled in this deploy, or is it a separate release? | D1 |
| OQ6 | Obsidian vs PWA for offline notebook — PWA is the proposed approach; confirm this is acceptable vs a dedicated mobile app | D3 |

---

## 7. Milestone summary & effort estimates

| Milestone | Scope | Effort |
|---|---|---|
| D1 — NAS Deployment | docker-compose changes, CF tunnel, nginx, deploy script, initial NAS setup | ~0.5 day |
| D2 — Security | CF Access rules, headers, secrets hygiene, rate limit tuning | ~0.5 day |
| D3.1 — PWA read cache | vite-plugin-pwa, Workbox NetworkFirst for knowledge API, installable manifest | ~0.5 day |
| D3.2–D3.5 — Offline writes | Write queue, sync badge, conflict handling — **deferred, build if needed** | ~2 days |
| D4 — Ops | Backup script, health monitoring, Makefile | ~0.5 day |
| **Total (without D3.2+)** | | **~2 days** |

---

## 8. What this PRD does NOT include

The following items are parked in the backlog for later:

- Public-facing Telegram bot (M35) — high value, minimal effort, but separate release
- Voice cloning (M37) — needs OpenAI org approval
- Animated avatar / lip-sync — V3 feature
- i18n (Dutch/English toggle)
- M18/M19 image & video memory support
