#!/bin/sh

# Stellt sicher, dass das Skript bei einem Fehler abbricht
set -e

# Supercronic im Hintergrund starten
# (erbt automatisch alle Umgebungsvariablen, kein cron_env nötig)
echo "Starte Supercronic (Scheduler)..."
supercronic /app/crontab &

# Gunicorn starten
echo "Starte Web-Server auf Port 8000..."
exec gunicorn --workers 2 --bind 0.0.0.0:8000 "web_server:get_app()" --log-file - --log-level info