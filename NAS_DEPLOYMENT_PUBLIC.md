# NAS Dual-Runtime Deployment Guide — Public Template

This guide provides a **template** for deploying the Digital Twin on your own NAS with separate public and internal runtimes. Replace all placeholders with your actual infrastructure values.

> **For Sebastiaan's setup:** See `NAS_DEPLOYMENT_INTERNAL.md` (private documentation) for specific IP addresses, paths, and credentials.

---

## 1. Prerequisites

You will need:

- A Synology NAS (or similar Docker-capable NAS) with SSH access
- Docker and Docker Compose installed on the NAS
- A domain name (e.g., `your-domain.com`)
- Cloudflare account (free tier sufficient) for DNS and Tunnel
- The Digital Twin source code deployed to your NAS

---

## 2. Deployment Architecture

```
                    ┌─────────────────────────────────────┐
                    │  Your Cloudflare Account            │
                    │  └─ Tunnel: <YOUR_DOMAIN>           │
                    │  └─ DNS: CNAME to Cloudflare        │
                    └────────────┬────────────────────────┘
                                 │
                    ┌────────────▼────────────────────────┐
                    │  Your NAS at <YOUR_NAS_IP>          │
                    │  /<YOUR_DEPLOY_PATH>/               │
                    └────────────────────────────────────┘
                           │
         ┌─────────────────┼─────────────────┐
         │                 │                 │
    ┌────▼─────────┐  ┌────▼─────────┐      │
    │ Public Stack │  │ Internal      │      │
    │ (visitors)   │  │ Stack (owner) │      │
    └──────────────┘  └───────────────┘      │
         │                 │                 │
    Port 8080         Port 8081          Shared
    APP_MODE=public   APP_MODE=internal  code &
    Public DB         Full DB            secrets
    Public Chroma     Full Chroma
```

---

## 3. Setup Steps

### 3.1. Prepare your NAS directory structure

```bash
# SSH into your NAS
ssh <NAS_USER>@<YOUR_NAS_IP>

# Create directories (adjust path as needed for your NAS)
mkdir -p <YOUR_DEPLOY_PATH>/digital_twin_public/{.cloudflared,data_public,chroma_db_public,logs}
mkdir -p <YOUR_DEPLOY_PATH>/digital_twin_internal/{vault,data_internal,chroma_db_internal,logs_internal}
mkdir -p <YOUR_DEPLOY_PATH>/shared-code
mkdir -p <YOUR_DEPLOY_PATH>/cron-jobs

# Set permissions
chmod 700 <YOUR_DEPLOY_PATH>/digital_twin_public/.cloudflared
chmod 700 <YOUR_DEPLOY_PATH>/digital_twin_internal
```

### 3.2. Deploy code to NAS

From your development machine:

```bash
# Copy the codebase to NAS (excluding data, credentials, node_modules)
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
  . <NAS_USER>@<YOUR_NAS_IP>:<YOUR_DEPLOY_PATH>/shared-code/
```

### 3.3. Create symlinks on NAS

```bash
# SSH to NAS
ssh <NAS_USER>@<YOUR_NAS_IP>

# Create symlinks for public stack
cd <YOUR_DEPLOY_PATH>/digital_twin_public
ln -s ../shared-code/frontend frontend
ln -s ../shared-code/backend backend
ln -s ../shared-code/scripts scripts
ln -s ../shared-code/docker-compose.public.yml .
ln -s docker-compose.public.yml docker-compose.yml
ln -s ../.env .env                    # (symlink to shared secrets)
ln -s ../credentials.yaml credentials.yaml

# Create symlinks for internal stack
cd <YOUR_DEPLOY_PATH>/digital_twin_internal
ln -s ../shared-code/frontend frontend
ln -s ../shared-code/backend backend
ln -s ../shared-code/scripts scripts
ln -s ../shared-code/docker-compose.internal.yml .
ln -s docker-compose.internal.yml docker-compose.yml
ln -s ../.env .env                    # (symlink to shared secrets)
ln -s ../credentials.yaml credentials.yaml
```

### 3.4. Deploy secrets (one-time, from dev machine)

> **CRITICAL:** These files are never committed to Git.

```bash
# Copy .env with your actual API keys (never commit this)
scp .env <NAS_USER>@<YOUR_NAS_IP>:<YOUR_DEPLOY_PATH>/.env

# Copy credentials.yaml with your access tokens
scp credentials.yaml <NAS_USER>@<YOUR_NAS_IP>:<YOUR_DEPLOY_PATH>/credentials.yaml

# Set restrictive permissions
ssh <NAS_USER>@<YOUR_NAS_IP> "chmod 600 <YOUR_DEPLOY_PATH>/.env <YOUR_DEPLOY_PATH>/credentials.yaml"
```

### 3.5. Set up Cloudflare Tunnel

From your development machine (assumes you're already logged into Cloudflare):

```bash
# Create a new tunnel for this domain
cloudflared tunnel create <YOUR_TUNNEL_NAME>

# This outputs a tunnel ID and creates credentials
# Copy the credentials file and cert to NAS
TUNNEL_ID=$(cloudflared tunnel list | grep <YOUR_TUNNEL_NAME> | awk '{print $1}')
scp ~/.cloudflared/${TUNNEL_ID}.json <NAS_USER>@<YOUR_NAS_IP>:<YOUR_DEPLOY_PATH>/digital_twin_public/.cloudflared/
scp ~/.cloudflared/cert.pem <NAS_USER>@<YOUR_NAS_IP>:<YOUR_DEPLOY_PATH>/digital_twin_public/.cloudflared/

# Create DNS routing
cloudflared tunnel route dns <YOUR_TUNNEL_NAME> <YOUR_DOMAIN>
cloudflared tunnel route dns <YOUR_TUNNEL_NAME> www.<YOUR_DOMAIN>
```

### 3.6. Create Cloudflare config on NAS

On your NAS, create `.cloudflared/config.yml`:

```bash
cat > <YOUR_DEPLOY_PATH>/digital_twin_public/.cloudflared/config.yml << 'EOF'
tunnel: <YOUR_TUNNEL_ID>
credentials-file: /etc/cloudflared/<YOUR_TUNNEL_ID>.json

ingress:
  - hostname: <YOUR_DOMAIN>
    service: http://frontend-public:80
  - hostname: www.<YOUR_DOMAIN>
    service: http://frontend-public:80
  - service: http_status:404
EOF
```

---

## 4. Running the Stacks

### 4.1. Start both runtimes

```bash
# SSH to NAS
ssh <NAS_USER>@<YOUR_NAS_IP>

# Terminal 1: Start public stack
cd <YOUR_DEPLOY_PATH>/digital_twin_public
docker compose up -d

# Terminal 2: Start internal stack
cd <YOUR_DEPLOY_PATH>/digital_twin_internal
docker compose up -d

# Verify both are running
docker ps | grep digital-twin
```

### 4.2. Access your deployment

**Public stack:**
- Online: `https://<YOUR_DOMAIN>` (via Cloudflare Tunnel)
- Local (for debugging): `http://<YOUR_NAS_IP>:8080`

**Internal stack:**
- Local LAN only: `http://<YOUR_NAS_IP>:8081` (requires token auth)

---

## 5. Publishing Public Data

To keep the public dataset synchronized with only public-role content:

```bash
# From your development machine
make publish-projection

# Or manually on NAS:
ssh <NAS_USER>@<YOUR_NAS_IP> << 'EOF'
cd <YOUR_DEPLOY_PATH>/digital_twin_internal
docker compose exec backend-internal python scripts/publish_public_projection.py \
  --internal-db /app/data_internal/knowledge.db \
  --public-db <YOUR_DEPLOY_PATH>/digital_twin_public/data_public/knowledge.db \
  --internal-chroma /app/chroma_db_internal \
  --public-chroma <YOUR_DEPLOY_PATH>/digital_twin_public/chroma_db_public
docker compose -f <YOUR_DEPLOY_PATH>/digital_twin_public/docker-compose.yml restart backend-public
EOF
```

**Automate with cron** (daily at 2 AM):

```bash
ssh <NAS_USER>@<YOUR_NAS_IP>

# Create publish script
cat > <YOUR_DEPLOY_PATH>/cron-jobs/publish-projection.sh << 'EOF'
#!/bin/bash
INTERNAL_STACK=<YOUR_DEPLOY_PATH>/digital_twin_internal
PUBLIC_STACK=<YOUR_DEPLOY_PATH>/digital_twin_public
cd $INTERNAL_STACK
docker compose exec -T backend-internal python scripts/publish_public_projection.py \
  --internal-db /app/data_internal/knowledge.db \
  --public-db ${PUBLIC_STACK}/data_public/knowledge.db \
  --internal-chroma /app/chroma_db_internal \
  --public-chroma ${PUBLIC_STACK}/chroma_db_public
cd $PUBLIC_STACK
docker compose restart backend-public
echo "$(date): Public projection published" >> <YOUR_DEPLOY_PATH>/cron-jobs/projection.log
EOF

chmod +x <YOUR_DEPLOY_PATH>/cron-jobs/publish-projection.sh

# Add to crontab (0 2 * * * = 2 AM daily)
(crontab -l 2>/dev/null; echo "0 2 * * * <YOUR_DEPLOY_PATH>/cron-jobs/publish-projection.sh") | crontab -
```

---

## 6. Monitoring

```bash
# Check stack status
ssh <NAS_USER>@<YOUR_NAS_IP> \
  "cd <YOUR_DEPLOY_PATH>/digital_twin_public && docker compose ps"

# View public logs
ssh <NAS_USER>@<YOUR_NAS_IP> \
  "cd <YOUR_DEPLOY_PATH>/digital_twin_public && docker compose logs -f --tail=50"

# View internal logs
ssh <NAS_USER>@<YOUR_NAS_IP> \
  "cd <YOUR_DEPLOY_PATH>/digital_twin_internal && docker compose logs -f --tail=50"

# Check disk usage
ssh <NAS_USER>@<YOUR_NAS_IP> \
  "du -sh <YOUR_DEPLOY_PATH>/digital_twin_public/data_public"
```

---

## 7. Security Checklist

- [ ] Rotate all API keys (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`) before first launch
- [ ] Cloudflare credentials stored only on NAS, not in Git
- [ ] `.env` and `credentials.yaml` in `.gitignore` and never committed
- [ ] Cloudflare Access policies set up for `/admin` routes (email OTP or SSO)
- [ ] Test public stack with invalid token → should receive 401 or public-only data
- [ ] Test internal stack with valid token → should receive full data access

---

## 8. Troubleshooting

**Public stack not accessible from internet**
- Check Cloudflare tunnel is running: `docker compose ps` in public stack dir
- Check DNS is configured: `dig <YOUR_DOMAIN>`
- Check backend health: `curl http://frontend-public:80`

**Internal stack not accessible from LAN**
- Check internal stack is running: `docker ps | grep internal`
- Check firewall allows port 8081
- Verify token is present: `cat credentials.yaml`

**Projection sync fails**
- Ensure internal backend is running
- Check disk space on NAS
- Review logs: `docker compose logs backend-internal`

---

## 9. Template Placeholders

Replace these in all commands above:

| Placeholder | Example | Description |
|---|---|---|
| `<YOUR_NAS_IP>` | `192.168.1.100` | NAS IP address (LAN) |
| `<NAS_USER>` | `admin` | NAS SSH username |
| `<YOUR_DEPLOY_PATH>` | `/volume1/docker` | Root deployment directory on NAS |
| `<YOUR_DOMAIN>` | `my-twin.com` | Your domain name |
| `<YOUR_TUNNEL_NAME>` | `digital-twin` | Cloudflare tunnel name |
| `<YOUR_TUNNEL_ID>` | `abc-123-def` | Cloudflare tunnel UUID |

---

## 10. Next Steps

- Configure Cloudflare Access for `/admin` routes (requires paid CF plan or free trial)
- Set up monitoring/alerting for NAS health
- Plan backup strategy for internal database
- Document your custom configuration for reference

