import os
import json
import requests
import subprocess
from flask import Flask, render_template, request, redirect, url_for, flash, session
from flask_login import LoginManager, UserMixin, login_user, logout_user, current_user, login_required
from cryptography.fernet import Fernet
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from google.auth.transport.requests import Request as GoogleRequest
from googleapiclient.discovery import build

# --- Konfiguration ---

DATA_DIR = '/app/data'
LOG_FILE = os.path.join(DATA_DIR, 'sync.log')
SCOPES = ['https://www.googleapis.com/auth/calendar', 'openid', 'email', 'profile']

# ENV-Variablen
APP_BASE_URL = os.getenv('APP_BASE_URL')
GOOGLE_CLIENT_ID = os.getenv('GOOGLE_CLIENT_ID')
GOOGLE_CLIENT_SECRET = os.getenv('GOOGLE_CLIENT_SECRET')
SECRET_KEY = os.getenv('SECRET_KEY') # Dient als Flask Secret & Encryption Key

if not all([APP_BASE_URL, GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, SECRET_KEY]):
    raise ValueError("FEHLER: Nicht alle Umgebungsvariablen sind gesetzt (APP_BASE_URL, GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, SECRET_KEY)")

# Stelle sicher, dass das Datenverzeichnis existiert
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
    """Ein User-Objekt, das seine Daten aus einer JSON-Datei liest/schreibt."""
    
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
                pass # Fährt mit leeren Daten fort
        return {'id': self.id} # Default

    def save(self):
        with open(self.data_file, 'w') as f:
            json.dump(self.data, f, indent=2)

    def get_config(self):
        return {
            'source_id': self.data.get('source_id', ''),
            'target_id': self.data.get('target_id', ''),
            'regex_patterns': self.data.get('regex_patterns', [])
        }

    def set_config(self, source_id, target_id, regex_list):
        self.data['source_id'] = source_id
        self.data['target_id'] = target_id
        self.data['regex_patterns'] = regex_list
        self.save()

    def set_auth(self, email, encrypted_token):
        self.data['email'] = email
        self.data['refresh_token_encrypted'] = encrypted_token
        self.save()

    def get_credentials(self):
        """Baut ein gültiges Credentials-Objekt für API-Aufrufe."""
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
    
    login_manager = LoginManager()
    login_manager.init_app(app)
    login_manager.login_view = 'login'
    login_manager.login_message = "Bitte anmelden, um diese Seite zu sehen."

    @login_manager.user_loader
    def load_user(user_id):
        return User(user_id)

    @app.route('/health')
    def health_check():
        """
        Einfacher, leichtgewichtiger Health-Check-Endpunkt.
        Antwortet nur mit 200 OK, um zu signalisieren, dass der Webserver läuft.
        """
        return "OK", 200

    # --- OAuth Flow Routen ---

    def get_oauth_flow():
        """Erstellt ein OAuth Flow-Objekt."""
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
        """Startet den Google-Login."""
        flow = get_oauth_flow()
        authorization_url, state = flow.authorization_url(
            access_type='offline', 
            prompt='consent' # Erzwingt die erneute Abfrage des Refresh-Tokens
        )
        session['oauth_state'] = state
        return redirect(authorization_url)

    @app.route('/authorize')
    def authorize():
        """Callback-Endpunkt von Google."""
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
        
        # Nutzer-Infos (ID, E-Mail) vom ID-Token holen
        try:
            # openid-client (google-auth) validiert das Token automatisch
            from google.oauth2 import id_token
            id_info = id_token.verify_oauth2_token(
                creds.id_token, GoogleRequest(), GOOGLE_CLIENT_ID
            )
            user_id = id_info['sub'] # Googles permanente User-ID
            email = id_info['email']
        except Exception as e:
            flash(f"Fehler beim Validieren der User-ID: {e}", "error")
            return redirect(url_for('index'))

        # User-Objekt erstellen/laden
        user = User(user_id)
        
        # Refresh-Token verschlüsseln und speichern
        if not creds.refresh_token:
            flash("Konnte keinen Refresh-Token erhalten. Der Nutzer ist möglicherweise bereits authentifiziert.", "info")
            # Wenn der Token fehlt, aber der User existiert, einfach einloggen
            if user.data.get('refresh_token_encrypted'):
                login_user(user)
                return redirect(url_for('index'))
            else:
                flash("Kritischer Fehler: Kein Refresh-Token und kein gespeicherter Token. Bitte 'prompt=consent' prüfen.", "error")
                return redirect(url_for('index'))

        encrypted_token = encrypt(creds.refresh_token)
        user.set_auth(email, encrypted_token)
        
        login_user(user)
        flash("Erfolgreich angemeldet!", "success")
        return redirect(url_for('index'))

    @app.route('/logout')
    @login_required
    def logout():
        logout_user()
        flash("Erfolgreich abgemeldet.", "info")
        return redirect(url_for('index'))

    # --- Anwendungs-Routen ---

    def get_log_lines(n=20):
        if not os.path.exists(LOG_FILE):
            return ["Log-Datei noch nicht erstellt."]
        try:
            with open(LOG_FILE, 'r') as f:
                lines = f.readlines()
                return [line.strip() for line in lines[-n:]]
        except Exception as e:
            return [f"Fehler beim Lesen der Log-Datei: {e}"]

    @app.route('/')
    def index():
        if not current_user.is_authenticated:
            return render_template('login.html')
        
        return render_template('dashboard.html', 
                               config=current_user.get_config(),
                               logs=get_log_lines())

    @app.route('/save', methods=['POST'])
    @login_required
    def save_config():
        source_id = request.form.get('source_id')
        target_id = request.form.get('target_id')
        regex_raw = request.form.get('regex_patterns', '')
        
        regex_patterns = [line.strip() for line in regex_raw.splitlines() if line.strip()]
        
        if not source_id or not target_id:
            flash("Quell-ID und Ziel-ID sind Pflichtfelder.", 'error')
            return redirect(url_for('index'))
            
        current_user.set_config(source_id, target_id, regex_patterns)
        
        flash("Konfiguration gespeichert. Erster Sync wird gestartet...", 'success')
        # Starte den ersten Sync nicht-blockierend im Hintergrund
        # Wir rufen das Cron-Skript auf, aber nur für diesen User
        subprocess.Popen(['python', '/app/sync_all_users.py']) # Einfachheitshalber das ganze Skript triggern
            
        return redirect(url_for('index'))

    @app.route('/sync-now', methods=['POST'])
    @login_required
    def sync_now():
        # Starte Sync nicht-blockierend
        subprocess.Popen(['python', '/app/sync_all_users.py'])
        flash("Manuelle Synchronisierung für alle Nutzer gestartet. Lade die Seite neu, um Logs zu sehen.", 'info')
        return redirect(url_for('index'))

    return app

# Wird nur für `flask run` (lokales Debugging) benötigt
if __name__ == '__main__':
    os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1' # Erlaube HTTP für lokales Debugging
    app = get_app()
    app.run(debug=True, host='0.0.0.0', port=8000)