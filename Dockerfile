# Python 3.11 Basis-Image
FROM python:3.11-slim

# ===== Security Labels (OCI Standard) =====
LABEL org.opencontainers.image.title="DHBW Calendar Cleaner" \
      org.opencontainers.image.description="Sanitizes DHBW calendars and syncs to Google Calendar" \
      org.opencontainers.image.vendor="STAINCABLER" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.source="https://github.com/STAINCABLER/DHBW_Calendar_Cleaner" \
      # Security-relevante Labels
      maintainer="STAINCABLER" \
      security.privileged="false" \
      security.non-root="true"

# Python-Optimierungen für Container
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    # Verhindert pip Warnungen und reduziert Attack Surface
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_ROOT_USER_ACTION=ignore \
    # Python Security Hardening
    PYTHONHASHSEED=random

# Supercronic Version (cron-Ersatz für Container, läuft als non-root)
# SHA1 Checksums von https://github.com/aptible/supercronic/releases/tag/v0.2.33
ARG SUPERCRONIC_VERSION=v0.2.33
ARG SUPERCRONIC_SHA1SUM_AMD64=71b0d58cc53f6bd72cf2f293e09e294b79c666d8
ARG SUPERCRONIC_SHA1SUM_ARM64=e0f0c06ebc5627e43b25475711e694450489ab00
ARG TARGETARCH

# Systemabhängigkeiten: curl (Healthcheck), coreutils (tee)
# --no-install-recommends minimiert installierte Pakete
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    coreutils \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean \
    # Entferne unnötige Dateien für kleineres Image
    && rm -rf /var/cache/apt/archives /var/log/apt /var/log/dpkg.log

# Supercronic installieren mit SHA1-Checksum-Verifikation (offizielle Checksums)
RUN set -eux; \
    case "${TARGETARCH}" in \
        amd64) SUPERCRONIC_SHA1SUM="${SUPERCRONIC_SHA1SUM_AMD64}" ;; \
        arm64) SUPERCRONIC_SHA1SUM="${SUPERCRONIC_SHA1SUM_ARM64}" ;; \
        *) echo "Unsupported architecture: ${TARGETARCH}" && exit 1 ;; \
    esac; \
    SUPERCRONIC="supercronic-linux-${TARGETARCH}"; \
    curl -fsSLO "https://github.com/aptible/supercronic/releases/download/${SUPERCRONIC_VERSION}/${SUPERCRONIC}"; \
    echo "${SUPERCRONIC_SHA1SUM}  ${SUPERCRONIC}" | sha1sum -c -; \
    chmod +x "${SUPERCRONIC}"; \
    mv "${SUPERCRONIC}" /usr/local/bin/supercronic

# Non-Root User für Sicherheit (ohne Login-Shell für zusätzliche Härtung)
RUN groupadd --gid 1000 appgroup \
    && useradd --uid 1000 --gid appgroup --shell /usr/sbin/nologin --no-create-home appuser

# Setze das Arbeitsverzeichnis
WORKDIR /app

# Dependencies installieren (als root, dann aufräumen)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    # Entferne pip cache und unnötige Dateien
    && rm -rf /root/.cache /tmp/* \
    && find /usr/local -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true

# Anwendungscode kopieren
COPY . .

# Image aufräumen und Berechtigungen setzen
RUN rm -f requirements.txt \
    # Datenverzeichnis erstellen
    && mkdir -p /app/data \
    # Crontab Berechtigungen
    && chmod 0644 /app/crontab \
    # Start-Skript ausführbar machen
    && chmod +x run.sh \
    # Nur Anwendungscode lesbar, data beschreibbar
    && chown -R appuser:appgroup /app \
    && chmod -R 755 /app \
    && chmod 700 /app/data \
    # Entferne Write-Permissions auf Code (Immutable Infrastructure)
    && chmod -R a-w /app/*.py /app/templates /app/static /app/content 2>/dev/null || true

# Als non-root User ausführen
USER appuser

# Web-Port
EXPOSE 8000

# Healthcheck für Container-Orchestrierung
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Container starten (cron + gunicorn)
CMD ["./run.sh"]