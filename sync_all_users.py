import os
import json
import glob
import sys
import argparse
from datetime import datetime
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request as GoogleRequest
from googleapiclient.discovery import build
from filelock import FileLock, Timeout

# Importiere die geteilte Logik und Konfiguration
from sync_logic import CalendarSyncer
import config
from config import (
    DATA_DIR, GOOGLE_SCOPES,
    GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET,
    decrypt
)

def log(message):
    print(f"[{datetime.now().isoformat()}] SYNC: {message}", flush=True)

def build_credentials(user_data):
    """Entschlüsselt Refresh-Token und erstellt Credentials."""
    try:
        encrypted_token = user_data.get('refresh_token_encrypted')
        if not encrypted_token:
            log(f"Nutzer {user_data.get('email')} hat keinen Refresh-Token. Übersprungen.")
            return None
            
        token_json = decrypt(encrypted_token)
        
        creds = Credentials(
            token=None,
            refresh_token=token_json,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=GOOGLE_CLIENT_ID,
            client_secret=GOOGLE_CLIENT_SECRET,
            scopes=GOOGLE_SCOPES
        )
        
        creds.refresh(GoogleRequest())
        return creds
        
    except Exception as e:
        log(f"Fehler beim Entschlüsseln/Aktualisieren des Tokens für {user_data.get('email')}: {e}")
        return None

def main():
    try:
        config.validate_config()
    except ValueError as e:
        log(str(e))
        sys.exit(1)
    
    parser = argparse.ArgumentParser(description='Synchronisiert Kalender.')
    parser.add_argument('--user', type=str, help='Die ID eines einzelnen Benutzers, der synchronisiert werden soll.')
    parser.add_argument('--wipe', action='store_true', help='Löscht alle Events im Zielkalender des Benutzers (erfordert --user).')
    args = parser.parse_args()
    
    if args.wipe and not args.user:
        log("FEHLER: --wipe erfordert --user")
        sys.exit(1)
    
    user_files = []
    if args.user:
        # Einzelner User (manueller Sync)
        log(f"Starte manuellen Sync-Lauf für einzelnen Benutzer: {args.user}...")
        user_file_path = os.path.join(DATA_DIR, f"{args.user}.json")
        if os.path.exists(user_file_path):
            user_files.append(user_file_path)
        else:
            log(f"FEHLER: Konfigurationsdatei {user_file_path} für User {args.user} nicht gefunden.")
    else:
        # Alle User (Cron-Job)
        log("Starte stündlichen Sync-Lauf für alle Benutzer...")
        user_files = glob.glob(os.path.join(DATA_DIR, '*.json'))
    
    if not user_files:
        log("Keine Benutzer-Konfigurationsdateien zum Verarbeiten gefunden.")
        return

    log(f"{len(user_files)} Benutzerkonfiguration(en) gefunden.")

    for user_file in user_files:
        user_id = None
        lock = None
        lock_acquired = False
        try:
            with open(user_file, 'r') as f:
                user_data = json.load(f)
            
            user_id = user_data.get('id', 'unbekannt')
            
            # File-Lock gegen parallele Syncs
            lock_file = os.path.join(DATA_DIR, f"{user_id}.sync.lock")
            lock = FileLock(lock_file)

            try:
                lock.acquire(timeout=2)
                lock_acquired = True
            except Timeout:
                log(f"!!! WARNUNG: Sync für User {user_id} läuft bereits. Überspringe diesen Lauf.")
                continue

            log(f"--- Verarbeite Nutzer: {user_data.get('email')} (ID: {user_id}) ---")
            
            if not user_data.get('source_id') or not user_data.get('target_id'):
                log(f"Nutzer {user_id} hat Setup nicht abgeschlossen. Übersprungen.")
                continue

            creds = build_credentials(user_data)
            if not creds:
                continue
                
            service = build('calendar', 'v3', credentials=creds)
            
            user_log_path = os.path.join(DATA_DIR, f"{user_id}.log")
            
            syncer = CalendarSyncer(service, log_callback=log, user_log_file=user_log_path, user_id=user_id)
            
            if args.wipe:
                # Wipe-Modus: Alle Events im Zielkalender löschen
                target_id = user_data.get('target_id')
                source_id = user_data.get('source_id')
                syncer.log_user("Zielkalender wird geleert...")
                log(f"Wipe-Target gestartet für target={target_id}")
                syncer.clear_cache()
                created_count, deleted_count = syncer.sync_to_target(target_id, [], None, None, source_id=source_id)
                syncer.log_user(f"Zielkalender geleert ({deleted_count} Einträge entfernt).")
                log(f"Wipe-Target abgeschlossen: deleted={deleted_count}")
            else:
                # Normaler Sync-Modus
                syncer.run_sync(user_data)
            
            log(f"--- {'Wipe' if args.wipe else 'Sync'} für Nutzer {user_id} abgeschlossen ---")
            
        except Exception as e:
            log(f"FEHLER bei der Verarbeitung von Datei {user_file}: {e}")
        finally:
            if lock_acquired and lock and lock.is_locked:
                try:
                    lock.release()
                except Exception:
                    pass

    log("Sync-Lauf beendet.")

if __name__ == "__main__":
    main()