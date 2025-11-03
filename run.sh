#!/bin/sh
set -e
echo "Starte cron daemon..."
cron
echo "Starte Web-Server auf Port 8000..."
exec gunicorn --workers 2 --bind 0.0.0.0:8000 "web_server:get_app()" --log-file - --log-level warning