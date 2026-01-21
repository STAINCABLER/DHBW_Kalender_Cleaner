import re
import os
import json
import hashlib
import requests
import arrow
import time
from datetime import datetime, timedelta, timezone
from googleapiclient.errors import HttpError
from ics import Calendar

# Cache-Verzeichnis für ICS-ETags und Event-Hashes
# Dynamisch aus DATA_DIR ableiten für Container- und Test-Kompatibilität
DATA_DIR = os.getenv('DATA_DIR', '/app/data')
CACHE_DIR = os.path.join(DATA_DIR, '.cache')


class CalendarSyncer:
    def __init__(self, service, log_callback=print, user_log_file=None, user_id=None):
        self.service = service
        self.system_log = log_callback  # Dies ist print() -> geht an system.log/docker logs
        self.user_log_file = user_log_file  # Pfad zur <user_id>.log
        self.user_id = user_id  # Für Cache-Dateien
        
        # Cache-Verzeichnis erstellen
        os.makedirs(CACHE_DIR, exist_ok=True)

    def log(self, message, user_message=None):
        """Schreibt in den System-Log und optional in den User-Log."""
        # 1. Immer in den System-Log (für den Admin) - technisch detailliert
        self.system_log(message) 
        
        # 2. Nur wenn user_message gesetzt ist, in die User-Log-Datei schreiben
        if user_message and self.user_log_file:
            try:
                with open(self.user_log_file, 'a') as f:
                    f.write(user_message + '\n')
            except Exception as e:
                self.system_log(f"!!! LOG-FEHLER: Konnte nicht in User-Log schreiben: {e}")
    
    def log_user(self, message):
        """Loggt eine Nachricht sowohl in System- als auch User-Log (gleicher Text)."""
        self.system_log(message)
        if self.user_log_file:
            try:
                with open(self.user_log_file, 'a') as f:
                    f.write(message + '\n')
            except Exception as e:
                self.system_log(f"!!! LOG-FEHLER: Konnte nicht in User-Log schreiben: {e}")

    # Cache-Funktionen
    
    def _get_cache_path(self, cache_type):
        """Gibt den Pfad zur Cache-Datei für diesen User zurück."""
        if not self.user_id:
            return None
        return os.path.join(CACHE_DIR, f"{self.user_id}_{cache_type}.json")
    
    def _load_cache(self, cache_type):
        """Lädt Cache-Daten aus Datei."""
        cache_path = self._get_cache_path(cache_type)
        if not cache_path or not os.path.exists(cache_path):
            return {}
        try:
            with open(cache_path, 'r') as f:
                return json.load(f)
        except Exception:
            return {}
    
    def _save_cache(self, cache_type, data):
        """Speichert Cache-Daten in Datei."""
        cache_path = self._get_cache_path(cache_type)
        if not cache_path:
            return
        try:
            with open(cache_path, 'w') as f:
                json.dump(data, f)
        except Exception as e:
            self.log(f"Cache-Fehler: Konnte {cache_type} nicht speichern: {e}")
    
    def _compute_event_hash(self, event):
        """Berechnet einen Hash für ein Event zur Delta-Erkennung."""
        # Erstelle einen eindeutigen String aus den Event-Daten
        hash_input = json.dumps({
            'summary': event.get('summary', ''),
            'description': event.get('description', ''),
            'location': event.get('location', ''),
            'start': event.get('start', {}),
            'end': event.get('end', {}),
        }, sort_keys=True)
        return hashlib.md5(hash_input.encode()).hexdigest()
    
    def _get_event_key(self, event):
        """Erstellt einen eindeutigen Schlüssel für ein Event (für Delta-Sync)."""
        start = event.get('start', {})
        start_str = start.get('dateTime') or start.get('date') or ''
        summary = event.get('summary', '')
        # Kombination aus Start-Zeit und Titel als Key
        return f"{start_str}|{summary}"

    def standardize_event(self, event_data, source_type):
        if source_type == 'google':
            return {
                'summary': event_data.get('summary', 'Kein Titel'),
                'description': event_data.get('description', ''),
                'location': event_data.get('location', ''),
                'start': event_data.get('start'),
                'end': event_data.get('end'),
            }
        elif source_type == 'ics':
            # Diese Funktion erhält jetzt zeitzonenbewusste 'arrow'-Objekte
            start_arrow = event_data.begin
            end_arrow = event_data.end

            start, end = {}, {}
            if event_data.all_day:
                start['date'] = start_arrow.format('YYYY-MM-DD')
                end['date'] = end_arrow.shift(days=1).format('YYYY-MM-DD')
            else:
                # isoformat() enthält jetzt den korrekten Offset (z.B. +01:00)
                start['dateTime'] = start_arrow.isoformat()
                end['dateTime'] = end_arrow.isoformat()
            return {
                'summary': event_data.name or 'Kein Titel',
                'description': event_data.description or '',
                'location': event_data.location or '',
                'start': start,
                'end': end,
            }

    def fetch_google_events(self, calendar_id, time_min=None, time_max=None):
        self.log(f"Google Calendar API: Abruf für {calendar_id}")
        all_events = []
        page_token = None
        
        try:
            while True:
                params = {
                    'calendarId': calendar_id,
                    'singleEvents': True,
                    'orderBy': 'startTime',
                    'maxResults': 250  # Google API Maximum
                }
                # Optional time window nur hinzufügen, wenn gesetzt
                if time_min:
                    params['timeMin'] = time_min
                if time_max:
                    params['timeMax'] = time_max
                if page_token:
                    params['pageToken'] = page_token

                events_result = self.service.events().list(**params).execute()
                items = events_result.get('items', [])
                all_events.extend([self.standardize_event(e, 'google') for e in items])
                
                page_token = events_result.get('nextPageToken')
                if not page_token:
                    break
                    
            self.log(f"Google API: {len(all_events)} Events abgerufen (über {len(all_events)//250 + 1} Seiten)")
            return all_events
        except HttpError as error:
            self.log_user("Fehler beim Abrufen der Google-Ereignisse.")
            self.log(f"Google API Error: {error}")
            return []

    def fetch_ics_events(self, url, time_min_dt=None, time_max_dt=None, source_timezone='Europe/Berlin'):
        """Ruft Ereignisse aus einer ICS-URL ab mit ETag-Caching und filtert sie nach Zeit."""
        self.log(f"ICS-Abruf: {url}")
        self.log(f"Zeitzone: {source_timezone}")
        
        try:
            # ETag/Last-Modified Caching
            ics_cache = self._load_cache('ics')
            cached_etag = ics_cache.get('etag')
            cached_last_modified = ics_cache.get('last_modified')
            cached_content = ics_cache.get('content')
            
            headers = {}
            if cached_etag:
                headers['If-None-Match'] = cached_etag
            if cached_last_modified:
                headers['If-Modified-Since'] = cached_last_modified
            
            response = requests.get(url, headers=headers, timeout=30)
            
            # 304 Not Modified = ICS hat sich nicht geändert
            if response.status_code == 304 and cached_content:
                self.log("ICS: 304 Not Modified, Cache verwendet")
                ics_content = cached_content
            else:
                response.raise_for_status()
                ics_content = response.text
                
                # Cache aktualisieren
                new_etag = response.headers.get('ETag')
                new_last_modified = response.headers.get('Last-Modified')
                if new_etag or new_last_modified:
                    self._save_cache('ics', {
                        'etag': new_etag,
                        'last_modified': new_last_modified,
                        'content': ics_content,
                        'timestamp': datetime.now(timezone.utc).isoformat()
                    })
                    self.log(f"ICS: Cache aktualisiert (ETag={new_etag is not None})")
            
            calendar = Calendar(ics_content)
            
            events = []
            seen_uids = set()  # Deduplizierung nach UID
            duplicate_count = 0
            
            for event in calendar.events:
                if not event.end or not event.begin:
                    continue

                # Deduplizierung: Überspringe Events mit bereits gesehener UID
                event_uid = event.uid if hasattr(event, 'uid') and event.uid else None
                if event_uid:
                    if event_uid in seen_uids:
                        duplicate_count += 1
                        continue
                    seen_uids.add(event_uid)

                # Zeitzonen-Korrektur
                start_arrow = event.begin
                end_arrow = event.end
                start_arrow = arrow.get(start_arrow.naive, tzinfo=source_timezone)
                end_arrow = arrow.get(end_arrow.naive, tzinfo=source_timezone)
                event.begin = start_arrow
                event.end = end_arrow

                # Zeitfilter
                if time_min_dt is None or time_max_dt is None:
                    events.append(self.standardize_event(event, 'ics'))
                else:
                    if event.end > time_min_dt and event.begin < time_max_dt:
                        events.append(self.standardize_event(event, 'ics'))
            
            if duplicate_count > 0:
                self.log(f"ICS: {duplicate_count} Duplikate übersprungen")
            return events
        except Exception as e:
            self.log_user("Fehler beim Abrufen des Kalenders.")
            self.log(f"ICS Parse Error: {e}")
            return []

    def filter_events(self, events, regex_patterns_raw):
        if not regex_patterns_raw:
            return events, 0
        
        regex_patterns = []
        invalid_count = 0
        for pattern in regex_patterns_raw:
            if not pattern:
                continue
            try:
                regex_patterns.append(re.compile(pattern, re.IGNORECASE))
            except re.error as e:
                invalid_count += 1
                self.log(f"Ungültiges RegEx '{pattern}': {e}")

        if invalid_count > 0 and not regex_patterns:
            self.log_user("Ungültige Filterregeln - alle Ereignisse bleiben erhalten.")
        elif invalid_count > 0:
            self.log(f"RegEx: {invalid_count} ungültige Muster ignoriert")

        if not regex_patterns:
            return events, 0

        filtered_events = []
        excluded_count = 0
        
        for event in events:
            summary = event['summary']
            is_excluded = any(pattern.search(summary) for pattern in regex_patterns)
            if not is_excluded:
                filtered_events.append(event)
            else:
                excluded_count += 1
                self.log(f"Filter: '{summary}' ausgeschlossen")
                
        self.log(f"Filter: {excluded_count} ausgeschlossen, {len(filtered_events)} verbleiben")
        return filtered_events, excluded_count

    def _fetch_target_events(self, target_id, time_min=None, time_max=None):
        """Holt alle Events aus dem Zielkalender für Cache-Initialisierung."""
        self.log(f"Zielkalender-Scan: Hole existierende Events aus {target_id}")
        all_events = []
        page_token = None
        
        try:
            while True:
                params = {
                    'calendarId': target_id,
                    'singleEvents': True,
                    'orderBy': 'startTime',
                    'maxResults': 250
                }
                if time_min:
                    params['timeMin'] = time_min
                if time_max:
                    params['timeMax'] = time_max
                if page_token:
                    params['pageToken'] = page_token

                events_result = self.service.events().list(**params).execute()
                items = events_result.get('items', [])
                all_events.extend(items)
                
                page_token = events_result.get('nextPageToken')
                if not page_token:
                    break
                    
            self.log(f"Zielkalender: {len(all_events)} existierende Events gefunden")
            return all_events
        except HttpError as error:
            self.log(f"Zielkalender-Scan fehlgeschlagen: {error}")
            return []

    def _initialize_cache_from_target(self, target_id, time_min=None, time_max=None):
        """Initialisiert den Cache basierend auf existierenden Events im Zielkalender."""
        existing_events = self._fetch_target_events(target_id, time_min, time_max)
        
        cached_hashes = {}
        cached_event_ids = {}
        
        for event in existing_events:
            # Standardisiere das Event für Hash-Berechnung
            std_event = self.standardize_event(event, 'google')
            key = self._get_event_key(std_event)
            hash_val = self._compute_event_hash(std_event)
            
            # Event-ID aus Google-Event extrahieren
            event_id = event.get('id')
            if event_id:
                cached_hashes[key] = hash_val
                cached_event_ids[key] = event_id
        
        self.log(f"Cache initialisiert mit {len(cached_event_ids)} Events aus Zielkalender")
        return cached_hashes, cached_event_ids

    def sync_to_target(
        self,
        target_id,
        events_to_sync,
        time_min=None,
        time_max=None,
        delete_pause_every=50,
        create_pause_every=50,
        max_attempts=3,
    ):
        """Synchronisiert Events zum Zielkalender mittels Delta-Sync und Batch-API."""
        
        # Delta-Sync vorbereiten
        event_cache = self._load_cache('events')
        cached_hashes = event_cache.get('hashes', {})
        cached_event_ids = event_cache.get('event_ids', {})
        
        # KRITISCH: Bei leerem Cache erst den Zielkalender scannen!
        # Verhindert Duplikate beim ersten Sync oder nach Cache-Verlust
        if not cached_hashes and not cached_event_ids:
            self.log("Cache leer - initialisiere aus Zielkalender (Duplikat-Prävention)")
            cached_hashes, cached_event_ids = self._initialize_cache_from_target(
                target_id, time_min, time_max
            )
        
        # Berechne Hashes für neue Events
        new_hashes = {}
        new_events_by_key = {}
        for event in events_to_sync:
            key = self._get_event_key(event)
            hash_val = self._compute_event_hash(event)
            new_hashes[key] = hash_val
            new_events_by_key[key] = event
        
        # Ermittle Änderungen
        keys_to_add = []
        keys_to_update = []
        keys_to_delete = []
        keys_unchanged = []
        
        # Neue oder geänderte Events
        for key, hash_val in new_hashes.items():
            if key not in cached_hashes:
                keys_to_add.append(key)
            elif cached_hashes[key] != hash_val:
                keys_to_update.append(key)
            else:
                keys_unchanged.append(key)
        
        # Gelöschte Events (im Cache aber nicht mehr in der Quelle)
        for key in cached_hashes:
            if key not in new_hashes:
                keys_to_delete.append(key)
        
        # Technisches Log für Admin
        self.log(f"Delta-Sync: {len(keys_to_add)} neu, {len(keys_to_update)} geändert, "
                 f"{len(keys_to_delete)} zu löschen, {len(keys_unchanged)} unverändert")
        
        # Wenn alles unverändert ist, können wir abkürzen
        if not keys_to_add and not keys_to_update and not keys_to_delete:
            self.log_user("Keine Änderungen erkannt.")
            return 0, 0
        
        deleted_count = 0
        created_count = 0
        
        # Events löschen (Batch API)
        events_to_delete_ids = []
        
        # Events die nicht mehr existieren
        for key in keys_to_delete:
            if key in cached_event_ids:
                events_to_delete_ids.append(cached_event_ids[key])
        
        # Events die geändert wurden (löschen + neu erstellen ist einfacher als update)
        for key in keys_to_update:
            if key in cached_event_ids:
                events_to_delete_ids.append(cached_event_ids[key])
        
        if events_to_delete_ids:
            self.log(f"Batch-Delete: {len(events_to_delete_ids)} Events werden entfernt")
            deleted_count = self._batch_delete_events(target_id, events_to_delete_ids, max_attempts)
        
        # Events erstellen (Batch API)
        events_to_create = []
        keys_for_new_events = []
        
        for key in keys_to_add + keys_to_update:
            events_to_create.append(new_events_by_key[key])
            keys_for_new_events.append(key)
        
        if events_to_create:
            self.log(f"Batch-Insert: {len(events_to_create)} Events werden erstellt")
            created_ids = self._batch_create_events(target_id, events_to_create, max_attempts)
            created_count = len([x for x in created_ids if x])
            
            # Update cached_event_ids mit neuen IDs
            for i, key in enumerate(keys_for_new_events):
                if i < len(created_ids) and created_ids[i]:
                    cached_event_ids[key] = created_ids[i]
        
        # Cache aktualisieren
        for key in keys_to_delete:
            cached_hashes.pop(key, None)
            cached_event_ids.pop(key, None)
        
        # Aktualisiere Hashes
        for key, hash_val in new_hashes.items():
            cached_hashes[key] = hash_val
        
        self._save_cache('events', {
            'hashes': cached_hashes,
            'event_ids': cached_event_ids,
            'last_sync': datetime.now(timezone.utc).isoformat()
        })
        
        # User-freundliche Zusammenfassung
        self.log_user(f"{created_count} erstellt, {deleted_count} gelöscht.")
        return created_count, deleted_count
    
    def _batch_delete_events(self, calendar_id, event_ids, max_attempts=3):
        """Löscht Events in Batches von 50 (Google API Maximum)."""
        deleted_count = 0
        batch_size = 50
        
        for i in range(0, len(event_ids), batch_size):
            batch_ids = event_ids[i:i + batch_size]
            batch_deleted = 0
            
            def delete_callback(request_id, response, exception):
                nonlocal batch_deleted
                if exception:
                    if hasattr(exception, 'resp'):
                        # 404/410 = bereits gelöscht, zählt als Erfolg
                        if exception.resp.status in (404, 410):
                            batch_deleted += 1
                            return
                    self.log(f"Batch-Delete Error: {exception}")
                else:
                    batch_deleted += 1
            
            for attempt in range(max_attempts):
                try:
                    batch = self.service.new_batch_http_request(callback=delete_callback)
                    for event_id in batch_ids:
                        batch.add(self.service.events().delete(
                            calendarId=calendar_id,
                            eventId=event_id
                        ))
                    batch.execute()
                    deleted_count += batch_deleted
                    break
                except HttpError as e:
                    if attempt < max_attempts - 1:
                        self.log(f"Batch-Delete Retry {attempt + 2}/{max_attempts}")
                        time.sleep(2 ** attempt)
                    else:
                        self.log(f"Batch-Delete Failed: {e}")
            
            # Kurze Pause zwischen Batches um Rate-Limits zu vermeiden
            if i + batch_size < len(event_ids):
                time.sleep(0.5)
        
        return deleted_count
    
    def _batch_create_events(self, calendar_id, events, max_attempts=3):
        """Erstellt Events in Batches von 50 (Google API Maximum)."""
        created_ids = []
        batch_size = 50
        
        for i in range(0, len(events), batch_size):
            batch_events = events[i:i + batch_size]
            batch_ids = [None] * len(batch_events)
            
            def create_callback(request_id, response, exception):
                idx = int(request_id)
                if exception:
                    self.log(f"Batch-Insert Error #{idx}: {exception}")
                else:
                    batch_ids[idx] = response.get('id')
            
            for attempt in range(max_attempts):
                try:
                    batch = self.service.new_batch_http_request(callback=create_callback)
                    for idx, event in enumerate(batch_events):
                        batch.add(
                            self.service.events().insert(
                                calendarId=calendar_id,
                                body=event
                            ),
                            request_id=str(idx)
                        )
                    batch.execute()
                    created_ids.extend(batch_ids)
                    break
                except HttpError as e:
                    if attempt < max_attempts - 1:
                        self.log(f"Batch-Insert Retry {attempt + 2}/{max_attempts}")
                        time.sleep(2 ** attempt)
                    else:
                        self.log(f"Batch-Insert Failed: {e}")
                        created_ids.extend([None] * len(batch_events))
            
            # Kurze Pause zwischen Batches
            if i + batch_size < len(events):
                time.sleep(0.5)
        
        return created_ids
    
    def clear_cache(self):
        """Löscht den Cache für diesen User (für Full-Sync oder Reset)."""
        for cache_type in ['ics', 'events']:
            cache_path = self._get_cache_path(cache_type)
            if cache_path and os.path.exists(cache_path):
                try:
                    os.remove(cache_path)
                    self.log(f"Cache '{cache_type}' gelöscht")
                except Exception as e:
                    self.log(f"Cache-Löschfehler '{cache_type}': {e}")

    def run_sync(self, config):
        """Führt den gesamten Sync-Prozess für eine gegebene Konfiguration aus."""
        user_email = config.get('email', 'Unbekannt')
        self.log_user("Synchronisation gestartet...")
        self.log(f"Sync-Start für user={user_email}, source={config.get('source_id')}")
        SOURCE_CALENDAR_ID = config.get('source_id')
        TARGET_CALENDAR_ID = config.get('target_id')
        REGEX_PATTERNS = config.get('regex_patterns', [])
        # Zeitzone des Benutzers holen, Standard ist Berlin
        SOURCE_TIMEZONE = config.get('source_timezone', 'Europe/Berlin') 

        if not SOURCE_CALENDAR_ID or not TARGET_CALENDAR_ID:
            self.log_user("Fehler: Quell- oder Ziel-ID nicht konfiguriert.")
            self.log("Sync abgebrochen: source_id oder target_id fehlt")
            return

        # Zeitfenster: 6 Monate in Vergangenheit und Zukunft synchronisieren
        now = datetime.now(timezone.utc)
        time_min_dt = now - timedelta(days=180)  # 6 Monate in die Vergangenheit
        time_max_dt = now + timedelta(days=180)  # 6 Monate in die Zukunft
        
        time_min_iso = time_min_dt.isoformat()
        time_max_iso = time_max_dt.isoformat()
        self.log(f"Zeitfenster: {time_min_dt.strftime('%Y-%m-%d')} bis {time_max_dt.strftime('%Y-%m-%d')}")

        source_events = []
        is_ics = SOURCE_CALENDAR_ID.startswith('http://') or SOURCE_CALENDAR_ID.startswith('https://')

        if is_ics:
            # Für ICS brauchen wir datetime-Objekte als Arrow-kompatible Zeitfilter
            source_events = self.fetch_ics_events(SOURCE_CALENDAR_ID, time_min_dt, time_max_dt, SOURCE_TIMEZONE)
        else:
            source_events = self.fetch_google_events(SOURCE_CALENDAR_ID, time_min_iso, time_max_iso)

        self.log(f"Quelle: {len(source_events)} Events")
        eligible_events, excluded = self.filter_events(source_events, REGEX_PATTERNS)
        created, deleted = self.sync_to_target(TARGET_CALENDAR_ID, eligible_events, time_min_iso, time_max_iso)

        self.log_user(f"Sync abgeschlossen: {created} erstellt, {deleted} gelöscht, {excluded} gefiltert.")
        self.log(f"Sync-Ende: created={created}, deleted={deleted}, excluded={excluded}")