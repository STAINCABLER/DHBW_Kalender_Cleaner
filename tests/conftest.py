"""
Gemeinsame Pytest-Fixtures für alle Testmodule.
"""

import os
import sys
import tempfile
import json
import shutil
from pathlib import Path

# WICHTIG: Umgebungsvariablen MÜSSEN VOR dem Import anderer Module gesetzt werden,
# da config.py und sync_logic.py bei Import DATA_DIR auswerten!
# Dieses temporäre Verzeichnis wird für die gesamte Test-Session verwendet.
_SESSION_TEMP_DIR = tempfile.mkdtemp(prefix='dhbw_calendar_test_')
os.environ['DATA_DIR'] = _SESSION_TEMP_DIR

# Auch SECRET_KEY muss früh gesetzt werden
from cryptography.fernet import Fernet
_TEST_SECRET_KEY = Fernet.generate_key().decode()
os.environ['SECRET_KEY'] = _TEST_SECRET_KEY
os.environ['APP_BASE_URL'] = 'http://localhost:8000'
os.environ['GOOGLE_CLIENT_ID'] = 'test-client-id.apps.googleusercontent.com'
os.environ['GOOGLE_CLIENT_SECRET'] = 'test-client-secret'

import pytest

# Projektverzeichnis zum Python-Pfad hinzufügen
sys.path.insert(0, str(Path(__file__).parent.parent))


# Fixtures

@pytest.fixture(scope="session", autouse=True)
def setup_test_environment():
    """Initialisiert Umgebungsvariablen für alle Tests."""
    # Umgebungsvariablen wurden bereits auf Modulebene gesetzt
    yield
    
    # Cleanup: Temporäres Verzeichnis löschen
    try:
        shutil.rmtree(_SESSION_TEMP_DIR)
    except Exception:
        pass  # Ignoriere Fehler beim Aufräumen


@pytest.fixture
def temp_data_dir(tmp_path):
    """Temporäres DATA_DIR für isolierte Tests."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    
    # Setze DATA_DIR für diesen Test
    original_data_dir = os.environ.get('DATA_DIR')
    os.environ['DATA_DIR'] = str(data_dir)
    
    yield data_dir
    
    # Cleanup
    if original_data_dir:
        os.environ['DATA_DIR'] = original_data_dir
    else:
        os.environ.pop('DATA_DIR', None)


@pytest.fixture
def sample_user_data():
    """Beispiel-Benutzerdaten."""
    return {
        'id': 'test-user-123',
        'email': 'test@example.com',
        'source_id': 'https://example.com/calendar.ics',
        'target_id': 'target-calendar-id',
        'regex_patterns': [r'^Feiertag:', r'Abgesagt'],
        'source_timezone': 'Europe/Berlin',
        'has_accepted_disclaimer': True,
    }


@pytest.fixture
def sample_events():
    """Beispiel-Events für Filtertests."""
    return [
        {
            'summary': 'Vorlesung Mathematik',
            'description': 'Raum A101',
            'location': 'Campus Nord',
            'start': {'dateTime': '2026-01-21T09:00:00+01:00'},
            'end': {'dateTime': '2026-01-21T10:30:00+01:00'},
        },
        {
            'summary': 'Feiertag: Tag der Deutschen Einheit',
            'description': '',
            'location': '',
            'start': {'date': '2026-10-03'},
            'end': {'date': '2026-10-04'},
        },
        {
            'summary': 'Workshop Python (Abgesagt)',
            'description': 'Wurde leider abgesagt',
            'location': 'Online',
            'start': {'dateTime': '2026-01-22T14:00:00+01:00'},
            'end': {'dateTime': '2026-01-22T16:00:00+01:00'},
        },
        {
            'summary': 'Klausur Datenbanken',
            'description': 'Bitte pünktlich erscheinen',
            'location': 'Hörsaal B',
            'start': {'dateTime': '2026-02-15T10:00:00+01:00'},
            'end': {'dateTime': '2026-02-15T12:00:00+01:00'},
        },
    ]


@pytest.fixture
def sample_ics_content():
    """ICS-Kalenderdaten als String."""
    return """BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Test//Test Calendar//EN
BEGIN:VEVENT
DTSTART:20260121T090000
DTEND:20260121T103000
SUMMARY:Vorlesung Informatik
DESCRIPTION:Einführung in Algorithmen
LOCATION:Raum A101
UID:event-001@test.example.com
END:VEVENT
BEGIN:VEVENT
DTSTART:20260122T140000
DTEND:20260122T160000
SUMMARY:Übung Programmieren
DESCRIPTION:Praktische Übungen
LOCATION:PC-Pool
UID:event-002@test.example.com
END:VEVENT
BEGIN:VEVENT
DTSTART;VALUE=DATE:20261003
DTEND;VALUE=DATE:20261004
SUMMARY:Feiertag: Tag der Deutschen Einheit
UID:event-003@test.example.com
END:VEVENT
END:VCALENDAR"""


@pytest.fixture
def mock_google_service(mocker):
    """Gemockter Google Calendar Service."""
    mock_service = mocker.MagicMock()
    
    # Mock für events().list()
    mock_events = mocker.MagicMock()
    mock_service.events.return_value = mock_events
    
    return mock_service


@pytest.fixture
def fernet_key():
    """Test-Fernet-Key aus Umgebungsvariable."""
    return os.environ['SECRET_KEY']


@pytest.fixture
def flask_app():
    """Flask-App im Testmodus."""
    # Import hier, da config erst nach setup_test_environment geladen werden sollte
    import config
    config.init()
    
    from web_server import get_app
    
    app = get_app()
    app.config['TESTING'] = True
    app.config['WTF_CSRF_ENABLED'] = False  # CSRF für Tests deaktivieren
    
    return app


@pytest.fixture
def client(flask_app):
    """Flask Test-Client."""
    return flask_app.test_client()
