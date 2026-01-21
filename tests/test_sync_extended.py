"""
Erweiterte Tests für sync_logic.py und sync_all_users.py.
"""

from unittest.mock import MagicMock


class TestSyncAllUsersModule:
    """sync_all_users.py Funktionen."""
    
    def test_log_function_format(self, setup_test_environment, capsys):
        """log() formatiert mit Timestamp."""
        from sync_all_users import log
        
        log("Test Message")
        
        captured = capsys.readouterr()
        assert "SYNC: Test Message" in captured.out
        assert "[" in captured.out  # Timestamp vorhanden
    
    def test_build_credentials_no_token(self, setup_test_environment):
        """build_credentials() gibt None ohne Token zurück."""
        from sync_all_users import build_credentials
        
        user_data = {'email': 'test@example.com'}
        
        result = build_credentials(user_data)
        
        assert result is None
    
    def test_build_credentials_invalid_token(self, setup_test_environment):
        """build_credentials() gibt None bei ungültigem Token zurück."""
        from sync_all_users import build_credentials
        
        user_data = {
            'email': 'test@example.com',
            'refresh_token_encrypted': 'invalid-encrypted-token'
        }
        
        result = build_credentials(user_data)
        
        assert result is None


class TestCalendarSyncerInit:
    """CalendarSyncer-Initialisierung."""
    
    def test_syncer_creates_cache_dir(self, temp_data_dir, setup_test_environment):
        """CalendarSyncer erstellt Cache-Verzeichnis."""
        from sync_logic import CalendarSyncer
        import sync_logic
        
        cache_dir = temp_data_dir / '.cache'
        sync_logic.CACHE_DIR = str(cache_dir)
        
        mock_service = MagicMock()
        CalendarSyncer(mock_service, user_id='test-user')
        
        assert cache_dir.exists()
    
    def test_syncer_custom_log_callback(self, setup_test_environment):
        """CalendarSyncer unterstützt custom log callback."""
        from sync_logic import CalendarSyncer
        
        log_messages = []
        
        def custom_logger(msg):
            log_messages.append(msg)
        
        mock_service = MagicMock()
        syncer = CalendarSyncer(mock_service, log_callback=custom_logger)
        
        syncer.log("Test Message")
        
        assert "Test Message" in log_messages


class TestCacheFunctions:
    """Cache-Hilfsfunktionen."""
    
    def test_get_cache_path_with_user_id(self, temp_data_dir, setup_test_environment):
        """_get_cache_path() liefert korrekten Pfad."""
        from sync_logic import CalendarSyncer
        import sync_logic
        
        sync_logic.CACHE_DIR = str(temp_data_dir / '.cache')
        
        mock_service = MagicMock()
        syncer = CalendarSyncer(mock_service, user_id='cache-user-123')
        
        path = syncer._get_cache_path('events')
        
        assert 'cache-user-123_events.json' in path
    
    def test_get_cache_path_without_user_id(self, setup_test_environment):
        """_get_cache_path() gibt None ohne user_id zurück."""
        from sync_logic import CalendarSyncer
        
        mock_service = MagicMock()
        syncer = CalendarSyncer(mock_service, user_id=None)
        
        path = syncer._get_cache_path('events')
        
        assert path is None
    
    def test_save_cache_without_user_id(self, setup_test_environment):
        """_save_cache() ohne user_id ist no-op."""
        from sync_logic import CalendarSyncer
        
        mock_service = MagicMock()
        syncer = CalendarSyncer(mock_service, user_id=None)
        
        # Sollte keine Exception werfen
        syncer._save_cache('events', {'test': 'data'})
    
    def test_clear_cache(self, temp_data_dir, setup_test_environment):
        """clear_cache() löscht Cache-Dateien."""
        from sync_logic import CalendarSyncer
        import sync_logic
        
        cache_dir = temp_data_dir / '.cache'
        cache_dir.mkdir(exist_ok=True)
        sync_logic.CACHE_DIR = str(cache_dir)
        
        mock_service = MagicMock()
        syncer = CalendarSyncer(mock_service, user_id='clear-cache-user')
        
        # Erstelle Cache-Dateien
        syncer._save_cache('ics', {'etag': 'test'})
        syncer._save_cache('events', {'events': []})
        
        # Lösche Cache
        syncer.clear_cache()
        
        # Verifiziere dass Caches leer sind
        assert syncer._load_cache('ics') == {}
        assert syncer._load_cache('events') == {}


class TestEventHashing:
    """Event-Hashing."""
    
    def test_hash_includes_description(self, setup_test_environment):
        """Hash berücksichtigt Beschreibung."""
        from sync_logic import CalendarSyncer
        
        mock_service = MagicMock()
        syncer = CalendarSyncer(mock_service)
        
        event1 = {
            'summary': 'Event',
            'description': 'Description A',
            'location': '',
            'start': {'date': '2026-01-21'},
            'end': {'date': '2026-01-22'},
        }
        
        event2 = {
            'summary': 'Event',
            'description': 'Description B',
            'location': '',
            'start': {'date': '2026-01-21'},
            'end': {'date': '2026-01-22'},
        }
        
        assert syncer._compute_event_hash(event1) != syncer._compute_event_hash(event2)
    
    def test_hash_includes_location(self, setup_test_environment):
        """Hash berücksichtigt Location."""
        from sync_logic import CalendarSyncer
        
        mock_service = MagicMock()
        syncer = CalendarSyncer(mock_service)
        
        event1 = {
            'summary': 'Event',
            'description': '',
            'location': 'Room A',
            'start': {'date': '2026-01-21'},
            'end': {'date': '2026-01-22'},
        }
        
        event2 = {
            'summary': 'Event',
            'description': '',
            'location': 'Room B',
            'start': {'date': '2026-01-21'},
            'end': {'date': '2026-01-22'},
        }
        
        assert syncer._compute_event_hash(event1) != syncer._compute_event_hash(event2)


class TestEventKey:
    """Event-Key-Generierung."""
    
    def test_event_key_with_datetime(self, setup_test_environment):
        """Event-Key verwendet dateTime."""
        from sync_logic import CalendarSyncer
        
        mock_service = MagicMock()
        syncer = CalendarSyncer(mock_service)
        
        event = {
            'summary': 'Vorlesung',
            'start': {'dateTime': '2026-01-21T09:00:00+01:00'},
            'end': {'dateTime': '2026-01-21T10:00:00+01:00'},
        }
        
        key = syncer._get_event_key(event)
        
        assert '2026-01-21T09:00:00+01:00' in key
        assert 'Vorlesung' in key
    
    def test_event_key_with_date(self, setup_test_environment):
        """Event-Key verwendet date für Ganztags-Events."""
        from sync_logic import CalendarSyncer
        
        mock_service = MagicMock()
        syncer = CalendarSyncer(mock_service)
        
        event = {
            'summary': 'Feiertag',
            'start': {'date': '2026-10-03'},
            'end': {'date': '2026-10-04'},
        }
        
        key = syncer._get_event_key(event)
        
        assert '2026-10-03' in key
        assert 'Feiertag' in key
    
    def test_event_key_missing_start(self, setup_test_environment):
        """Event-Key ohne Start verwendet leeren String."""
        from sync_logic import CalendarSyncer
        
        mock_service = MagicMock()
        syncer = CalendarSyncer(mock_service)
        
        event = {
            'summary': 'Broken Event',
        }
        
        key = syncer._get_event_key(event)
        
        assert '|Broken Event' in key


class TestICSStandardization:
    """ICS-Event-Standardisierung."""
    
    def test_standardize_ics_all_day_event(self, setup_test_environment):
        """Ganztags-Events werden korrekt standardisiert."""
        from sync_logic import CalendarSyncer
        import arrow
        
        mock_service = MagicMock()
        syncer = CalendarSyncer(mock_service)
        
        # Mock ICS Event
        ics_event = MagicMock()
        ics_event.name = 'Feiertag'
        ics_event.description = 'Gesetzlicher Feiertag'
        ics_event.location = ''
        ics_event.all_day = True
        ics_event.begin = arrow.get('2026-10-03')
        ics_event.end = arrow.get('2026-10-03')
        
        result = syncer.standardize_event(ics_event, 'ics')
        
        assert result['summary'] == 'Feiertag'
        assert 'date' in result['start']
        assert result['start']['date'] == '2026-10-03'
    
    def test_standardize_ics_timed_event(self, setup_test_environment):
        """Zeitgebundene Events werden korrekt standardisiert."""
        from sync_logic import CalendarSyncer
        import arrow
        
        mock_service = MagicMock()
        syncer = CalendarSyncer(mock_service)
        
        # Mock ICS Event
        ics_event = MagicMock()
        ics_event.name = 'Vorlesung'
        ics_event.description = 'Mathematik'
        ics_event.location = 'Raum A101'
        ics_event.all_day = False
        ics_event.begin = arrow.get('2026-01-21T09:00:00+01:00')
        ics_event.end = arrow.get('2026-01-21T10:30:00+01:00')
        
        result = syncer.standardize_event(ics_event, 'ics')
        
        assert result['summary'] == 'Vorlesung'
        assert result['location'] == 'Raum A101'
        assert 'dateTime' in result['start']
    
    def test_standardize_ics_missing_fields(self, setup_test_environment):
        """Fehlende Felder erhalten Standardwerte."""
        from sync_logic import CalendarSyncer
        import arrow
        
        mock_service = MagicMock()
        syncer = CalendarSyncer(mock_service)
        
        # Mock ICS Event ohne optionale Felder
        ics_event = MagicMock()
        ics_event.name = None
        ics_event.description = None
        ics_event.location = None
        ics_event.all_day = True
        ics_event.begin = arrow.get('2026-01-21')
        ics_event.end = arrow.get('2026-01-21')
        
        result = syncer.standardize_event(ics_event, 'ics')
        
        assert result['summary'] == 'Kein Titel'
        assert result['description'] == ''
        assert result['location'] == ''


class TestFilterEdgeCases:
    """Filter-Randfälle."""
    
    def test_filter_empty_summary(self, setup_test_environment):
        """Events ohne Summary werden nicht gefiltert."""
        from sync_logic import CalendarSyncer
        
        mock_service = MagicMock()
        syncer = CalendarSyncer(mock_service)
        
        events = [
            {'summary': '', 'description': '', 'location': '', 'start': {}, 'end': {}},
        ]
        
        filtered, excluded = syncer.filter_events(events, ['Test'])
        
        assert len(filtered) == 1
        assert excluded == 0
    
    def test_filter_special_characters_in_pattern(self, setup_test_environment):
        """Regex mit Sonderzeichen funktioniert."""
        from sync_logic import CalendarSyncer
        
        mock_service = MagicMock()
        syncer = CalendarSyncer(mock_service)
        
        events = [
            {'summary': 'Event (1)', 'description': '', 'location': '', 'start': {}, 'end': {}},
            {'summary': 'Event [2]', 'description': '', 'location': '', 'start': {}, 'end': {}},
        ]
        
        # Regex das (1) matched
        filtered, excluded = syncer.filter_events(events, [r'\(1\)'])
        
        assert len(filtered) == 1
        assert filtered[0]['summary'] == 'Event [2]'


class TestLogErrorHandling:
    """Logging-Fehlerbehandlung."""
    
    def test_log_to_invalid_path(self, setup_test_environment, capsys):
        """Ungültiger Pfad crasht nicht."""
        from sync_logic import CalendarSyncer
        
        mock_service = MagicMock()
        syncer = CalendarSyncer(
            mock_service, 
            user_log_file='/invalid/path/that/does/not/exist/log.log'
        )
        
        # Sollte keine Exception werfen
        syncer.log("Test", user_message="Test User Message")
        
        captured = capsys.readouterr()
        assert "LOG-FEHLER" in captured.out


class TestGoogleEventStandardization:
    """Google-Event-Standardisierung."""
    
    def test_standardize_google_event_with_all_fields(self, setup_test_environment):
        """Alle Felder werden korrekt übernommen."""
        from sync_logic import CalendarSyncer
        
        mock_service = MagicMock()
        syncer = CalendarSyncer(mock_service)
        
        google_event = {
            'summary': 'Meeting',
            'description': 'Wichtiges Meeting',
            'location': 'Konferenzraum A',
            'start': {'dateTime': '2026-01-21T14:00:00+01:00'},
            'end': {'dateTime': '2026-01-21T15:00:00+01:00'},
            'id': 'event-123',  # Zusätzliche Felder sollten ignoriert werden
            'created': '2026-01-01T00:00:00Z',
        }
        
        result = syncer.standardize_event(google_event, 'google')
        
        assert result['summary'] == 'Meeting'
        assert result['description'] == 'Wichtiges Meeting'
        assert result['location'] == 'Konferenzraum A'
        assert 'id' not in result
        assert 'created' not in result
