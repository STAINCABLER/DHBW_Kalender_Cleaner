import os
import json
import glob
import sys
import argparse # NEU: Importieren
from datetime import datetime
from cryptography.fernet import Fernet
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request as GoogleRequest
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# Importiere die geteilte Logik
from sync_logic import CalendarSyncer

DATA_DIR = '/app/data'
SCOPES = [
    'https://www.googleapis.com/auth/calendar',
    'openid',
    'https://www.googleapis.com/auth/userinfo.email',
    'https://www.googleapis.com/auth/userinfo.profile'
]

# ENV-Variablen müssen gesetzt sein
SECRET_KEY = os.getenv('SECRET_KEY')
GOOGLE_CLIENT_ID = os.getenv('GOOGLE_CLIENT_ID')
GOOGLE_CLIENT_SECRET = os.getenv('GOOGLE_CLIENT_SECRET')

def log(message):
    print(f"[{datetime.now().isoformat()}] SYNC: {message}", flush=True) # Von CRON zu SYNC geändert für Klarheit

def get_decrypter():
    if not SECRET_KEY:
        log("FEHLER: SECRET_KEY ist nicht gesetzt. Cronjob kann nicht laufen.")
        sys.exit(1)
    return Fernet(SECRET_KEY.encode())

def build_credentials(user_data, decrypter):
    """Baut ein Credentials-Objekt aus dem verschlüsselten Refresh-Token."""
    try:
        encrypted_token = user_data.get('refresh_token_encrypted')
        if not encrypted_token:
            log(f"Nutzer {user_data.get('email')} hat keinen Refresh-Token. Übersprungen.")
            return None
            
        token_json = decrypter.decrypt(encrypted_token.encode()).decode()
        
        creds = Credentials(
            token=None,
            refresh_token=token_json,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=GOOGLE_CLIENT_ID,
            client_secret=GOOGLE_CLIENT_SECRET,
            scopes=SCOPES
        )
        
        creds.refresh(GoogleRequest())
        return creds
        
    except Exception as e:
        log(f"Fehler beim Entschlüsseln/Aktualisieren des Tokens für {user_data.get('email')}: {e}")
        return None

def main():
    # NEU: Argumenten-Parser hinzugefügt
    parser = argparse.ArgumentParser(description='Synchronisiert Kalender.')
    parser.add_argument('--user', type=str, help='Die ID eines einzelnen Benutzers, der synchronisiert werden soll.')
    args = parser.parse_args()

    if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
        log("FEHLER: GOOGLE_CLIENT_ID oder GOOGLE_CLIENT_SECRET nicht gesetzt.")
        sys.exit(1)
        
    decrypter = get_decrypter()
    
    user_files = []
    if args.user:
        # Fall 1: Einzelner User-Sync (vom Web-UI ausgelöst)
        log(f"Starte manuellen Sync-Lauf für einzelnen Benutzer: {args.user}...")
        user_file_path = os.path.join(DATA_DIR, f"{args.user}.json")
        if os.path.exists(user_file_path):
            user_files.append(user_file_path)
        else:
            log(f"FEHLER: Konfigurationsdatei {user_file_path} für User {args.user} nicht gefunden.")
    else:
        # Fall 2: Alle-User-Sync (vom Cron-Job ausgelöst)
        log("Starte stündlichen Sync-Lauf für alle Benutzer...")
        user_files = glob.glob(os.path.join(DATA_DIR, '*.json'))
    
    if not user_files:
        log("Keine Benutzer-Konfigurationsdateien zum Verarbeiten gefunden.")
        return

    log(f"{len(user_files)} Benutzerkonfiguration(en) gefunden.")

    for user_file in user_files:
        try:
            with open(user_file, 'r') as f:
                user_data = json.load(f)
            
            user_id = user_data.get('id', 'unbekannt')
            log(f"--- Verarbeite Nutzer: {user_data.get('email')} (ID: {user_id}) ---")
            
            if not user_data.get('source_id') or not user_data.get('target_id'):
                log(f"Nutzer {user_id} hat Setup nicht abgeschlossen. Übersprungen.")
                continue

            creds = build_credentials(user_data, decrypter)
            if not creds:
                continue
                
            service = build('calendar', 'v3', credentials=creds)
            
            user_log_path = os.path.join(DATA_DIR, f"{user_id}.log")
            
            syncer = CalendarSyncer(service, log_callback=log, user_log_file=user_log_path)
            
            syncer.run_sync(user_data)
            
            log(f"--- Sync für Nutzer {user_id} abgeschlossen ---")
            
        except Exception as e:
            log(f"FEHLER bei der Verarbeitung von Datei {user_file}: {e}")

    log("Sync-Lauf beendet.")

if __name__ == "__main__":
    main()