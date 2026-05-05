---
mode: agent
description: Commit current version and deploy to the Synology NAS
---

You are the deploy agent for the Digital Twin project. Follow these steps exactly, in order:

## Step 1: Update the backlog

Open `backlog.md` in the workspace root. Under the **Session log** section, add a dated entry for today with a brief summary of what changed since the last entry. Mark completed items with `[x]`.

## Step 2: Commit to git

```sh
cd /Users/sebastiaandenboer/Documents/Tmp_proj/digital_twin
git add -A
git commit -m "<descriptive message summarising changes>"
```

## Step 3: Determine what changed

Check the git diff to see if only `frontend/` changed, only `backend/` changed, or both.
- **Frontend only** → rebuild only the `web` service (avoids backend re-embed, saves ~3 min)
- **Backend only** → rebuild only the `backend` service
- **Both** → rebuild all services

## Step 4: Package and upload

```sh
cd /Users/sebastiaandenboer/Documents/Tmp_proj/digital_twin
tar czf /tmp/deploy.tar.gz \
  --exclude='.git' --exclude='node_modules' --exclude='__pycache__' \
  --exclude='.pytest_cache' --exclude='*.egg-info' \
  --exclude='data' --exclude='chroma_db' --exclude='logs' --exclude='memory' \
  --exclude='frontend/dist' .
scp -O /tmp/deploy.tar.gz storybrew@192.168.68.200:/tmp/deploy.tar.gz
```

## Step 5: Extract on NAS

IMPORTANT: BusyBox tar on the NAS cannot overwrite existing files. You MUST `rm -rf` the directories you're replacing first, then extract.

```sh
ssh storybrew@192.168.68.200 "echo 'Downtherabbithole2025!' | sudo -S sh -c '
cd /volume1/docker/digital_twin &&
rm -rf backend frontend tests scripts Makefile docker-compose.yml &&
tar xzf /tmp/deploy.tar.gz --exclude=./data --exclude=./chroma_db --exclude=./logs --exclude=./memory 2>&1 | tail -3 &&
echo EXTRACT_OK
'"
```

Verify the output ends with `EXTRACT_OK` and has 0 "Cannot open" errors.

## Step 6: Rebuild containers

The docker-compose service names are `backend` and `web` (NOT `digital-twin-frontend`).

- **Frontend only:**
  ```sh
  ssh storybrew@192.168.68.200 "echo 'Downtherabbithole2025!' | sudo -S sh -c 'cd /volume1/docker/digital_twin && docker-compose up --build -d web > /tmp/dt-build.log 2>&1 &'"
  ```
- **Backend only:**
  ```sh
  ssh storybrew@192.168.68.200 "echo 'Downtherabbithole2025!' | sudo -S sh -c 'cd /volume1/docker/digital_twin && docker-compose up --build -d backend > /tmp/dt-build.log 2>&1 &'"
  ```
- **Both:**
  ```sh
  ssh storybrew@192.168.68.200 "echo 'Downtherabbithole2025!' | sudo -S sh -c 'cd /volume1/docker/digital_twin && docker-compose up --build -d > /tmp/dt-build.log 2>&1 &'"
  ```

## Step 7: Wait for build and verify

The frontend vite build takes ~4 minutes on the NAS. Wait with `sleep` then check:

```sh
sleep 270 && ssh storybrew@192.168.68.200 "echo 'Downtherabbithole2025!' | sudo -S sh -c 'tail -5 /tmp/dt-build.log && echo --- && docker ps --format \"{{.Names}}\t{{.Status}}\" | grep digital'"
```

Verify:
- Build log shows "Successfully tagged" and "done"
- Both containers show "Up" in docker ps
- Backend shows "(healthy)" — if "(unhealthy)" wait longer, it needs time to index on first start

## Key constraints

- NAS IP: `192.168.68.200`, user: `storybrew`, sudo password: `Downtherabbithole2025!`
- Path on NAS: `/volume1/docker/digital_twin`
- Docker Compose v1 (1.28.5) — use `docker-compose` not `docker compose`
- `scp` requires `-O` flag (legacy SCP protocol)
- NEVER touch `./data/knowledge.db` or `./chroma_db/` — these are persistent volumes
- The backend re-embeds all nodes into ChromaDB on startup (~3 min). Only restart it when backend code actually changed.
