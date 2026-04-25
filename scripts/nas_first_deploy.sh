#!/usr/bin/env bash
# ── Digital Twin — First NAS Deploy ──────────────────────────────────────────
# Run from your Mac: bash scripts/nas_first_deploy.sh
#
# The CF tunnel is dashboard-managed — routes are added via the CF dashboard,
# not via config.yml.  This script only needs to:
#   1. Create a shared Docker network so the tunnel can reach digital-twin
#   2. Add that network to StoryBrew's tunnel container
#   3. Deploy digital-twin
#
# After running this, add the route in the CF dashboard:
#   sebastiaandenboer.org → http://digital-twin-frontend:80
set -euo pipefail

NAS="storybrew@192.168.68.200"
NAS_PASS="Downtherabbithole2025!"
DT_PATH="/volume1/docker/digital_twin"
SB_PATH="/volume1/docker/Storybrew"
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

# Helper: run docker commands via sudo on the NAS
nas_docker() {
  ssh "$NAS" "echo '$NAS_PASS' | sudo -S $* 2>/dev/null"
}

echo "=== Step 1: Create shared Docker network on NAS ==="
nas_docker docker network create cf-tunnel-net 2>/dev/null && echo "Created cf-tunnel-net" || echo "cf-tunnel-net already exists"

echo ""
echo "=== Step 2: Add cf-tunnel-net to StoryBrew tunnel ==="
# Write a small patch script, scp -O it, run it on the NAS
cat > /tmp/patch_storybrew.py << 'PYEOF'
import sys, os

path = sys.argv[1]
with open(path) as f:
    content = f.read()

if "cf-tunnel-net" in content:
    print("StoryBrew docker-compose already has cf-tunnel-net, skipping.")
    sys.exit(0)

# Backup
with open(path + ".bak", "w") as f:
    f.write(content)

# Add cf-tunnel-net to tunnel service's networks (last occurrence before volumes:)
old = "    networks:\n      - storybrew-net\n\nvolumes:"
new = "    networks:\n      - storybrew-net\n      - cf-tunnel-net\n\nvolumes:"
content = content.replace(old, new)

# Add external network declaration
content = content.rstrip() + "\n  cf-tunnel-net:\n    external: true\n"

with open(path, "w") as f:
    f.write(content)
print("Patched StoryBrew docker-compose.yml")
PYEOF
scp -O /tmp/patch_storybrew.py "$NAS:/tmp/patch_storybrew.py"
ssh "$NAS" "python3 /tmp/patch_storybrew.py $SB_PATH/docker-compose.yml && rm /tmp/patch_storybrew.py"

echo ""
echo "=== Step 3: Create digital-twin directories on NAS ==="
ssh "$NAS" "mkdir -p $DT_PATH/{data,logs,chroma_db,memory}"

echo ""
echo "=== Step 4: Copy secrets and data to NAS ==="
echo "Copying .env..."
scp -O "$PROJECT_DIR/.env" "$NAS:$DT_PATH/.env"

echo "Copying credentials.yaml..."
scp -O "$PROJECT_DIR/credentials.yaml" "$NAS:$DT_PATH/credentials.yaml"

echo "Syncing data/..."
rsync -av --progress "$PROJECT_DIR/data/" "$NAS:$DT_PATH/data/"

echo "Syncing memory/..."
rsync -av --progress "$PROJECT_DIR/memory/" "$NAS:$DT_PATH/memory/"

echo "Syncing chroma_db/..."
rsync -av --progress "$PROJECT_DIR/chroma_db/" "$NAS:$DT_PATH/chroma_db/"

echo ""
echo "=== Step 5: Deploy digital-twin ==="
tar --no-xattrs \
    --exclude='.git' \
    --exclude='backend/__pycache__' \
    --exclude='backend/.venv' \
    --exclude='frontend/node_modules' \
    --exclude='chroma_db' \
    --exclude='data' \
    --exclude='logs' \
    --exclude='memory' \
    --exclude='.env' \
    --exclude='credentials.yaml' \
    -czf /tmp/digital-twin-deploy.tar.gz -C "$PROJECT_DIR" .
scp -O /tmp/digital-twin-deploy.tar.gz "$NAS:$DT_PATH/"
ssh "$NAS" "cd $DT_PATH && tar -xzf digital-twin-deploy.tar.gz && rm digital-twin-deploy.tar.gz"

echo ""
echo "=== Step 6: Build and start digital-twin ==="
nas_docker docker compose -f $DT_PATH/docker-compose.yml up --build -d

echo ""
echo "=== Step 7: Restart StoryBrew tunnel to join cf-tunnel-net ==="
nas_docker docker compose -f $SB_PATH/docker-compose.yml up -d

echo ""
echo "=== Step 8: Verify ==="
echo "Waiting 15 seconds for services to start..."
sleep 15
nas_docker docker ps --format "'table {{.Names}}\t{{.Status}}'" | grep -E 'digital-twin|storybrew'

echo ""
echo "=== Done! ==="
echo ""
echo "NEXT: Add route in Cloudflare dashboard (Networks → Tunnels → your tunnel):"
echo "  Public hostname: sebastiaandenboer.org"
echo "  Service: http://digital-twin-frontend:80"
echo ""
echo "Then test: curl -I https://sebastiaandenboer.org"
