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

1. **Code** to the NAS, as usual (see `NAS_DEPLOYMENT_INTERNAL.md`): rsync this repo to
   `/volume1/docker/shared-code/`.
2. **Media**, once (and again when videos are added):

   ```bash
   rsync -av ~/Practice/library/ Storybrew@192.168.68.200:/volume1/docker/groundwork_media/
   ```

3. **Rebuild** both runtimes (needs sudo on the NAS):

   ```bash
   ssh -t Storybrew@192.168.68.200 'cd /volume1/docker/digital_twin_internal && sudo docker compose up -d --build && cd ../digital_twin_public && sudo docker compose up -d --build'
   ```

4. The next vault poll (≤5 min) writes `state.json`; or trigger a sync from the admin page.
   Check `https://sebastiaandenboer.org/groundwork/`.

## Local development

`~/Practice/server.py` runs the same app in local (read-write) mode at `http://localhost:8780`,
reading the vault directly. Copy `frontend/public/groundwork/*.js` over when changing the app there,
until the local runner is retired.
