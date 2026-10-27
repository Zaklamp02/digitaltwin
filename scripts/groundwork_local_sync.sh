#!/bin/sh
# Copies the Groundwork app from this repo to ~/Practice, where the always-on local server
# (LaunchAgent; macOS won't let it read ~/Documents) serves it at http://localhost:8780.
set -e
cd "$(dirname "$0")/../frontend/public/groundwork"
cp index.html app.js art.js icons.js exercises.js workouts.js manifest.webmanifest icon-192.png icon-512.png ~/Practice/
echo "Synced Groundwork app to ~/Practice"
