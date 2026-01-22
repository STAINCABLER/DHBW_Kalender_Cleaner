import os
import re
import logging
import subprocess
import pytz
import markdown
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify
from markupsafe import Markup
from flask_login import LoginManager, login_user, logout_user, current_user, login_required
from flask_wtf.csrf import CSRFProtect, CSRFError
from flask_talisman import Talisman
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from werkzeug.middleware.proxy_fix import ProxyFix
from filelock import FileLock, Timeout

# Lokale Module
import config
from config import (
    DATA_DIR, CONTENT_DIR, GOOGLE_SCOPES,
    APP_BASE_URL, GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, SECRET_KEY,
    encrypt,
    RATE_LIMIT_DEFAULT, RATE_LIMIT_LOGIN, RATE_LIMIT_SYNC
)
from models import User
from sync_logic import CalendarSyncer

config.init()


def get_app():
    app = Flask(__name__)
    app.secret_key = SECRET_KEY
    
    # CSRF-Schutz aktivieren
    CSRFProtect(app)
    
    # Security Headers
    csp = {
        'default-src': "'self'",
        'script-src': ["'self'", "'unsafe-inline'", 'cdn.tailwindcss.com'],
        'style-src': ["'self'", "'unsafe-inline'", 'cdn.tailwindcss.com', 'fonts.googleapis.com'],
        'img-src': ["'self'", 'data:', 'https:'],
        'font-src': ["'self'", 'data:', 'fonts.gstatic.com'],
        'connect-src': ["'self'"],
    }
    Talisman(
        app,
        content_security_policy=csp,
        force_https=False,  # HTTPS wird vom Reverse Proxy gehandhabt
        session_cookie_secure=True,
        session_cookie_http_only=True,
        strict_transport_security=True,
        strict_transport_security_max_age=31536000,  # 1 Jahr
    )
    
    # Rate Limiting
    limiter = Limiter(
        key_func=get_remote_address,
        app=app,
        default_limits=RATE_LIMIT_DEFAULT,
        storage_uri="memory://",
    )
    
    gunicorn_logger = logging.getLogger('gunicorn.error')
    app.logger.handlers = gunicorn_logger.handlers
    app.logger.setLevel(gunicorn_logger.level)

    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)
    
    login_manager = LoginManager()
    login_manager.init_app(app)
    login_manager.login_view = 'login'
    login_manager.login_message = "Bitte anmelden, um diese Seite zu sehen."

    @login_manager.user_loader
    def load_user(user_id):
        return User(user_id)

    # CSRF-Fehlerbehandlung
    @app.errorhandler(CSRFError)
    def handle_csrf_error(e):
        flash('Sicherheitsfehler: Ungültiges oder abgelaufenes Formular-Token. Bitte erneut versuchen.', 'error')
        return redirect(url_for('index'))

    @app.route('/favicon.ico')
    def favicon():
        return app.send_static_file('favicon.ico')

    @app.route('/health')
    def health_check():
        return "OK", 200

    def render_markdown_page(md_filename, title):
        """Lädt eine Markdown-Datei und rendert sie als HTML."""
        md_path = os.path.join(CONTENT_DIR, md_filename)
        try:
            with open(md_path, 'r', encoding='utf-8') as f:
                md_content = f.read()
            html_content = markdown.markdown(md_content, extensions=['tables', 'fenced_code'])
            return render_template('legal_page.html', title=title, content=Markup(html_content))
        except FileNotFoundError:
            return f"Datei {md_filename} nicht gefunden.", 404

    @app.route('/privacy')
    def privacy_policy():
        return render_markdown_page('privacy.md', 'Datenschutzerklärung')

    @app.route('/terms')
    def terms_of_service():
        return render_markdown_page('terms.md', 'Nutzungsbedingungen & Impressum')

    # --- OAuth Flow Routen ---

    def get_oauth_flow():
        return Flow.from_client_config(
            {
                "web": {
                    "client_id": GOOGLE_CLIENT_ID,
                    "client_secret": GOOGLE_CLIENT_SECRET,
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                    "redirect_uris": [f"{APP_BASE_URL}/authorize"],
                }
            },
            scopes=GOOGLE_SCOPES,
            redirect_uri=f"{APP_BASE_URL}/authorize"
        )

    @app.route('/login')
    @limiter.limit(RATE_LIMIT_LOGIN)
    def login():
        flow = get_oauth_flow()
        authorization_url, state = flow.authorization_url(
            access_type='offline', 
            prompt='consent'
        )
        session['oauth_state'] = state
        return redirect(authorization_url)

    @app.route('/authorize')
    def authorize():
        try:
            state = session.pop('oauth_state', None)
            flow = get_oauth_flow()
            
            # Rekonstruiere die korrekte authorization_response URL
            # request.url kann hinter einem Reverse Proxy falsch sein (http statt https)
            authorization_response = f"{APP_BASE_URL}/authorize?{request.query_string.decode('utf-8')}"
            
            flow.fetch_token(
                authorization_response=authorization_response,
                state=state
            )
        except Exception as e:
            app.logger.error(f"OAuth token fetch failed: {e}")
            flash(f"OAuth-Fehler: {e}. Bitte erneut versuchen.", "error")
            return redirect(url_for('index'))

        creds = flow.credentials
        
        try:
            from google.oauth2 import id_token
            from google.auth.transport.requests import Request as GoogleRequest
            id_info = id_token.verify_oauth2_token(
                creds.id_token, GoogleRequest(), GOOGLE_CLIENT_ID
            )
            user_id = id_info['sub'] 
            email = id_info['email']
        except Exception as e:
            flash(f"Fehler beim Validieren der User-ID: {e}", "error")
            return redirect(url_for('index'))

        user = User(user_id)
        
        if not creds.refresh_token:
            flash("Konnte keinen Refresh-Token erhalten. Der Nutzer ist möglicherweise bereits authentifiziert.", "info")
            if user.data.get('refresh_token_encrypted'):
                login_user(user)
                return redirect(url_for('index'))
            else:
                flash("Kritischer Fehler: Kein Refresh-Token. Bitte erneut versuchen.", "error")
                return redirect(url_for('index'))

        encrypted_token = encrypt(creds.refresh_token)
        user.set_auth(email, encrypted_token)

        app.logger.info(f"User authenticated successfully: {email} (ID: {user_id})")
        
        login_user(user)
        flash("Erfolgreich angemeldet!", "success")
        return redirect(url_for('index'))

    @app.route('/logout')
    @login_required
    def logout():
        logout_user()
        flash("Erfolgreich abgemeldet.", "info")
        return redirect(url_for('index'))

    @app.route('/delete-account', methods=['POST'])
    @login_required
    def delete_account():
        email_confirmation = request.form.get('email_confirmation', '').lower().strip()
        user_email = current_user.data.get('email', '').lower().strip()

        if not email_confirmation or email_confirmation != user_email:
            flash("Die E-Mail-Bestätigung war falsch. Ihr Konto wurde nicht gelöscht.", 'error')
            return redirect(url_for('index'))
        
        try:
            user_data_file = current_user.data_file
            user_log_file = os.path.join(DATA_DIR, f"{current_user.id}.log")
            user_lock_file = os.path.join(DATA_DIR, f"{current_user.id}.sync.lock")
            cache_dir = os.path.join(DATA_DIR, '.cache')
            user_id_log = current_user.id
            user_email_log = current_user.data.get('email', 'N/A')

            logout_user() 

            # Konfigurationsdatei löschen
            if os.path.exists(user_data_file):
                os.remove(user_data_file)
            
            # Log-Datei löschen
            if os.path.exists(user_log_file):
                os.remove(user_log_file)
            
            # Lock-Datei löschen
            if os.path.exists(user_lock_file):
                os.remove(user_lock_file)
            
            # Cache-Dateien löschen
            for cache_type in ['ics', 'events']:
                cache_file = os.path.join(cache_dir, f"{user_id_log}_{cache_type}.json")
                if os.path.exists(cache_file):
                    os.remove(cache_file)

            app.logger.info(f"BENUTZERKONTO GELÖSCHT: {user_email_log} (ID: {user_id_log})")
            
            flash("Ihr Konto und alle Ihre Daten wurden erfolgreich und dauerhaft gelöscht.", 'success')
            return redirect(url_for('index')) 

        except Exception as e:
            app.logger.error(f"Fehler beim Löschen des Kontos (ID: {user_id_log}): {e}")
            flash("Beim Löschen Ihres Kontos ist ein unerwarteter Fehler aufgetreten.", 'error')
            return redirect(url_for('index'))

    @app.route('/accept', methods=['POST'])
    @login_required
    def accept_disclaimer():
        current_user.set_disclaimer_accepted()
        flash("Bestätigung erfolgreich. Willkommen beim Dashboard!", "success")
        return redirect(url_for('index'))

    # Anwendungs-Routen
    def get_log_lines_for_file(filepath, n=50):
        if not os.path.exists(filepath):
            return ["Noch keine Logs für diesen Benutzer erstellt. Starten Sie einen Sync."]
        try:
            # Effizientes Lesen der letzten n Zeilen (ohne gesamte Datei zu laden)
            with open(filepath, 'rb') as f:
                # Gehe ans Ende der Datei
                f.seek(0, 2)
                file_size = f.tell()
                
                if file_size == 0:
                    return ["Log-Datei ist leer."]
                
                # Lese max 64KB vom Ende (sollte für 50 Zeilen reichen)
                read_size = min(file_size, 65536)
                f.seek(-read_size, 2)
                content = f.read().decode('utf-8', errors='ignore')
                
                lines = content.splitlines()
                return [line.strip() for line in lines[-n:] if line.strip()]
        except Exception as e:
            return [f"Fehler beim Lesen der Log-Datei: {e}"]

    @app.route('/logs')
    @login_required
    def get_logs():
        user_log_file = os.path.join(DATA_DIR, f"{current_user.id}.log")
        logs = get_log_lines_for_file(user_log_file, n=50) 
        return jsonify({'logs': logs})

    @app.route('/')
    def index():
        if not current_user.is_authenticated:
            return render_template('login.html')
        
        if not current_user.data.get('has_accepted_disclaimer'):
            return render_template('info_page.html')
        
        user_log_file = os.path.join(DATA_DIR, f"{current_user.id}.log")
        initial_logs = get_log_lines_for_file(user_log_file, n=50)

        # Berechne Offsets für alle Zeitzonen für bessere UX
        timezones_display = []
        # Verwende naive UTC-Zeit für pytz.localize()
        now_naive = datetime.now(tz=pytz.utc).replace(tzinfo=None)
        for tz_name in pytz.common_timezones:
            try:
                tz = pytz.timezone(tz_name)
                # Lokalisiere naive Zeit in die Zeitzone, dann hole Offset
                localized_dt = tz.localize(now_naive, is_dst=None)
                offset = localized_dt.utcoffset()
                
                # Formatierung: (+HH:MM) oder (-HH:MM)
                total_seconds = int(offset.total_seconds())
                sign = "+" if total_seconds >= 0 else "-"
                hours, remainder = divmod(abs(total_seconds), 3600)
                minutes, _ = divmod(remainder, 60)
                
                offset_str = f"({sign}{hours:02d}:{minutes:02d})"
                # Verwende Non-Breaking Spaces für Abstand
                display_str = f"{tz_name}   {offset_str}"
                
                timezones_display.append({
                    'value': tz_name,
                    'label': display_str
                })
            except Exception as e:
                # Fallback bei Fehlern (z.B. bei mehrdeutigen Zeiten)
                timezones_display.append({
                    'value': tz_name,
                    'label': tz_name
                })
        
        return render_template('dashboard.html', 
                               config=current_user.get_config(),
                               logs=initial_logs,
                               timezones=timezones_display)

    def _validate_calendar_access(calendar_id, calendar_name):
        """Prüft ob der User Zugriff auf den Kalender hat. Gibt Fehlermeldung oder None zurück."""
        try:
            creds = current_user.get_credentials()
            if not creds:
                return f"{calendar_name}: Keine gültigen Anmeldedaten. Bitte erneut einloggen."
            
            service = build('calendar', 'v3', credentials=creds)
            # Versuche Kalender-Metadaten abzurufen
            service.calendars().get(calendarId=calendar_id).execute()
            return None  # Kein Fehler
        except HttpError as e:
            if e.resp.status == 404:
                return f"{calendar_name}: Kalender '{calendar_id}' nicht gefunden. Bitte ID prüfen."
            elif e.resp.status == 403:
                return f"{calendar_name}: Kein Zugriff auf '{calendar_id}'. Bitte Freigabe prüfen."
            else:
                return f"{calendar_name}: API-Fehler ({e.resp.status}). Bitte ID prüfen."
        except Exception as e:
            return f"{calendar_name}: Validierung fehlgeschlagen ({e})."

    def _validate_ics_url(url):
        """Prüft ob die ICS-URL erreichbar ist und gültiges ICS enthält. Gibt Fehlermeldung oder None zurück."""
        import requests as req
        try:
            headers = {
                'User-Agent': 'DHBW-Calendar-Cleaner/1.0 (https://github.com/STAINCABLER/DHBW_Calendar_Cleaner)',
                'Accept': 'text/calendar, */*'
            }
            response = req.get(url, timeout=15, headers=headers, allow_redirects=True)
            response.raise_for_status()
            
            # Lese die ersten 4KB um sicherzustellen dass wir VCALENDAR finden
            # (manche ICS-Dateien haben lange Header mit Kommentaren)
            # Nutze response.text statt raw.read() damit gzip automatisch dekomprimiert wird
            first_chunk = response.text[:4096]
            
            if 'BEGIN:VCALENDAR' not in first_chunk:
                # Prüfe ob es sich um eine HTML-Seite handelt (Login-Redirect)
                if '<html' in first_chunk.lower() or '<!doctype' in first_chunk.lower():
                    return "Quellkalender: Die URL führt zu einer HTML-Seite statt einer ICS-Datei. Bitte prüfen Sie ob ein Login erforderlich ist."
                return "Quellkalender: Die URL liefert keine gültige ICS-Datei (kein VCALENDAR gefunden)."
            
            return None  # Kein Fehler
        except req.exceptions.Timeout:
            return "Quellkalender: Die URL ist nicht erreichbar (Timeout nach 15 Sekunden)."
        except req.exceptions.SSLError:
            return "Quellkalender: SSL-Zertifikatsfehler. Bitte HTTPS-URL prüfen."
        except req.exceptions.ConnectionError:
            return "Quellkalender: Verbindung fehlgeschlagen. Bitte URL prüfen."
        except req.exceptions.HTTPError as e:
            return f"Quellkalender: HTTP-Fehler {e.response.status_code}. Bitte URL prüfen."
        except Exception as e:
            return f"Quellkalender: Validierung fehlgeschlagen ({e})."

    @app.route('/save', methods=['POST'])
    @login_required
    def save_config():
        source_id = request.form.get('source_id', '').strip()
        target_id = request.form.get('target_id', '').strip()
        regex_raw = request.form.get('regex_patterns', '')
        source_timezone = request.form.get('source_timezone') # NEU
        
        regex_patterns = [line.strip() for line in regex_raw.splitlines() if line.strip()]

        invalid_patterns = []
        for pattern in regex_patterns:
            try:
                re.compile(pattern)
            except re.error as e:
                invalid_patterns.append(f"'{pattern}' ({e})")

        if invalid_patterns:
            details = '; '.join(invalid_patterns)
            flash(f"Ungültige RegEx-Muster: {details}. Bitte korrigieren und erneut speichern.", 'error')
            return redirect(url_for('index'))

        if not source_timezone:
            source_timezone = 'Europe/Berlin'
        
        if not source_id or not target_id:
            flash("Quell-ID und Ziel-ID sind Pflichtfelder.", 'error')
            return redirect(url_for('index'))
        
        # Validierung der Ziel-Kalender-ID
        validation_error = _validate_calendar_access(target_id, 'Zielkalender')
        if validation_error:
            flash(validation_error, 'error')
            return redirect(url_for('index'))
        
        # Validierung der Quell-ID
        is_ics = source_id.startswith('http://') or source_id.startswith('https://')
        if is_ics:
            # ICS-URL validieren
            validation_error = _validate_ics_url(source_id)
            if validation_error:
                flash(validation_error, 'error')
                return redirect(url_for('index'))
        else:
            # Google Calendar ID validieren
            validation_error = _validate_calendar_access(source_id, 'Quellkalender')
            if validation_error:
                flash(validation_error, 'error')
                return redirect(url_for('index'))
            
        current_user.set_config(source_id, target_id, regex_patterns, source_timezone)
        
        flash("Konfiguration erfolgreich gespeichert.", 'success')
            
        return redirect(url_for('index'))

    @app.route('/sync-now', methods=['POST'])
    @login_required
    @limiter.limit(RATE_LIMIT_SYNC)
    def sync_now():
        is_fetch = request.headers.get('X-Requested-With') == 'fetch'

        def respond(status='ok', message=None, http_status=200):
            if is_fetch:
                payload = {'status': status}
                if status == 'ok':
                    payload['redirect'] = url_for('index')
                if message:
                    payload['message'] = message
                return jsonify(payload), http_status
            return redirect(url_for('index'))

        try:
            # Ruft das Sync-Skript nur für den aktuellen User auf
            user_id = current_user.id
            command = f"python /app/sync_all_users.py --user {user_id} >> /app/data/system.log 2>&1"
            subprocess.Popen(
                ['sh', '-c', command],
                close_fds=True
            )
            log_system_event(f"Manueller Sync durch User {user_id} gestartet.")
            flash("Manueller Sync für Ihr Konto gestartet. Das Log-Fenster wird aktualisiert.", 'info')
            return respond('ok')
        except Exception as e:
            message = f"Fehler beim Starten des Syncs: {e}"
            log_system_event(f"Fehler beim Starten eines manuellen Syncs für User {current_user.id}: {e}")
            flash(message, 'error')
            return respond('error', message, http_status=500)

    def log_system_event(message):
        timestamp = datetime.now().isoformat()
        try:
            with open(os.path.join(DATA_DIR, 'system.log'), 'a') as f:
                f.write(f"[{timestamp}] WEB: {message}\n")
        except Exception as exc:
            app.logger.error(f"Fehler beim Schreiben in system.log: {exc}")

    def sync_logger(message):
        app.logger.info(message)

    @app.route('/wipe-target', methods=['POST'])
    @login_required
    def wipe_target_calendar():
        is_fetch = request.headers.get('X-Requested-With') == 'fetch'

        def respond(status='ok', message=None, http_status=200):
            if is_fetch:
                payload = {'status': status}
                if status == 'ok':
                    payload['redirect'] = url_for('index')
                if message:
                    payload['message'] = message
                return jsonify(payload), http_status
            return redirect(url_for('index'))

        config = current_user.get_config()
        target_id = config.get('target_id')

        if not target_id:
            flash("Kein Zielkalender konfiguriert. Bitte zunächst eine Ziel-ID speichern.", 'error')
            return respond('error', "Kein Zielkalender konfiguriert.", http_status=400)

        creds = current_user.get_credentials()
        if not creds:
            flash("Authentifizierung fehlgeschlagen. Bitte erneut anmelden.", 'error')
            return respond('error', "Authentifizierung fehlgeschlagen.", http_status=401)

        lock_file = os.path.join(DATA_DIR, f"{current_user.id}.sync.lock")
        lock = FileLock(lock_file)
        lock_acquired = False

        try:
            log_system_event(f"User {current_user.id} startet Zielkalender-Löschung ({target_id}).")
            lock.acquire(timeout=2)
            lock_acquired = True
        except Timeout:
            log_system_event(f"Zielkalender-Löschung für User {current_user.id} abgebrochen (Lock aktiv).")
            flash("Ein anderer Sync-Lauf ist noch aktiv. Bitte später erneut versuchen.", 'error')
            return respond('error', "Sync läuft bereits.", http_status=409)

        user_log_path = os.path.join(DATA_DIR, f"{current_user.id}.log")

        try:
            service = build('calendar', 'v3', credentials=creds)
            syncer = CalendarSyncer(service, log_callback=sync_logger, user_log_file=user_log_path, user_id=current_user.id)
            syncer.log_user("Zielkalender wird geleert...")
            syncer.log(f"Wipe-Target gestartet für target={target_id}")
            # Cache leeren, damit der nächste Sync vollständig ist
            syncer.clear_cache()
            # Leere Liste synchronisieren = alle Events löschen
            source_id = config.get('source_id')
            created_count, deleted_count = syncer.sync_to_target(target_id, [], None, None, source_id=source_id)
            syncer.log_user(f"Zielkalender geleert ({deleted_count} Einträge entfernt).")
            syncer.log(f"Wipe-Target abgeschlossen: deleted={deleted_count}")
            log_system_event(f"Zielkalender-Löschung für User {current_user.id} beendet: {deleted_count} Einträge entfernt.")
            flash(f"Zielkalender geleert ({deleted_count} Einträge entfernt).", 'success')
            return respond('ok')
        except Exception as e:
            app.logger.exception(f"Fehler beim Löschen des Zielkalenders für User {current_user.id}")
            log_system_event(f"Fehler beim Löschen des Zielkalenders für User {current_user.id}: {e}")
            message = f"Fehler beim Löschen des Zielkalenders: {e}"
            flash(message, 'error')
            return respond('error', message, http_status=500)
        finally:
            if lock_acquired and lock.is_locked:
                try:
                    lock.release()
                except Exception:
                    pass

    @app.route('/clear-cache', methods=['POST'])
    @login_required
    def clear_sync_cache():
        """Löscht den Sync-Cache für einen vollständigen Re-Sync."""
        is_fetch = request.headers.get('X-Requested-With') == 'fetch'

        def respond(status='ok', message=None, http_status=200):
            if is_fetch:
                payload = {'status': status}
                if status == 'ok':
                    payload['redirect'] = url_for('index')
                if message:
                    payload['message'] = message
                return jsonify(payload), http_status
            return redirect(url_for('index'))

        user_log_path = os.path.join(DATA_DIR, f"{current_user.id}.log")
        
        try:
            # Wir brauchen keinen echten Service für clear_cache
            syncer = CalendarSyncer(None, log_callback=sync_logger, user_log_file=user_log_path, user_id=current_user.id)
            syncer.log_user("Sync-Cache wird geleert...")
            syncer.log(f"Clear-Cache gestartet für user={current_user.id}")
            syncer.clear_cache()
            syncer.log_user("Cache gelöscht. Nächster Sync lädt alle Events neu.")
            log_system_event(f"Sync-Cache für User {current_user.id} gelöscht.")
            flash("Sync-Cache gelöscht. Der nächste Sync wird alle Events neu synchronisieren.", 'success')
            return respond('ok')
        except Exception as e:
            app.logger.exception(f"Fehler beim Löschen des Sync-Cache für User {current_user.id}")
            message = f"Fehler beim Löschen des Sync-Cache: {e}"
            flash(message, 'error')
            return respond('error', message, http_status=500)

    return app

if __name__ == '__main__':
    os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1' 
    app = get_app()
    app.run(debug=True, host='0.0.0.0', port=8000)