# Verwende ein schlankes Python-Basisimage
FROM python:3.11-slim

# Installiere Systemabhängigkeiten: cron
RUN apt-get update && apt-get install -y cron && rm -rf /var/lib/apt/lists/*

# Setze das Arbeitsverzeichnis
WORKDIR /app

# Kopiere die Abhängigkeitsliste und installiere sie
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Kopiere den gesamten Anwendungscode
COPY . .

# Erstelle das Datenverzeichnis (Mount-Punkt)
# und die Log-Datei, auf die Cron schreiben kann
RUN mkdir -p /app/data && touch /app/data/sync.log

# Kopiere die Crontab-Datei und setze Berechtigungen
COPY crontab /etc/cron.d/sync-cron
RUN chmod 0644 /etc/cron.d/sync-cron
RUN crontab /etc/cron.d/sync-cron

# Mache das Start-Skript ausführbar
RUN chmod +x run.sh

# Port für das Web-UI freigeben
EXPOSE 8000

# Container-Startbefehl
CMD ["./run.sh"]