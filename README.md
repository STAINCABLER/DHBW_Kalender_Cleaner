# DHBW Calendar Cleaner

Docker-Service zur automatischen Bereinigung von DHBW/ICS-Kalendern. Filtert unerwünschte Termine per RegEx und synchronisiert stündlich mit einem Google-Kalender. Multi-User-fähig via Google OAuth.

---

## Architektur

- **Authentifizierung:** "Web Application" OAuth 2.0 Flow. Nutzer loggen sich auf Ihrer Domain ein.
- **Web-UI (Port 8000):** Für Login, Info-Seite, Disclaimer, Dashboard & Konfiguration (schreibt `/app/data/<user-id>.json`).
- **Backend (Cron):** Stündlicher Sync-Job im Container, der **alle** konfigurierten User-Dateien verarbeitet.
- **Persistence:** Das `/app/data` Verzeichnis (als Volume gemountet) enthält die verschlüsselten Konfigurationsdateien und individuellen Log-Dateien.

## Setup-Anleitung

### Schritt 1: Google Cloud Projekt (Webanwendung)

1.  Gehen Sie zur [Google Cloud Console](https://console.cloud.google.com/).
2.  Erstellen Sie ein neues Projekt und **aktivieren Sie die Google Calendar API** und die **Google People API**.
3.  Gehen Sie zu "APIs & Dienste" -> "Anmeldedaten".
4.  Klicken Sie auf "Anmeldedaten erstellen" -> "OAuth-Client-ID".
5.  Wählen Sie als Anwendungstyp **"Webanwendung"**.
6.  **Autorisierte Weiterleitungs-URIs:**
    Fügen Sie die *exakte* Callback-URL Ihrer Anwendung hinzu:
    `https://dhbw-calendar-cleaner.ptb.ltm-labs.de/authorize`
7.  Klicken Sie auf "Erstellen". Sie erhalten eine **Client-ID** und einen **Client-Geheimschlüssel**.
8.  Gehen Sie zum "OAuth-Zustimmungsbildschirm".
9.  Setzen Sie den Status auf **"In Produktion"**.
10. (Wenn Sie "Test" verwenden, fügen Sie sich selbst unter "Testbenutzer" hinzu).

### Schritt 2: Docker-Volume vorbereiten

1.  Erstellen Sie ein Verzeichnis, das als Docker-Volume dienen wird (falls Sie kein benanntes Volume wie in der `docker-compose.yml` verwenden):
    ```bash
    mkdir ./calendar-data
    ```

### Schritt 3: Docker Container starten

1.  **Generieren Sie einen starken Secret Key:**
    z.B. mit `openssl rand -base64 32`
2.  **Starten Sie den Container:**
    Dieser Befehl verwendet das von Ihnen bereitgestellte Image von GHCR. Ersetzen Sie die `...` durch Ihre echten Google-Secrets und Ihren Secret-Key.

    ```bash
    docker run -d --name calendar-cleaner \
      -p 8000:8000 \
      -v $(pwd)/calendar-data:/app/data \
      -e TZ=Europe/Berlin \
      -e APP_BASE_URL="[https://dhbw-calendar-cleaner.ptb.ltm-labs.de](https://dhbw-calendar-cleaner.ptb.ltm-labs.de)" \
      -e GOOGLE_CLIENT_ID="IHRE_CLIENT_ID_VON_GOOGLE" \
      -e GOOGLE_CLIENT_SECRET="IHR_CLIENT_SECRET_VON_GOOGLE" \
      -e SECRET_KEY="IHR_GENERIERTER_SECRET_KEY" \
      ghcr.io/staincabler/dhbw_kalender_cleaner:main
    ```
    *Alternativ: Nutzen Sie Ihre `docker-compose.yml` mit einer `.env`-Datei, um die Secrets zu verwalten.*

### Schritt 4: Reverse Proxy

Stellen Sie sicher, dass Ihr Reverse Proxy (z.B. Traefik) Anfragen für `https://dhbw-calendar-cleaner.ptb.ltm-labs.de` an `http://calendar-cleaner:8000` weiterleitet.

### Schritt 5: Nutzung

1.  Jeder Nutzer besucht `https://dhbw-calendar-cleaner.ptb.ltm-labs.de`.
2.  Klickt auf "Mit Google anmelden".
3.  Folgt den Anweisungen auf der Info-Seite (Disclaimer) und richtet das Dashboard ein.
4.  Das System synchronisiert diesen Nutzer ab sofort stündlich.