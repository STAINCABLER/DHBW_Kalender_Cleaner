"""
Tests für config.py: Validierung, Verschlüsselung, Konstanten.
"""

import os
import pytest
from cryptography.fernet import Fernet


class TestConfigValidation:
    """Konfigurationsvalidierung."""
    
    def test_validate_config_success(self, setup_test_environment):
        """Validierung erfolgreich bei vollständiger Konfiguration."""
        import importlib
        import config
        importlib.reload(config)
        
        # Sollte keine Exception werfen
        config.validate_config()
    
    def test_validate_config_missing_vars(self, monkeypatch):
        """Validierung schlägt bei fehlenden Variablen fehl."""
        # Entferne eine erforderliche Variable
        monkeypatch.delenv('GOOGLE_CLIENT_ID', raising=False)
        
        import importlib
        import config
        importlib.reload(config)
        
        with pytest.raises(ValueError) as exc_info:
            config.validate_config()
        
        assert 'GOOGLE_CLIENT_ID' in str(exc_info.value)


class TestEncryption:
    """Fernet-Verschlüsselung."""
    
    def test_encrypt_decrypt_roundtrip(self, setup_test_environment):
        """Verschlüsselung und Entschlüsselung sind invertierbar."""
        import importlib
        import config
        importlib.reload(config)
        config._fernet = None  # Reset cached fernet
        
        original_text = "Dies ist ein geheimer Refresh-Token!"
        
        encrypted = config.encrypt(original_text)
        decrypted = config.decrypt(encrypted)
        
        assert decrypted == original_text
        assert encrypted != original_text  # Verschlüsselt sollte anders sein
    
    def test_encrypt_produces_different_ciphertext(self, setup_test_environment):
        """Jede Verschlüsselung erzeugt unterschiedlichen Ciphertext (IV)."""
        import importlib
        import config
        importlib.reload(config)
        config._fernet = None
        
        text = "Gleicher Text"
        
        encrypted1 = config.encrypt(text)
        encrypted2 = config.encrypt(text)
        
        # Fernet verwendet zufällige IVs, daher unterschiedliche Ciphertexts
        assert encrypted1 != encrypted2
        
        # Beide sollten aber zum gleichen Klartext entschlüsseln
        assert config.decrypt(encrypted1) == text
        assert config.decrypt(encrypted2) == text
    
    def test_decrypt_invalid_token_fails(self, setup_test_environment):
        """Entschlüsselung ungültiger Tokens wirft Exception."""
        import importlib
        import config
        importlib.reload(config)
        config._fernet = None
        
        with pytest.raises(Exception):  # Fernet wirft InvalidToken
            config.decrypt("ungültiger-token")
    
    def test_get_fernet_invalid_key(self, monkeypatch):
        """Ungültiger SECRET_KEY wirft ValueError."""
        monkeypatch.setenv('SECRET_KEY', 'ungültiger-key')
        
        import importlib
        import config
        importlib.reload(config)
        
        with pytest.raises(ValueError) as exc_info:
            config.get_fernet()
        
        assert 'SECRET_KEY ist ungültig' in str(exc_info.value)


class TestGoogleScopes:
    """OAuth Scopes."""
    
    def test_google_scopes_contains_calendar(self, setup_test_environment):
        """Calendar-Scope ist enthalten."""
        import config
        
        assert 'https://www.googleapis.com/auth/calendar' in config.GOOGLE_SCOPES
    
    def test_google_scopes_contains_openid(self, setup_test_environment):
        """OpenID-Scopes für Login sind enthalten."""
        import config
        
        assert 'openid' in config.GOOGLE_SCOPES
        assert 'https://www.googleapis.com/auth/userinfo.email' in config.GOOGLE_SCOPES


class TestRateLimits:
    """Rate-Limit-Konstanten."""
    
    def test_rate_limits_are_defined(self, setup_test_environment):
        """Alle Rate-Limit-Werte sind definiert."""
        import config
        
        assert config.RATE_LIMIT_DEFAULT is not None
        assert config.RATE_LIMIT_LOGIN is not None
        assert config.RATE_LIMIT_SYNC is not None
    
    def test_rate_limit_default_is_list(self, setup_test_environment):
        """RATE_LIMIT_DEFAULT ist eine Liste."""
        import config
        
        assert isinstance(config.RATE_LIMIT_DEFAULT, list)
        assert len(config.RATE_LIMIT_DEFAULT) > 0


class TestAppMetadata:
    """App-Metadaten."""
    
    def test_app_name_defined(self, setup_test_environment):
        """APP_NAME ist gesetzt."""
        import config
        
        assert config.APP_NAME == "DHBW Calendar Cleaner"
    
    def test_app_website_is_url(self, setup_test_environment):
        """APP_WEBSITE ist eine gültige URL."""
        import config
        
        assert config.APP_WEBSITE.startswith('http')
