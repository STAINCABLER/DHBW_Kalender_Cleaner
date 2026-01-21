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
        'style-src': ["'self'", "'unsafe-inline'", 'cdn.tailwindcss.com'],
        'img-src': ["'self'", 'data:', 'https:'],
        'font-src': ["'self'", 'data:'],
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
            user_id_log = current_user.id
            user_email_log = current_user.data.get('email', 'N/A')

            logout_user() 

            if os.path.exists(user_data_file):
                os.remove(user_data_file)
            
            if os.path.exists(user_log_file):
                os.remove(user_log_file)

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
            with open(filepath, 'r') as f:
                lines = f.readlines()
                return [line.strip() for line in lines[-n:]]
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
        
        return render_template('dashboard.html', 
                               config=current_user.get_config(),
                               logs=initial_logs,
                               timezones=pytz.common_timezones)

    @app.route('/save', methods=['POST'])
    @login_required
    def save_config():
        source_id = request.form.get('source_id')
        target_id = request.form.get('target_id')
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
            created_count, deleted_count = syncer.sync_to_target(target_id, [], None, None)
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