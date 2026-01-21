# Python 3.11 Basis-Image
FROM python:3.11-slim

# Python-Optimierungen für Container
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Systemabhängigkeiten: cron, curl (Healthcheck), coreutils (tee)
RUN apt-get update && apt-get install -y --no-install-recommends \
    cron \
    curl \
    coreutils \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Non-Root User für Sicherheit
RUN groupadd --gid 1000 appgroup \
    && useradd --uid 1000 --gid appgroup --shell /bin/bash --create-home appuser

# Setze das Arbeitsverzeichnis
WORKDIR /app

# Dependencies installieren
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Anwendungscode kopieren
COPY . .

# Image aufräumen
RUN rm requirements.txt

# Datenverzeichnis und Log-Datei erstellen
RUN mkdir -p /app/data && touch /app/data/sync.log

# Crontab einrichten
COPY crontab /etc/cron.d/sync-cron
RUN chmod 0644 /etc/cron.d/sync-cron
RUN crontab /etc/cron.d/sync-cron

# Start-Skript ausführbar machen
RUN chmod +x run.sh

# Dateiberechtigungen setzen
RUN chown -R appuser:appgroup /app

# Web-Port
EXPOSE 8000

# Healthcheck für Container-Orchestrierung
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Container starten (cron + gunicorn)
CMD ["./run.sh"]