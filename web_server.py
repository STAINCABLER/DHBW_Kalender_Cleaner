import os
import json
import re
import requests
import subprocess
import logging
import pytz
from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify
from flask_login import LoginManager, UserMixin, login_user, logout_user, current_user, login_required
from cryptography.fernet import Fernet
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from google.auth.transport.requests import Request as GoogleRequest
from googleapiclient.discovery import build
from werkzeug.middleware.proxy_fix import ProxyFix

# --- Konfiguration ---

DATA_DIR = '/app/data'
SCOPES = [
    'https://www.googleapis.com/auth/calendar',
    'openid',
    'https://www.googleapis.com/auth/userinfo.email',
    'https://www.googleapis.com/auth/userinfo.profile'
]

# ENV-Variablen
APP_BASE_URL = os.getenv('APP_BASE_URL')
GOOGLE_CLIENT_ID = os.getenv('GOOGLE_CLIENT_ID')
GOOGLE_CLIENT_SECRET = os.getenv('GOOGLE_CLIENT_SECRET')
SECRET_KEY = os.getenv('SECRET_KEY') # Dient als Flask Secret & Encryption Key

if not all([APP_BASE_URL, GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, SECRET_KEY]):
    raise ValueError("FEHLER: Nicht alle Umgebungsvariablen sind gesetzt (APP_BASE_URL, GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, SECRET_KEY)")

os.makedirs(DATA_DIR, exist_ok=True)

# --- Verschlüsselungs-Helper ---

try:
    fernet = Fernet(SECRET_KEY.encode())
except Exception as e:
    raise ValueError(f"SECRET_KEY ist ungültig. Muss ein 32-Byte base64-kodierter String sein. Fehler: {e}")

def encrypt(data):
    return fernet.encrypt(data.encode()).decode()

def decrypt(token):
    return fernet.decrypt(token.encode()).decode()

# --- User-Modell & Daten-Handling ---

class User(UserMixin):
    def __init__(self, user_id):
        self.id = user_id
        self.data_file = os.path.join(DATA_DIR, f"{self.id}.json")
        self.data = self.load_data()

    def get_id(self):
        return str(self.id)

    def load_data(self):
        if os.path.exists(self.data_file):
            try:
                with open(self.data_file, 'r') as f:
                    return json.load(f)
            except json.JSONDecodeError:
                pass 
        return {'id': self.id} 

    def save(self):
        with open(self.data_file, 'w') as f:
            json.dump(self.data, f, indent=2)

    def get_config(self):
        return {
            'source_id': self.data.get('source_id', ''),
            'target_id': self.data.get('target_id', ''),
            'regex_patterns': self.data.get('regex_patterns', []),
            'source_timezone': self.data.get('source_timezone', 'Europe/Berlin') # NEU (Standard: Berlin)
        }

    def set_config(self, source_id, target_id, regex_list, source_timezone): # NEU: Parameter hinzugefügt
        self.data['source_id'] = source_id
        self.data['target_id'] = target_id
        self.data['regex_patterns'] = regex_list
        self.data['source_timezone'] = source_timezone # NEU
        self.save()

    def set_auth(self, email, encrypted_token):
        self.data['email'] = email
        self.data['refresh_token_encrypted'] = encrypted_token
        self.save()

    def set_disclaimer_accepted(self):
        self.data['has_accepted_disclaimer'] = True
        self.save()

    def get_credentials(self):
        encrypted_token = self.data.get('refresh_token_encrypted')
        if not encrypted_token:
            return None
        
        try:
            refresh_token = decrypt(encrypted_token)
            creds = Credentials(
                token=None,
                refresh_token=refresh_token,
                token_uri="https://oauth2.googleapis.com/token",
                client_id=GOOGLE_CLIENT_ID,
                client_secret=GOOGLE_CLIENT_SECRET,
                scopes=SCOPES
            )
            creds.refresh(GoogleRequest())
            return creds
        except Exception as e:
            print(f"Fehler beim Aktualisieren des Tokens für User {self.id}: {e}")
            return None


# --- Flask App Initialisierung ---

def get_app():
    app = Flask(__name__)
    app.secret_key = SECRET_KEY
    
    gunicorn_logger = logging.getLogger('gunicorn.error')
    app.logger.handlers = gunicorn_logger.handlers
    app.logger.setLevel(gunicorn_logger.level)

    app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)
    
    login_manager = LoginManager()
    login_manager.init_app(app)
    login_manager.login_view = 'login'
    login_manager.login_message = "Bitte anmelden, um diese Seite zu sehen."

    @login_manager.user_loader
    def load_user(user_id):
        return User(user_id)

    @app.route('/favicon.ico')
    def favicon():
        return app.send_static_file('favicon.ico')

    @app.route('/health')
    def health_check():
        return "OK", 200

    @app.route('/privacy')
    def privacy_policy():
        return render_template('privacy.html')

    @app.route('/terms')
    def terms_of_service():
        return render_template('terms.html')

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
            scopes=SCOPES,
            redirect_uri=f"{APP_BASE_URL}/authorize"
        )

    @app.route('/login')
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
            flow.fetch_token(
                authorization_response=request.url,
                state=state
            )
        except Exception as e:
            flash(f"OAuth-Fehler: {e}. Bitte erneut versuchen.", "error")
            return redirect(url_for('index'))

        creds = flow.credentials
        
        try:
            from google.oauth2 import id_token
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

    # --- Anwendungs-Routen ---

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
    def sync_now():
        try:
            # Ruft das Sync-Skript nur für den aktuellen User auf
            user_id = current_user.id
            command = f"python /app/sync_all_users.py --user {user_id} >> /app/data/system.log 2>&1"
            subprocess.Popen(
                ['sh', '-c', command],
                close_fds=True
            )
            flash("Manueller Sync für Ihr Konto gestartet. Das Log-Fenster wird aktualisiert.", 'info')
        except Exception as e:
            flash(f"Fehler beim Starten des Syncs: {e}", 'error')
            
        return redirect(url_for('index'))

    return app

if __name__ == '__main__':
    os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1' 
    app = get_app()
    app.run(debug=True, host='0.0.0.0', port=8000)