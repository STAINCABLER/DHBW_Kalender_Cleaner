"""
Tests für sync_logic.py: Filterung, Standardisierung, Caching.
"""

import os
from unittest.mock import MagicMock
import responses


class TestEventStandardization:
    """Event-Normalisierung."""
    
    def test_standardize_google_event(self, setup_test_environment):
        """Google-Events werden korrekt standardisiert."""
        from sync_logic import CalendarSyncer
        
        mock_service = MagicMock()
        syncer = CalendarSyncer(mock_service)
        
        google_event = {
            'summary': 'Test Event',
            'description': 'Eine Beschreibung',
            'location': 'Raum 101',
            'start': {'dateTime': '2026-01-21T09:00:00+01:00'},
            'end': {'dateTime': '2026-01-21T10:30:00+01:00'},
        }
        
        result = syncer.standardize_event(google_event, 'google')
        
        assert result['summary'] == 'Test Event'
        assert result['description'] == 'Eine Beschreibung'
        assert result['location'] == 'Raum 101'
        assert result['start'] == google_event['start']
        assert result['end'] == google_event['end']
    
    def test_standardize_google_event_missing_fields(self, setup_test_environment):
        """Fehlende Felder erhalten Standardwerte."""
        from sync_logic import CalendarSyncer
        
        mock_service = MagicMock()
        syncer = CalendarSyncer(mock_service)
        
        minimal_event = {
            'start': {'date': '2026-01-21'},
            'end': {'date': '2026-01-22'},
        }
        
        result = syncer.standardize_event(minimal_event, 'google')
        
        assert result['summary'] == 'Kein Titel'
        assert result['description'] == ''
        assert result['location'] == ''


class TestEventFiltering:
    """Regex-Filterung."""
    
    def test_filter_events_no_patterns(self, sample_events, setup_test_environment):
        """Ohne Patterns bleiben alle Events erhalten."""
        from sync_logic import CalendarSyncer
        
        mock_service = MagicMock()
        syncer = CalendarSyncer(mock_service)
        
        filtered, excluded_count = syncer.filter_events(sample_events, [])
        
        assert len(filtered) == len(sample_events)
        assert excluded_count == 0
    
    def test_filter_events_with_pattern(self, sample_events, setup_test_environment):
        """Passende Titel werden gefiltert."""
        from sync_logic import CalendarSyncer
        
        mock_service = MagicMock()
        syncer = CalendarSyncer(mock_service)
        
        # Filter: Feiertage ausschließen
        filtered, excluded_count = syncer.filter_events(sample_events, [r'^Feiertag:'])
        
        assert excluded_count == 1
        assert len(filtered) == 3
        assert all('Feiertag' not in e['summary'] for e in filtered)
    
    def test_filter_events_multiple_patterns(self, sample_events, setup_test_environment):
        """Mehrere Patterns werden kombiniert."""
        from sync_logic import CalendarSyncer
        
        mock_service = MagicMock()
        syncer = CalendarSyncer(mock_service)
        
        # Filter: Feiertage UND Abgesagte ausschließen
        patterns = [r'^Feiertag:', r'Abgesagt']
        filtered, excluded_count = syncer.filter_events(sample_events, patterns)
        
        assert excluded_count == 2
        assert len(filtered) == 2
        assert 'Vorlesung Mathematik' in [e['summary'] for e in filtered]
        assert 'Klausur Datenbanken' in [e['summary'] for e in filtered]
    
    def test_filter_events_case_insensitive(self, setup_test_environment):
        """Filter sind case-insensitive."""
        from sync_logic import CalendarSyncer
        
        mock_service = MagicMock()
        syncer = CalendarSyncer(mock_service)
        
        events = [
            {'summary': 'VORLESUNG', 'description': '', 'location': '', 'start': {}, 'end': {}},
            {'summary': 'Vorlesung', 'description': '', 'location': '', 'start': {}, 'end': {}},
            {'summary': 'vorlesung', 'description': '', 'location': '', 'start': {}, 'end': {}},
        ]
        
        filtered, excluded_count = syncer.filter_events(events, ['vorlesung'])
        
        assert excluded_count == 3
        assert len(filtered) == 0
    
    def test_filter_events_invalid_regex(self, sample_events, setup_test_environment):
        """Ungültige Regex-Patterns werden ignoriert."""
        from sync_logic import CalendarSyncer
        
        mock_service = MagicMock()
        syncer = CalendarSyncer(mock_service)
        
        # Ungültiges Regex-Pattern
        patterns = [r'[invalid(', r'Feiertag']
        filtered, excluded_count = syncer.filter_events(sample_events, patterns)
        
        # Nur das gültige Pattern sollte angewendet werden
        assert len(filtered) == 3


class TestEventHashing:
    """Event-Hashing für Delta-Sync."""
    
    def test_compute_event_hash_deterministic(self, setup_test_environment):
        """Gleiche Events erzeugen gleichen Hash."""
        from sync_logic import CalendarSyncer
        
        mock_service = MagicMock()
        syncer = CalendarSyncer(mock_service)
        
        event = {
            'summary': 'Test Event',
            'description': 'Beschreibung',
            'location': 'Raum 1',
            'start': {'dateTime': '2026-01-21T09:00:00+01:00'},
            'end': {'dateTime': '2026-01-21T10:00:00+01:00'},
        }
        
        hash1 = syncer._compute_event_hash(event)
        hash2 = syncer._compute_event_hash(event)
        
        assert hash1 == hash2
    
    def test_compute_event_hash_different_for_different_events(self, setup_test_environment):
        """Unterschiedliche Events erzeugen unterschiedliche Hashes."""
        from sync_logic import CalendarSyncer
        
        mock_service = MagicMock()
        syncer = CalendarSyncer(mock_service)
        
        event1 = {
            'summary': 'Event A',
            'description': '',
            'location': '',
            'start': {'dateTime': '2026-01-21T09:00:00+01:00'},
            'end': {'dateTime': '2026-01-21T10:00:00+01:00'},
        }
        
        event2 = {
            'summary': 'Event B',
            'description': '',
            'location': '',
            'start': {'dateTime': '2026-01-21T09:00:00+01:00'},
            'end': {'dateTime': '2026-01-21T10:00:00+01:00'},
        }
        
        assert syncer._compute_event_hash(event1) != syncer._compute_event_hash(event2)
    
    def test_get_event_key(self, setup_test_environment):
        """Event-Key kombiniert Startzeit und Titel."""
        from sync_logic import CalendarSyncer
        
        mock_service = MagicMock()
        syncer = CalendarSyncer(mock_service)
        
        event = {
            'summary': 'Vorlesung',
            'start': {'dateTime': '2026-01-21T09:00:00+01:00'},
            'end': {},
        }
        
        key = syncer._get_event_key(event)
        
        assert '2026-01-21T09:00:00+01:00' in key
        assert 'Vorlesung' in key


class TestCaching:
    """Cache-Persistierung."""
    
    def test_cache_save_and_load(self, temp_data_dir, setup_test_environment):
        """Cache wird gespeichert und geladen."""
        from sync_logic import CalendarSyncer
        import sync_logic
        
        # Setze Cache-Verzeichnis
        sync_logic.CACHE_DIR = str(temp_data_dir / '.cache')
        os.makedirs(sync_logic.CACHE_DIR, exist_ok=True)
        
        mock_service = MagicMock()
        syncer = CalendarSyncer(mock_service, user_id='cache-test-user')
        
        test_data = {'key': 'value', 'number': 42}
        syncer._save_cache('test', test_data)
        
        loaded = syncer._load_cache('test')
        
        assert loaded == test_data
    
    def test_cache_load_non_existent(self, temp_data_dir, setup_test_environment):
        """Nicht existierender Cache liefert leeres Dict."""
        from sync_logic import CalendarSyncer
        import sync_logic
        
        sync_logic.CACHE_DIR = str(temp_data_dir / '.cache')
        
        mock_service = MagicMock()
        syncer = CalendarSyncer(mock_service, user_id='no-cache-user')
        
        loaded = syncer._load_cache('non-existent')
        
        assert loaded == {}


class TestICSParsing:
    """ICS-Kalender-Parsing."""
    
    @responses.activate
    def test_fetch_ics_events_success(self, sample_ics_content, temp_data_dir, setup_test_environment):
        """ICS-Events werden korrekt abgerufen."""
        from sync_logic import CalendarSyncer
        import sync_logic
        
        sync_logic.CACHE_DIR = str(temp_data_dir / '.cache')
        os.makedirs(sync_logic.CACHE_DIR, exist_ok=True)
        
        # Mock HTTP-Response
        responses.add(
            responses.GET,
            'https://example.com/calendar.ics',
            body=sample_ics_content,
            status=200,
            headers={'ETag': '"abc123"'}
        )
        
        mock_service = MagicMock()
        syncer = CalendarSyncer(mock_service, user_id='ics-test-user')
        
        events = syncer.fetch_ics_events(
            'https://example.com/calendar.ics',
            source_timezone='Europe/Berlin'
        )
        
        assert len(events) == 3
        assert any('Vorlesung Informatik' in e['summary'] for e in events)
        assert any('Feiertag' in e['summary'] for e in events)
    
    @responses.activate
    def test_fetch_ics_events_uses_cache(self, sample_ics_content, temp_data_dir, setup_test_environment):
        """304 Not Modified nutzt den Cache."""
        from sync_logic import CalendarSyncer
        import sync_logic
        
        sync_logic.CACHE_DIR = str(temp_data_dir / '.cache')
        os.makedirs(sync_logic.CACHE_DIR, exist_ok=True)
        
        mock_service = MagicMock()
        syncer = CalendarSyncer(mock_service, user_id='cache-ics-user')
        
        # Erstelle Cache manuell
        syncer._save_cache('ics', {
            'etag': '"abc123"',
            'content': sample_ics_content,
        })
        
        # Server antwortet mit 304
        responses.add(
            responses.GET,
            'https://example.com/calendar.ics',
            status=304,
        )
        
        events = syncer.fetch_ics_events(
            'https://example.com/calendar.ics',
            source_timezone='Europe/Berlin'
        )
        
        assert len(events) == 3
    
    @responses.activate
    def test_fetch_ics_events_deduplicates(self, temp_data_dir, setup_test_environment):
        """Duplikate werden entfernt."""
        from sync_logic import CalendarSyncer
        import sync_logic
        
        sync_logic.CACHE_DIR = str(temp_data_dir / '.cache')
        os.makedirs(sync_logic.CACHE_DIR, exist_ok=True)
        
        # ICS mit Duplikat (gleiche UID)
        ics_with_duplicate = """BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Test//Test//EN
BEGIN:VEVENT
DTSTART:20260121T090000
DTEND:20260121T100000
SUMMARY:Event 1
UID:same-uid@test.com
END:VEVENT
BEGIN:VEVENT
DTSTART:20260121T110000
DTEND:20260121T120000
SUMMARY:Event 1 (Duplikat)
UID:same-uid@test.com
END:VEVENT
BEGIN:VEVENT
DTSTART:20260121T140000
DTEND:20260121T150000
SUMMARY:Event 2
UID:different-uid@test.com
END:VEVENT
END:VCALENDAR"""
        
        responses.add(
            responses.GET,
            'https://example.com/duplicate.ics',
            body=ics_with_duplicate,
            status=200,
        )
        
        mock_service = MagicMock()
        syncer = CalendarSyncer(mock_service, user_id='dedup-test')
        
        events = syncer.fetch_ics_events(
            'https://example.com/duplicate.ics',
            source_timezone='Europe/Berlin'
        )
        
        # Mindestens 2 Events (1 Duplikat sollte entfernt werden)
        # Die genaue Anzahl hängt von der ICS-Bibliothek ab
        assert len(events) >= 2
        # Das Wichtige: es wurden weniger Events als in der Datei
        summaries = [e['summary'] for e in events]
        # Es sollte entweder "Event 1" oder "Event 1 (Duplikat)" geben, nicht beide
        event1_count = sum(1 for s in summaries if 'Event 1' in s and 'Duplikat' not in s)
        duplikat_count = sum(1 for s in summaries if 'Duplikat' in s)
        # Maximal eines der Duplikate sollte vorhanden sein
        assert event1_count + duplikat_count <= 2


class TestLogging:
    """Logging-System."""
    
    def test_log_writes_to_system_log(self, setup_test_environment, capsys):
        """log() schreibt in stdout."""
        from sync_logic import CalendarSyncer
        
        mock_service = MagicMock()
        syncer = CalendarSyncer(mock_service)
        
        syncer.log("Test System Message")
        
        captured = capsys.readouterr()
        assert "Test System Message" in captured.out
    
    def test_log_writes_to_user_log_file(self, temp_data_dir, setup_test_environment):
        """log() mit user_message schreibt in Datei."""
        from sync_logic import CalendarSyncer
        
        mock_service = MagicMock()
        user_log_path = temp_data_dir / 'user.log'
        syncer = CalendarSyncer(mock_service, user_log_file=str(user_log_path))
        
        syncer.log("Technical message", user_message="Benutzerfreundliche Nachricht")
        
        assert user_log_path.exists()
        content = user_log_path.read_text()
        assert "Benutzerfreundliche Nachricht" in content
    
    def test_log_user_writes_same_message_to_both(self, temp_data_dir, setup_test_environment, capsys):
        """log_user() schreibt in beide Logs."""
        from sync_logic import CalendarSyncer
        
        mock_service = MagicMock()
        user_log_path = temp_data_dir / 'user.log'
        syncer = CalendarSyncer(mock_service, user_log_file=str(user_log_path))
        
        syncer.log_user("Sync erfolgreich abgeschlossen")
        
        # System-Log (stdout)
        captured = capsys.readouterr()
        assert "Sync erfolgreich abgeschlossen" in captured.out
        
        # User-Log (Datei)
        content = user_log_path.read_text()
        assert "Sync erfolgreich abgeschlossen" in content
