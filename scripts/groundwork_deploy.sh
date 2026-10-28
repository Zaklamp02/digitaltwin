#!/bin/sh
# Deploys the Groundwork app to the NAS: stamps a fresh ?v= on the script tags (Cloudflare and
# browsers cache .js for hours, but index.html is never cached, so new tags load new files at once),
# copies the app into shared-code, then prints the rebuild command (it needs your sudo password).
set -e
cd "$(dirname "$0")/.."
V=$(date +%Y%m%d%H%M)
sed -i '' -E "s/(src=\"(art|icons|exercises|workouts|app)\.js)(\?v=[0-9]+)?\"/\1?v=$V\"/" frontend/public/groundwork/index.html
COPYFILE_DISABLE=1 tar --no-xattrs -cf - frontend/public/groundwork | ssh Storybrew@192.168.68.200 'tar -xf - -C /volume1/docker/shared-code'
echo "Copied Groundwork (v=$V). Now rebuild the public frontend:"
echo "  ssh -t Storybrew@192.168.68.200 'cd /volume1/docker/digital_twin_public && sudo COMPOSE_DOCKER_CLI_BUILD=1 DOCKER_BUILDKIT=1 docker-compose up -d --build frontend-public'"
