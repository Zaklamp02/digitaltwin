# NAS Dual-Runtime Deployment Guide

**Objective:** Run the Digital Twin on Synology NAS with two separate runtime instances:
- **Public stack** (`digital_twin_public`): Internet-facing via Cloudflare Tunnel, read-only for visitors
- **Internal stack** (`digital_twin_internal`): LAN-only for owner, full data access

**NAS Host:** `192.168.68.200`  
**Base deploy directory:** `/volume1/docker/`

---

## 1. Deployment Architecture Overview

```
┌──────────────────────────────────────────────────────────────────────────┐
│                    Synology NAS 192.168.68.200                           │
│                     /volume1/docker/                                     │
├──────────────────────────┬──────────────────────────────────────────────┤
│                          │                                              │
│   PUBLIC STACK           │   INTERNAL STACK                             │
│   (internet-facing)      │   (owner-only LAN)                           │
│                          │                                              │
│  /digital_twin_public/   │  /digital_twin_internal/                     │
│  ├─ .cloudflared/        │  ├─ vault/                                   │
│  ├─ .env (secrets)       │  ├─ .env (secrets, shared)                   │
│  ├─ credentials.yaml     │  ├─ credentials.yaml (shared)                │
│  ├─ data_public/         │  ├─ data_internal/  ← full DB                │
│  │  ├─ knowledge.db      │  │  ├─ knowledge.db                          │
│  │  └─ (published only)  │  │  └─ (all roles)                           │
│  ├─ chroma_db_public/    │  ├─ chroma_db_internal/ ← full index         │
│  │  └─ (published only)  │  │  └─ (all embeddings)                      │
│  ├─ logs/                │  ├─ logs_internal/                           │
│  ├─ frontend/            │  ├─ frontend/ (shared code)                  │
│  ├─ backend/             │  ├─ backend/ (shared code)                   │
│  └─ docker-compose.yml   │  └─ docker-compose.yml                       │
│      (symlink to base)   │      (symlink to base)                       │
│                          │                                              │
│  Services:               │  Services:                                   │
│  • tunnel-public         │  • (no tunnel; LAN only)                     │
│  • frontend-public       │  • frontend-internal                         │
│    port 8080             │    port 8081                                 │
│  • backend-public        │  • backend-internal                          │
│    APP_MODE=public       │    APP_MODE=internal                         │
│                          │                                              │
└──────────────────────────┴──────────────────────────────────────────────┘
           │
           ├─→ Cloudflare Tunnel (public)
           │   ├─ sebastiaandenboer.org
           │   └─ www.sebastiaandenboer.org
           │
           └─→ publish-projection (cron job, runs hourly/daily)
               Syncs public-role data from internal to public datasets
```

---

## 2. File Structure

```
/volume1/docker/
├── digital_twin_public/           (public runtime)
│   ├── .cloudflared/
│   │   ├── cert.pem
│   │   ├── config.yml
│   │   └── <TUNNEL_ID>.json       (credentials)
│   ├── data_public/               (synced from internal)
│   │   └── knowledge.db
│   ├── chroma_db_public/
│   ├── logs/
│   ├── .env → ../../.env.shared   (symlink to shared secrets)
│   ├── credentials.yaml → ../../credentials.yaml.shared (symlink)
│   ├── frontend/ → ../../frontend/ (symlink)
│   ├── backend/ → ../../backend/  (symlink)
│   ├── scripts/ → ../../scripts/  (symlink)
│   ├── docker-compose.public.yml → ../../docker-compose.public.yml
│   └── docker-compose.yml         (alias to .public.yml)
│
├── digital_twin_internal/         (internal runtime)
│   ├── vault/                     (full private vault, synced from git)
│   ├── data_internal/             (full database)
│   │   └── knowledge.db
│   ├── chroma_db_internal/
│   ├── logs_internal/
│   ├── .env → ../../.env.shared   (symlink to shared secrets)
│   ├── credentials.yaml → ../../credentials.yaml.shared (symlink)
│   ├── frontend/ → ../../frontend/ (symlink)
│   ├── backend/ → ../../backend/  (symlink)
│   ├── scripts/ → ../../scripts/  (symlink)
│   ├── docker-compose.internal.yml → ../../docker-compose.internal.yml
│   └── docker-compose.yml         (alias to .internal.yml)
│
├── shared-code/                   (shared across both stacks)
│   ├── frontend/                  (React app, built into both stacks)
│   ├── backend/                   (Python backend, built into both stacks)
│   ├── scripts/
│   │   ├── publish_public_projection.py
│   │   └── vault_sync.py
│   ├── docker-compose.public.yml
│   ├── docker-compose.internal.yml
│   ├── .env.shared                (API keys, never committed)
│   └── credentials.yaml.shared    (tokens, never committed)
│
└── cron-jobs/
    └── publish-projection.sh      (runs hourly/daily to sync public data)
```

**Key Point:** Each runtime stack symlinks to the shared code and secrets, so you maintain one codebase while running two isolated services.

---

## 3. Setup Instructions (One-time)

### 3.1. Create directory structure on NAS

```bash
ssh Storybrew@192.168.68.200

# Create all directories
mkdir -p /volume1/docker/digital_twin_public/{.cloudflared,data_public,chroma_db_public,logs}
mkdir -p /volume1/docker/digital_twin_internal/{vault,data_internal,chroma_db_internal,logs_internal}
mkdir -p /volume1/docker/shared-code
mkdir -p /volume1/docker/cron-jobs

# Set permissions on secret files
chmod 700 /volume1/docker/digital_twin_public/.cloudflared
chmod 700 /volume1/docker/digital_twin_internal
```

### 3.2. Deploy code and create symlinks

From dev machine:

```bash
# 1. Copy shared code to NAS
rsync -av --exclude='.git' \
  --exclude='node_modules' \
  --exclude='__pycache__' \
  --exclude='.venv' \
  --exclude='backend/.pytest_cache' \
  --exclude='data*' \
  --exclude='chroma_db*' \
  --exclude='logs*' \
  --exclude='vault' \
  --exclude='.env' \
  --exclude='credentials.yaml' \
  . Storybrew@192.168.68.200:/volume1/docker/shared-code/

# 2. SSH to NAS and create symlinks for public stack
ssh Storybrew@192.168.68.200

cd /volume1/docker/digital_twin_public
ln -s ../shared-code/frontend frontend
ln -s ../shared-code/backend backend
ln -s ../shared-code/scripts scripts
ln -s ../shared-code/docker-compose.public.yml .
ln -s docker-compose.public.yml docker-compose.yml
ln -s ../../.env.shared .env
ln -s ../../credentials.yaml.shared credentials.yaml

# 3. Create symlinks for internal stack
cd /volume1/docker/digital_twin_internal
ln -s ../shared-code/frontend frontend
ln -s ../shared-code/backend backend
ln -s ../shared-code/scripts scripts
ln -s ../shared-code/docker-compose.internal.yml .
ln -s docker-compose.internal.yml docker-compose.yml
ln -s ../../.env.shared .env
ln -s ../../credentials.yaml.shared credentials.yaml
```

### 3.3. Deploy secrets (one-time, never on NAS)

From dev machine, copy secrets directly to NAS (never committed to git):

```bash
scp .env Storybrew@192.168.68.200:/volume1/docker/.env.shared
scp credentials.yaml Storybrew@192.168.68.200:/volume1/docker/credentials.yaml.shared

# Cloudflare tunnel credentials (created locally, never in git)
scp .cloudflared/<TUNNEL_ID>.json Storybrew@192.168.68.200:/volume1/docker/digital_twin_public/.cloudflared/
scp .cloudflared/cert.pem Storybrew@192.168.68.200:/volume1/docker/digital_twin_public/.cloudflared/
```

### 3.4. Copy initial data (one-time or one-off sync)

From dev machine:

```bash
# Copy initial knowledge database to NAS
rsync -av data/ Storybrew@192.168.68.200:/volume1/docker/digital_twin_internal/data_internal/
rsync -av chroma_db/ Storybrew@192.168.68.200:/volume1/docker/digital_twin_internal/chroma_db_internal/

# Create initial public projection (see section 5)
ssh Storybrew@192.168.68.200
cd /volume1/docker/digital_twin_internal
docker compose up -d backend-internal
docker compose exec backend-internal python scripts/publish_public_projection.py \
  --internal-db /app/data_internal/knowledge.db \
  --public-db /volume1/docker/digital_twin_public/data_public/knowledge.db \
  --internal-chroma /app/chroma_db_internal \
  --public-chroma /volume1/docker/digital_twin_public/chroma_db_public
```

### 3.5. Deploy Cloudflare tunnel (one-time setup)

> Assumes you already have a Cloudflare account set up (same as StoryBrew project).

From dev machine (tunnel auth already cached):

```bash
# Create tunnel (no login needed — same account as StoryBrew)
cloudflared tunnel create digital-twin-public

# View tunnel ID and copy to .cloudflared/
cat ~/.cloudflared/digital-twin-public.json
# → Copy this to NAS at /volume1/docker/digital_twin_public/.cloudflared/digital-twin-public.json

# Create DNS routes
cloudflared tunnel route dns digital-twin-public sebastiaandenboer.org
cloudflared tunnel route dns digital-twin-public www.sebastiaandenboer.org

# Config file (.cloudflared/config.yml on NAS, see template below)
```

**.cloudflared/config.yml** (create on NAS):

```yaml
tunnel: <TUNNEL_ID>
credentials-file: /etc/cloudflared/<TUNNEL_ID>.json

ingress:
  - hostname: sebastiaandenboer.org
    service: http://frontend-public:80
  - hostname: www.sebastiaandenboer.org
    service: http://frontend-public:80
  - service: http_status:404
```

---

## 4. Running the Stacks

### 4.1. Start both runtimes on NAS

```bash
ssh Storybrew@192.168.68.200

# Terminal 1: Public stack
cd /volume1/docker/digital_twin_public
docker compose up -d

# Terminal 2: Internal stack
cd /volume1/docker/digital_twin_internal
docker compose up -d

# Verify both are running
docker compose -f /volume1/docker/digital_twin_public/docker-compose.yml ps
docker compose -f /volume1/docker/digital_twin_internal/docker-compose.yml ps
```

### 4.2. Access public runtime

- **Online:** https://sebastiaandenboer.org (via Cloudflare Tunnel)
- **LAN debug:** http://nas.local:8080 (raw, no auth required)

### 4.3. Access internal runtime

```bash
# From dev machine or any LAN client
curl -H "X-Access-Token: <token_from_credentials.yaml>" \
  http://nas.local:8081/api/health

# Or browse (requires passing token via sessionStorage or fragment)
# http://nas.local:8081#t=<token>
```

### 4.4. Logs

```bash
# Public stack
ssh Storybrew@192.168.68.200 \
  "cd /volume1/docker/digital_twin_public && docker compose logs -f"

# Internal stack
ssh Storybrew@192.168.68.200 \
  "cd /volume1/docker/digital_twin_internal && docker compose logs -f"

# Persistent logs stored in:
# - /volume1/docker/digital_twin_public/logs/requests.ndjson
# - /volume1/docker/digital_twin_internal/logs_internal/requests.ndjson
```

---

## 5. Publishing Public Projection (Data Sync)

The public dataset must be kept in sync with published (public-role) content from the internal database. This is done via the `publish_public_projection.py` script.

### 5.1. Publish manually

On NAS, from the internal stack directory:

```bash
cd /volume1/docker/digital_twin_internal

# Run projection script inside the internal backend container
docker compose exec backend-internal python scripts/publish_public_projection.py \
  --internal-db /app/data_internal/knowledge.db \
  --public-db /volume1/docker/digital_twin_public/data_public/knowledge.db \
  --internal-chroma /app/chroma_db_internal \
  --public-chroma /volume1/docker/digital_twin_public/chroma_db_public
```

### 5.2. Automate via cron

Create a cron job to publish public projection hourly/daily.

`/volume1/docker/cron-jobs/publish-projection.sh`:

```bash
#!/bin/bash
set -e

INTERNAL_STACK=/volume1/docker/digital_twin_internal
PUBLIC_STACK=/volume1/docker/digital_twin_public

# Ensure internal stack is running
cd $INTERNAL_STACK
docker compose up -d backend-internal

# Run projection
docker compose exec -T backend-internal python scripts/publish_public_projection.py \
  --internal-db /app/data_internal/knowledge.db \
  --public-db ${PUBLIC_STACK}/data_public/knowledge.db \
  --internal-chroma /app/chroma_db_internal \
  --public-chroma ${PUBLIC_STACK}/chroma_db_public

# Restart public backend to pick up new data
cd $PUBLIC_STACK
docker compose restart backend-public

# Log result
echo "$(date): Public projection published successfully" >> /volume1/docker/cron-jobs/projection.log
```

Add to NAS cron (via Synology Control Panel or SSH):

```cron
# Publish public projection every day at 2 AM (NAS timezone)
0 2 * * * /volume1/docker/cron-jobs/publish-projection.sh
```

---

## 6. Updating Code (Deployment)

When you have new code to deploy:

```bash
# From dev machine
cd /path/to/Digital\ Twin

# Rebuild and redeploy both stacks
rsync -av --exclude='.git' \
  --exclude='node_modules' \
  --exclude='__pycache__' \
  --exclude='.venv' \
  --exclude='data*' \
  --exclude='chroma_db*' \
  --exclude='logs*' \
  --exclude='vault' \
  --exclude='.env' \
  --exclude='credentials.yaml' \
  . Storybrew@192.168.68.200:/volume1/docker/shared-code/

# SSH to NAS
ssh Storybrew@192.168.68.200

# Rebuild and restart both stacks
cd /volume1/docker/digital_twin_public && docker compose up -d --build
cd /volume1/docker/digital_twin_internal && docker compose up -d --build
```

---

## 7. Monitoring & Maintenance

### 7.1. Health checks

Both stacks have health endpoints configured in docker-compose:

```bash
curl http://backend-public:8000/api/health     # from inside public stack
curl http://backend-internal:8000/api/health   # from inside internal stack
```

### 7.2. Disk usage

```bash
ssh Storybrew@192.168.68.200

# Check space
du -sh /volume1/docker/digital_twin_public/data_public/
du -sh /volume1/docker/digital_twin_internal/data_internal/
du -sh /volume1/docker/digital_twin_public/chroma_db_public/
du -sh /volume1/docker/digital_twin_internal/chroma_db_internal/
```

### 7.3. Backup strategy

- **Code:** Stored in Git (public & private repos)
- **Internal data:** Back up `/volume1/docker/digital_twin_internal/data_internal/` and `chroma_db_internal/` regularly
- **Secrets:** Keep `.env.shared` and `credentials.yaml.shared` backed up separately (not in Git)
- **Public data:** Auto-generated from internal via projection; no separate backup needed

---

## 8. Security Checklist

- [ ] Rotate all API keys before first public deployment
- [ ] Verify `.env` and `credentials.yaml` are in `.gitignore` and **not** committed
- [ ] Set NAS file permissions: `chmod 600` on `.env.shared`, `credentials.yaml.shared`, `.cloudflared/*.json`
- [ ] Cloudflare Access policies configured for `/admin` routes (email OTP or SSO)
- [ ] Cloudflare tunnel credentials (`.json`) only stored on NAS, never in Git or email
- [ ] Test public stack with invalid/missing token → should get 401 or empty public data
- [ ] Test internal stack with valid owner token → should get full data access
- [ ] Verify APP_MODE=public prevents admin routes from being registered
- [ ] Confirm vault_sync.py runs on schedule to keep internal vault fresh

---

## 9. Troubleshooting

### Backend not connecting to Chroma
**Symptom:** Error in logs: `Connection refused (chroma_db/...)`  
**Fix:** Ensure `chroma_db_public/` and `chroma_db_internal/` directories exist and are readable by the Docker user.

### Public projection fails to sync
**Symptom:** Cron job fails; public data is stale  
**Fix:** Check that internal backend container is running; increase timeout in cron script.

### Internal stack accessible from internet
**Symptom:** Can reach internal API from outside LAN  
**Fix:** Ensure internal stack **does not** have a tunnel configured; only public stack has cloudflared service.

### Token rejected on internal stack
**Symptom:** `401 Unauthorized` even with valid token  
**Fix:** Verify token is present in `credentials.yaml` and loaded correctly; check `ALLOW_QUERY_TOKEN_AUTH` is not restricting header-based auth.

---

## 10. Future Enhancements

- [ ] Add internal tunnel (e.g., Tailscale) for secure remote access to internal stack
- [ ] Implement automatic vault sync from GitHub to NAS
- [ ] Add health monitoring / alerting (e.g., Uptime Kuma)
- [ ] Set up log aggregation and analysis (e.g., ELK stack)
- [ ] Implement disaster recovery / rollback script
