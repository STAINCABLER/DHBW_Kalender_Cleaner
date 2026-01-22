"""
Zentrale Konfiguration des DHBW Calendar Cleaners.

Enthält Umgebungsvariablen, Pfade, OAuth-Scopes und Verschlüsselungs-Utilities.
"""

import os
from cryptography.fernet import Fernet

# Pfade
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.getenv('DATA_DIR', '/app/data')
CONTENT_DIR = os.path.join(BASE_DIR, 'content')

# OAuth Scopes
GOOGLE_SCOPES = [
    'https://www.googleapis.com/auth/calendar',
    'openid',
    'https://www.googleapis.com/auth/userinfo.email',
    'https://www.googleapis.com/auth/userinfo.profile'
]

# --- Environment Variables ---
APP_BASE_URL = os.getenv('APP_BASE_URL')
GOOGLE_CLIENT_ID = os.getenv('GOOGLE_CLIENT_ID')
GOOGLE_CLIENT_SECRET = os.getenv('GOOGLE_CLIENT_SECRET')
SECRET_KEY = os.getenv('SECRET_KEY')  # Dient als Flask Secret & Encryption Key


def validate_config():
    """Prüft, ob alle erforderlichen Umgebungsvariablen vorhanden sind."""
    required_vars = {
        'APP_BASE_URL': APP_BASE_URL,
        'GOOGLE_CLIENT_ID': GOOGLE_CLIENT_ID,
        'GOOGLE_CLIENT_SECRET': GOOGLE_CLIENT_SECRET,
        'SECRET_KEY': SECRET_KEY,
    }
    
    missing = [name for name, value in required_vars.items() if not value]
    
    if missing:
        raise ValueError(
            f"FEHLER: Folgende Umgebungsvariablen sind nicht gesetzt: {', '.join(missing)}"
        )


def get_fernet():
    """Erstellt eine Fernet-Instanz aus SECRET_KEY."""
    try:
        return Fernet(SECRET_KEY.encode())
    except Exception as e:
        raise ValueError(
            f"SECRET_KEY ist ungültig. Muss ein 32-Byte base64-kodierter String sein. Fehler: {e}"
        )


# --- Verschlüsselungs-Helper ---
_fernet = None

def _get_fernet():
    """Lazy-Loading der Fernet-Instanz."""
    global _fernet
    if _fernet is None:
        _fernet = get_fernet()
    return _fernet


def encrypt(data: str) -> str:
    """Verschlüsselt einen String mit Fernet."""
    return _get_fernet().encrypt(data.encode()).decode()


def decrypt(token: str) -> str:
    """Entschlüsselt einen Fernet-Token."""
    return _get_fernet().decrypt(token.encode()).decode()


# --- App-Metadaten ---
APP_NAME = "DHBW Calendar Cleaner"
APP_AUTHOR = "Tobias Maimone"
APP_WEBSITE = "https://thulium-labs.de"


# --- Rate Limiting Defaults ---
RATE_LIMIT_DEFAULT = ["200 per day", "50 per hour"]
RATE_LIMIT_LOGIN = "10 per minute"
RATE_LIMIT_SYNC = "5 per minute"
RATE_LIMIT_LOGS = "60 per minute"  # Höheres Limit für Log-Polling


# --- Initialisierung ---
def init():
    """Validiert die Konfiguration und erstellt das Datenverzeichnis."""
    validate_config()
    os.makedirs(DATA_DIR, exist_ok=True)
