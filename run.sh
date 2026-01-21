#!/bin/sh

# Stellt sicher, dass das Skript bei einem Fehler abbricht
set -e

echo "Speichere Umgebungsvariablen für cron..."
touch /app/cron_env
echo > /app/cron_env

# Umgebungsvariablen exportieren
echo "export APP_BASE_URL=\"${APP_BASE_URL}\"" >> /app/cron_env
echo "export GOOGLE_CLIENT_ID=\"${GOOGLE_CLIENT_ID}\"" >> /app/cron_env
echo "export GOOGLE_CLIENT_SECRET=\"${GOOGLE_CLIENT_SECRET}\"" >> /app/cron_env
echo "export SECRET_KEY=\"${SECRET_KEY}\"" >> /app/cron_env
echo "export TZ=\"${TZ}\"" >> /app/cron_env

chmod 0644 /app/cron_env

# Starte den Cron-Daemon im Hintergrund
echo "Starte cron daemon..."
cron

# Gunicorn starten
echo "Starte Web-Server auf Port 8000..."
exec gunicorn --workers 2 --bind 0.0.0.0:8000 "web_server:get_app()" --log-file - --log-level info