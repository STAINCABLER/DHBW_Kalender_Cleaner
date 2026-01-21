"""
Tests für models.py: User-Erstellung, Persistierung, Konfiguration.
"""

import json


class TestUserCreation:
    """User-Instanziierung."""
    
    def test_user_creation(self, temp_data_dir, setup_test_environment):
        """User-Objekt wird korrekt initialisiert."""
        # Reload config mit neuem DATA_DIR
        import importlib
        import config
        config.DATA_DIR = str(temp_data_dir)
        importlib.reload(config)
        
        import models
        importlib.reload(models)
        
        user = models.User('test-user-123')
        
        assert user.id == 'test-user-123'
        assert user.data['id'] == 'test-user-123'
    
    def test_user_get_id(self, temp_data_dir, setup_test_environment):
        """get_id() liefert String."""
        import importlib
        import config
        config.DATA_DIR = str(temp_data_dir)
        importlib.reload(config)
        
        import models
        importlib.reload(models)
        
        user = models.User('user-456')
        
        assert user.get_id() == 'user-456'
        assert isinstance(user.get_id(), str)
    
    def test_user_exists_false_for_new_user(self, temp_data_dir, setup_test_environment):
        """exists() liefert False für unbekannte IDs."""
        import importlib
        import config
        config.DATA_DIR = str(temp_data_dir)
        importlib.reload(config)
        
        import models
        importlib.reload(models)
        
        assert models.User.exists('non-existent-user') is False
    
    def test_user_exists_true_after_save(self, temp_data_dir, setup_test_environment):
        """exists() liefert True nach save()."""
        import importlib
        import config
        config.DATA_DIR = str(temp_data_dir)
        importlib.reload(config)
        
        import models
        importlib.reload(models)
        
        user = models.User('saved-user')
        user.save()
        
        assert models.User.exists('saved-user') is True


class TestUserPersistence:
    """Datenpersistierung."""
    
    def test_user_save_creates_file(self, temp_data_dir, setup_test_environment):
        """save() erstellt JSON-Datei."""
        import importlib
        import config
        config.DATA_DIR = str(temp_data_dir)
        importlib.reload(config)
        
        import models
        importlib.reload(models)
        
        user = models.User('persist-user')
        user.data['email'] = 'test@example.com'
        user.save()
        
        expected_file = temp_data_dir / 'persist-user.json'
        assert expected_file.exists()
        
        with open(expected_file) as f:
            saved_data = json.load(f)
        
        assert saved_data['email'] == 'test@example.com'
    
    def test_user_load_existing_data(self, temp_data_dir, setup_test_environment):
        """Bestehende Daten werden geladen."""
        import importlib
        import config
        config.DATA_DIR = str(temp_data_dir)
        importlib.reload(config)
        
        import models
        importlib.reload(models)
        
        # Erstelle Datei manuell
        user_file = temp_data_dir / 'load-test.json'
        test_data = {
            'id': 'load-test',
            'email': 'existing@example.com',
            'source_id': 'https://example.com/cal.ics'
        }
        with open(user_file, 'w') as f:
            json.dump(test_data, f)
        
        # Lade User
        user = models.User('load-test')
        
        assert user.data['email'] == 'existing@example.com'
        assert user.data['source_id'] == 'https://example.com/cal.ics'


class TestUserConfig:
    """Benutzerkonfiguration."""
    
    def test_get_config_defaults(self, temp_data_dir, setup_test_environment):
        """get_config() liefert Standardwerte."""
        import importlib
        import config
        config.DATA_DIR = str(temp_data_dir)
        importlib.reload(config)
        
        import models
        importlib.reload(models)
        
        user = models.User('config-test')
        cfg = user.get_config()
        
        assert cfg['email'] == ''
        assert cfg['source_id'] == ''
        assert cfg['target_id'] == ''
        assert cfg['regex_patterns'] == []
        assert cfg['source_timezone'] == 'Europe/Berlin'
    
    def test_set_config(self, temp_data_dir, setup_test_environment):
        """set_config() speichert Werte."""
        import importlib
        import config
        config.DATA_DIR = str(temp_data_dir)
        importlib.reload(config)
        
        import models
        importlib.reload(models)
        
        user = models.User('config-set-test')
        user.set_config(
            source_id='https://dhbw.de/calendar.ics',
            target_id='target-cal-id',
            regex_list=[r'^Feiertag:', r'Abgesagt'],
            source_timezone='Europe/Vienna'
        )
        
        cfg = user.get_config()
        
        assert cfg['source_id'] == 'https://dhbw.de/calendar.ics'
        assert cfg['target_id'] == 'target-cal-id'
        assert cfg['regex_patterns'] == [r'^Feiertag:', r'Abgesagt']
        assert cfg['source_timezone'] == 'Europe/Vienna'


class TestUserAuth:
    """Authentifizierungsdaten."""
    
    def test_set_auth(self, temp_data_dir, setup_test_environment):
        """set_auth() speichert E-Mail und Token."""
        import importlib
        import config
        config.DATA_DIR = str(temp_data_dir)
        importlib.reload(config)
        
        import models
        importlib.reload(models)
        
        user = models.User('auth-test')
        user.set_auth('user@example.com', 'encrypted-token-123')
        
        assert user.data['email'] == 'user@example.com'
        assert user.data['refresh_token_encrypted'] == 'encrypted-token-123'


class TestUserDisclaimer:
    """Disclaimer-Status."""
    
    def test_disclaimer_default_false(self, temp_data_dir, setup_test_environment):
        """Disclaimer ist standardmäßig nicht akzeptiert."""
        import importlib
        import config
        config.DATA_DIR = str(temp_data_dir)
        importlib.reload(config)
        
        import models
        importlib.reload(models)
        
        user = models.User('disclaimer-test')
        
        assert user.has_accepted_disclaimer() is False
    
    def test_set_disclaimer_accepted(self, temp_data_dir, setup_test_environment):
        """set_disclaimer_accepted() markiert als akzeptiert."""
        import importlib
        import config
        config.DATA_DIR = str(temp_data_dir)
        importlib.reload(config)
        
        import models
        importlib.reload(models)
        
        user = models.User('disclaimer-accept-test')
        user.set_disclaimer_accepted()
        
        assert user.has_accepted_disclaimer() is True


class TestUserDeletion:
    """Account-Löschung."""
    
    def test_delete_removes_config_file(self, temp_data_dir, setup_test_environment):
        """delete() entfernt Konfigurationsdatei."""
        import importlib
        import config
        config.DATA_DIR = str(temp_data_dir)
        importlib.reload(config)
        
        import models
        importlib.reload(models)
        
        user = models.User('delete-test')
        user.save()
        
        config_file = temp_data_dir / 'delete-test.json'
        assert config_file.exists()
        
        user.delete()
        
        assert not config_file.exists()
    
    def test_delete_removes_log_file(self, temp_data_dir, setup_test_environment):
        """delete() entfernt Log-Datei."""
        import importlib
        import config
        config.DATA_DIR = str(temp_data_dir)
        importlib.reload(config)
        
        import models
        importlib.reload(models)
        
        user = models.User('delete-log-test')
        user.save()
        
        # Erstelle Log-Datei
        log_file = temp_data_dir / 'delete-log-test.log'
        log_file.write_text('Test log entry')
        
        user.delete()
        
        assert not log_file.exists()
    
    def test_delete_removes_cache_files(self, temp_data_dir, setup_test_environment):
        """delete() entfernt Cache-Dateien."""
        import importlib
        import config
        config.DATA_DIR = str(temp_data_dir)
        importlib.reload(config)
        
        import models
        importlib.reload(models)
        
        user = models.User('delete-cache-test')
        user.save()
        
        # Erstelle Cache-Verzeichnis und Dateien
        cache_dir = temp_data_dir / '.cache'
        cache_dir.mkdir()
        
        ics_cache = cache_dir / 'delete-cache-test_ics.json'
        events_cache = cache_dir / 'delete-cache-test_events.json'
        
        ics_cache.write_text('{}')
        events_cache.write_text('{}')
        
        user.delete()
        
        assert not ics_cache.exists()
        assert not events_cache.exists()


class TestUserStaticMethods:
    """Statische Methoden."""
    
    def test_load_existing_user(self, temp_data_dir, setup_test_environment):
        """load() lädt existierenden User."""
        import importlib
        import config
        config.DATA_DIR = str(temp_data_dir)
        importlib.reload(config)
        
        import models
        importlib.reload(models)
        
        # Erstelle User
        original = models.User('load-static-test')
        original.data['email'] = 'static@test.com'
        original.save()
        
        # Lade mit statischer Methode
        loaded = models.User.load('load-static-test')
        
        assert loaded is not None
        assert loaded.data['email'] == 'static@test.com'
    
    def test_load_non_existing_user(self, temp_data_dir, setup_test_environment):
        """load() gibt None für unbekannte IDs zurück."""
        import importlib
        import config
        config.DATA_DIR = str(temp_data_dir)
        importlib.reload(config)
        
        import models
        importlib.reload(models)
        
        loaded = models.User.load('non-existent-user')
        
        assert loaded is None
