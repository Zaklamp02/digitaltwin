# Groundwork: training page at /groundwork

A read-only training app on the public site: today's routine, the plan calendar, routines with video,
and the exercise library. Data flows one way, from the vault to the site; the site never writes back.

## How it fits together

| Piece | Where |
| --- | --- |
| App (static HTML/JS) | `frontend/public/groundwork/` → served by nginx at `/groundwork/` |
| Data export | `backend/app/groundwork.py` → `export_public_groundwork()` runs next to the family-tree export after each vault sync on the internal runtime and writes `data_public/groundwork/state.json` |
| Data API | `GET /api/groundwork/state` on the public backend (adds `today`) |
| Video library (463 MB, 317 videos + posters + `exercises.json`) | `/volume1/docker/groundwork_media/` on the NAS, mounted read-only into `frontend-public` and served at `/groundwork/library/` (not in git, not in the vault) |

Exported notes (each only if its frontmatter says `visibility: public`):
`Hobbies/Sports/Training Plan.md`, `Running Log.md` (last 150 days), `Strength Log.md`, and
`Hobbies/Sports/Groundwork/{sessions,settings}.json` (gated on `Groundwork/README.md`).
Races come from the plan's bold entries, so the private Upcoming Races note stays private.

Per-device choices on the site (location, voice, beeps) are kept in the browser's localStorage.

## Deploy

App changes (anything in `frontend/public/groundwork/`):

```bash
scripts/groundwork_deploy.sh
```

It stamps a fresh `?v=` on the script tags, copies the app to the NAS, and prints the rebuild
command for `frontend-public` (needs your sudo password on the NAS). The stamp matters: Cloudflare and
browsers cache `.js` for 4 hours, while `index.html` is never cached, so new tags load the new files
immediately.

Backend changes (`backend/app/groundwork.py`): copy the repo to `/volume1/docker/shared-code/` (see
`NAS_DEPLOYMENT_INTERNAL.md`) and rebuild both runtimes with
`sudo COMPOSE_DOCKER_CLI_BUILD=1 DOCKER_BUILDKIT=1 docker-compose up -d --build` (the NAS has
docker-compose 1.28). The NAS rsync service is off, so copies go over SSH with tar.

Media (once, and when videos are added):

```bash
cd ~/Practice/library && tar -cf - . | ssh Storybrew@192.168.68.200 'tar -xf - -C /volume1/docker/groundwork_media'
```

Plan, routines and logs need no deploy: they live in the vault and reach the site after the next
vault sync (≤10 min).

## Local development

`~/Practice/server.py` runs the same app in local (read-write) mode at `http://localhost:8780`,
reading the vault directly. Copy `frontend/public/groundwork/*.js` over when changing the app there,
until the local runner is retired.
