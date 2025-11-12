## Overview
- Containerized Flask service that sanitizes DHBW calendars via regex and resyncs into Google; backend logic lives in `sync_logic.py`, web UI in `web_server.py` plus `templates/`.
- Docker image boots via `run.sh`, combining a Gunicorn web tier and cron-driven worker that share `/app/data` for configs and logs.
- Tailored for multi-user Google OAuth, so flows, storage, and locking assume per-user isolation rather than global settings.

## Runtime Architecture
- `run.sh` snapshots env vars into `/app/cron_env`, starts `cron`, then launches `gunicorn --workers 2 --bind 0.0.0.0:8000 web_server:get_app()`.
- `crontab` schedules `/app/sync_all_users.py` every 8 hours at minute 0, redirecting output into `/app/data/system.log`; manual syncs reuse the same script with `--user`.
- Web layer expects an external reverse proxy terminating TLS and calling the service at port 8000 with `APP_BASE_URL` matching the public origin.

## Data & Persistence
- Volume-mounted `/app/data` stores `<user-id>.json` configs plus `<user-id>.log` tails; JSON holds `email`, `source_id`, `target_id`, `regex_patterns`, `source_timezone`, `refresh_token_encrypted`, `has_accepted_disclaimer`.
- `CalendarSyncer.log()` writes to both stdout and the per-user log file; UI polls `/logs` to stream the last 50 lines, so avoid breaking line-based formatting.
- `.sync.lock` files are managed via `filelock.FileLock` to prevent concurrent runs per user—respect this pattern when adding new background tasks.

## Auth & Google API
- OAuth handled in `web_server.py:get_app()` using `google_auth_oauthlib.flow.Flow` with redirect `{APP_BASE_URL}/authorize` and scopes defined in `SCOPES`.
- Tokens are encrypted with `cryptography.Fernet` using `SECRET_KEY` (must remain a 32-byte base64 string); rotating this key invalidates every stored refresh token.
- `sync_all_users.build_credentials()` decrypts the refresh token, refreshes it via `google.auth.transport.requests.GoogleRequest`, and builds a discovery client; no service accounts are involved.

## Sync Logic
- `CalendarSyncer.run_sync()` treats `source_id` beginning with `http` as ICS; otherwise it calls Google Calendar APIs, always syncing the full history unless you add explicit time windows.
- `fetch_ics_events()` rebinds naive ICS timestamps to `config['source_timezone']` using Arrow and deduplicates by UID before filtering.
- `sync_to_target()` deletes all target events within the window then re-inserts; it already retries select `HttpError` cases, so add new API calls inside the same retry discipline.

## Web UI Patterns
- Templates under `templates/` use Tailwind via CDN and Flask-Login’s `current_user`; glossary and disclaimer flow live in `info_page.html` before unlocking `dashboard.html`.
- `/save` accepts newline-delimited regex rules, splits them server-side, and persists via `User.set_config()`; keep field names (`source_id`, `target_id`, `regex_patterns`, `source_timezone`) stable with the form.
- `/sync-now` spawns `python /app/sync_all_users.py --user <id>` through `/bin/sh`, so any command changes must stay POSIX-compatible despite the Windows host.

## Development Tips
- No automated tests exist; validate changes by building the image (`docker build .`) and running it with the required env vars plus a mounted `./calendar-data` volume.
- Python deps are tracked in `requirements.txt` and installed during image build; pin versions when adding new libs and keep the Docker image slim.
- If you adjust OAuth scopes, cron cadence, or env var names, update `README.md` so operators deploying via GHCR stay aligned.

## Common Pitfalls
- Deleting or rewriting `/app/data` wipes user configs; design migrations carefully when changing schema or encryption.
- Cron expression is `0 */8 * * *` even though the comment says hourly; update both schedule and documentation together if you change it.
- ICS feeds may lack timezone clues—`source_timezone` is mandatory for accurate offsets, so keep that field populated in any tooling you add.
