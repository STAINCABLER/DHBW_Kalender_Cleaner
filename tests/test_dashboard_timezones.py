
import os
import json
import re
from unittest.mock import patch
import pytest

def test_dashboard_timezone_display(flask_app, temp_data_dir):
    """Prüft, ob Zeitzonen mit Offset im Dashboard angezeigt werden."""
    
    # User-Datei erstellen
    user_id = 'tz-test-user'
    user_data = {
        'email': 'tz@test.com',
        'has_accepted_disclaimer': True,
        'source_timezone': 'Europe/Berlin'
    }
    
    with open(temp_data_dir / f"{user_id}.json", 'w') as f:
        json.dump(user_data, f)
    
    # Log-Datei mocken, damit kein Fehler auftritt
    with open(temp_data_dir / f"{user_id}.log", 'w') as f:
        f.write("Log initialized.")
    
    # Patch DATA_DIR in den relevanten Modulen
    # Da config.DATA_DIR beim Import gesetzt wird, müssen wir sicherstellen,
    # dass die Module, die es verwenden, gepatcht werden.
    with patch('models.DATA_DIR', str(temp_data_dir)), \
         patch('web_server.DATA_DIR', str(temp_data_dir)):
         
        with flask_app.test_client() as client:
            with client.session_transaction() as sess:
                sess['_user_id'] = user_id
            
            response = client.get('/')
            assert response.status_code == 200
            
            # Prüfe auf HTML-Inhalt
            html = response.data.decode('utf-8')
            
            # Prüfe ob 'Europe/Berlin' vorhanden ist
            assert 'Europe/Berlin' in html
            
            # Prüfe Pattern: Zeitzone + Spaces + Klammer + Offset
            # Regex sucht nach etwas wie "Europe/Berlin   (+01:00)" oder "UTC   (+00:00)"
            # (einige Zeitzonen haben das Format garantiert)
            pattern_utc = re.compile(r'UTC\s+\(\+00:00\)')
            match_utc = pattern_utc.search(html)
            
            assert match_utc, f"UTC offset pattern nicht gefunden"
            
            # Prüfe, dass Europe/Berlin einen Offset hat (entweder +01:00 oder +02:00 je nach DST)
            pattern_berlin = re.compile(r'Europe/Berlin\s+\(\+0[12]:00\)')
            match_berlin = pattern_berlin.search(html)
            
            assert match_berlin, f"Europe/Berlin offset pattern nicht gefunden"
