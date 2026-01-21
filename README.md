# DHBW Calendar Cleaner

[![Docker Build](https://github.com/STAINCABLER/DHBW_Calendar_Cleaner/actions/workflows/docker-build-container.yml/badge.svg)](https://github.com/STAINCABLER/DHBW_Calendar_Cleaner/actions/workflows/docker-build-container.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Docker Pulls](https://img.shields.io/badge/ghcr.io-available-blue)](https://github.com/STAINCABLER/DHBW_Calendar_Cleaner/pkgs/container/dhbw_calendar_cleaner)

Docker-Service zur automatischen Bereinigung von DHBW/ICS-Kalendern. Filtert unerwünschte Termine per RegEx und synchronisiert stündlich mit einem Google-Kalender. Multi-User-fähig via Google OAuth.

---

## Features

- **Automatische Synchronisation** – Stündlicher Cronjob hält deinen Kalender aktuell (dank Delta-Sync effizient)
- **RegEx-Filter** – Filtere unerwünschte Vorlesungen nach Titel
- **ICS & Google Calendar** – Unterstützt ICS-URLs (z.B. DHBW Rapla) und Google Kalender als Quelle
- **Multi-User** – Mehrere Nutzer mit eigenen Google-Konten und Filtern
- **Sicher** – CSRF-Schutz, Rate Limiting, verschlüsselte Tokens, Security Headers
- **Docker-Ready** – Einfaches Deployment mit Docker/Docker Compose
- **Multi-Arch** – Läuft auf amd64 und arm64 (Raspberry Pi)

## Architektur

```text
┌─────────────────────────────────────────────────────────────┐
│                    Docker Container                         │
│  ┌─────────────────┐    ┌─────────────────────────────────┐ │
│  │    Gunicorn     │    │           Cron Daemon           │ │
│  │   (Port 8000)   │    │     (Stündlicher Sync-Job)      │ │
│  │                 │    │                                 │ │
│  │  ┌───────────┐  │    │  ┌───────────────────────────┐  │ │
│  │  │ Flask App │  │    │  │   sync_all_users.py       │  │ │
│  │  │ + OAuth   │  │    │  │   (CalendarSyncer)        │  │ │
│  │  └───────────┘  │    │  └───────────────────────────┘  │ │
│  └─────────────────┘    └─────────────────────────────────┘ │
│                              │                              │
│                    ┌─────────▼─────────┐                    │
│                    │   /app/data/      │                    │
│                    │   (Volume Mount)  │                    │
│                    │   - user.json     │                    │
│                    │   - user.log      │                    │
│                    └───────────────────┘                    │
└─────────────────────────────────────────────────────────────┘
```

- **Web-UI (Port 8000):** Login, Dashboard, Konfiguration
- **Backend (Cron):** Stündlicher Sync für alle User
- **Persistence:** `/app/data` Volume für User-Configs und Logs

---

## Quick Start

### Voraussetzungen

1. Docker installiert
2. Google Cloud Projekt mit aktivierter **Calendar API** und **People API**
3. OAuth 2.0 Client-ID (Webanwendung) mit Redirect-URI: `https://deine-domain.de/authorize`

### Docker Compose (empfohlen)

```yaml
version: '3.8'
services:
  calendar-cleaner:
    image: ghcr.io/staincabler/dhbw_calendar_cleaner:latest
    container_name: calendar-cleaner
    restart: unless-stopped
    ports:
      - "8000:8000"
    volumes:
      - ./calendar-data:/app/data
    environment:
      - TZ=Europe/Berlin
      - APP_BASE_URL=https://deine-domain.de
      - GOOGLE_CLIENT_ID=deine-client-id
      - GOOGLE_CLIENT_SECRET=dein-client-secret
      - SECRET_KEY=dein-secret-key  # openssl rand -base64 32
```

```bash
docker compose up -d
```

### Docker Run

```bash
docker run -d --name calendar-cleaner \
  -p 8000:8000 \
  -v $(pwd)/calendar-data:/app/data \
  -e TZ=Europe/Berlin \
  -e APP_BASE_URL="https://deine-domain.de" \
  -e GOOGLE_CLIENT_ID="..." \
  -e GOOGLE_CLIENT_SECRET="..." \
  -e SECRET_KEY="$(openssl rand -base64 32)" \
  ghcr.io/staincabler/dhbw_calendar_cleaner:latest
```

---

## Konfiguration

### Umgebungsvariablen

| Variable | Beschreibung | Beispiel |
| -------- | ------------ | -------- |
| `APP_BASE_URL` | Öffentliche URL der Anwendung | `https://calendar.example.com` |
| `GOOGLE_CLIENT_ID` | OAuth Client-ID von Google Cloud | `123...apps.googleusercontent.com` |
| `GOOGLE_CLIENT_SECRET` | OAuth Client-Secret | `GOCSPX-...` |
| `SECRET_KEY` | 32-Byte Base64-Key für Verschlüsselung | `openssl rand -base64 32` |
| `TZ` | Zeitzone für Cron und Logs | `Europe/Berlin` |

### Google Cloud Setup

1. [Google Cloud Console](https://console.cloud.google.com/) öffnen
2. Neues Projekt erstellen
3. **APIs aktivieren:** Calendar API, People API
4. **OAuth-Client erstellen:**
   - Anwendungstyp: Webanwendung
   - Redirect-URI: `https://deine-domain.de/authorize`
5. **OAuth-Zustimmungsbildschirm:** Status auf "In Produktion" setzen

---

## Sicherheit

Dieses Projekt implementiert mehrere Sicherheitsmaßnahmen:

| Feature | Technologie |
| ------- | ----------- |
| CSRF-Schutz | Flask-WTF |
| Security Headers | Flask-Talisman (HSTS, CSP) |
| Rate Limiting | Flask-Limiter |
| Token-Verschlüsselung | Fernet (AES-128) |
| Vulnerability Scanning | Trivy in CI/CD |
| Secure Cookies | HttpOnly, Secure Flags |

Für Sicherheitsmeldungen siehe [SECURITY.md](SECURITY.md).

---

## Versionen & Tags

| Tag | Beschreibung |
| --- | ------------ |
| `latest` | Aktuellste stabile Version |
| `main` | Aktueller Stand des main-Branch |
| `vX.Y.Z` | Spezifische Versionen (durch Dependabot-Updates) |
| `sha-abc1234` | Spezifischer Commit |

---

## Entwicklung

```bash
# Repository klonen
git clone https://github.com/STAINCABLER/DHBW_Calendar_Cleaner.git
cd DHBW_Calendar_Cleaner

# Lokales Setup
cp .env.example .env
# .env bearbeiten mit echten Werten

# Container bauen und starten
docker build -t calendar-cleaner .
docker run -p 8000:8000 --env-file .env -v ./data:/app/data calendar-cleaner
```

---

## Lizenz

Dieses Projekt ist unter der [MIT-Lizenz](LICENSE) lizenziert.

---

## Credits

Entwickelt von [Tobias Maimone](https://thulium-labs.de)
