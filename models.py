"""
User-Model mit JSON-Persistierung.

Implementiert Flask-Login UserMixin und verwaltet Benutzerdaten.
"""

import os
import json
from flask_login import UserMixin
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request as GoogleRequest

from config import (
    DATA_DIR, 
    GOOGLE_CLIENT_ID, 
    GOOGLE_CLIENT_SECRET, 
    GOOGLE_SCOPES,
    decrypt
)


class User(UserMixin):
    """
    Benutzer mit JSON-Datei als Speicher.
    
    Attributes:
        id: Google Sub-ID
        data: Benutzerdaten als Dictionary
        data_file: Pfad zur Konfigurationsdatei
    """
    
    def __init__(self, user_id: str):
        self.id = user_id
        self.data_file = os.path.join(DATA_DIR, f"{self.id}.json")
        self.data = self._load_data()

    def get_id(self) -> str:
        """Gibt die User-ID als String zurück (für Flask-Login)."""
        return str(self.id)

    def _load_data(self) -> dict:
        """Lädt Benutzerdaten aus der JSON-Datei."""
        if os.path.exists(self.data_file):
            try:
                with open(self.data_file, 'r') as f:
                    return json.load(f)
            except json.JSONDecodeError:
                pass
        return {'id': self.id}

    def save(self):
        """Speichert Benutzerdaten in die JSON-Datei."""
        with open(self.data_file, 'w') as f:
            json.dump(self.data, f, indent=2)

    # --- Konfiguration ---
    
    def get_config(self) -> dict:
        """Gibt die Sync-Konfiguration des Benutzers zurück."""
        return {
            'email': self.data.get('email', ''),
            'source_id': self.data.get('source_id', ''),
            'target_id': self.data.get('target_id', ''),
            'regex_patterns': self.data.get('regex_patterns', []),
            'source_timezone': self.data.get('source_timezone', 'Europe/Berlin'),
        }

    def set_config(self, source_id: str, target_id: str, regex_list: list, source_timezone: str):
        """Speichert die Sync-Konfiguration."""
        self.data['source_id'] = source_id
        self.data['target_id'] = target_id
        self.data['regex_patterns'] = regex_list
        self.data['source_timezone'] = source_timezone
        self.save()

    # Authentifizierung
    
    def set_auth(self, email: str, encrypted_token: str):
        """Speichert E-Mail und verschlüsselten Refresh-Token."""
        self.data['email'] = email
        self.data['refresh_token_encrypted'] = encrypted_token
        self.save()

    def get_credentials(self) -> Credentials | None:
        """Entschlüsselt den Refresh-Token und gibt gültige Credentials zurück."""
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
                scopes=GOOGLE_SCOPES
            )
            creds.refresh(GoogleRequest())
            return creds
        except Exception as e:
            print(f"Fehler beim Aktualisieren des Tokens für User {self.id}: {e}")
            return None

    # Disclaimer
    
    def set_disclaimer_accepted(self):
        """Markiert den Disclaimer als akzeptiert."""
        self.data['has_accepted_disclaimer'] = True
        self.save()

    def has_accepted_disclaimer(self) -> bool:
        """Prüft, ob der Disclaimer akzeptiert wurde."""
        return self.data.get('has_accepted_disclaimer', False)

    # Account-Management
    
    def delete(self):
        """Löscht alle Benutzerdaten (Konfiguration und Logs)."""
        # Konfigurationsdatei löschen
        if os.path.exists(self.data_file):
            os.remove(self.data_file)
        
        # Log-Datei löschen
        log_file = os.path.join(DATA_DIR, f"{self.id}.log")
        if os.path.exists(log_file):
            os.remove(log_file)
        
        # Cache-Dateien löschen
        cache_dir = os.path.join(DATA_DIR, '.cache')
        for cache_type in ['ics', 'events']:
            cache_file = os.path.join(cache_dir, f"{self.id}_{cache_type}.json")
            if os.path.exists(cache_file):
                os.remove(cache_file)

    @staticmethod
    def exists(user_id: str) -> bool:
        """Prüft, ob ein Benutzer existiert."""
        return os.path.exists(os.path.join(DATA_DIR, f"{user_id}.json"))

    @staticmethod
    def load(user_id: str) -> 'User | None':
        """Lädt einen Benutzer, falls er existiert."""
        if User.exists(user_id):
            return User(user_id)
        return None
