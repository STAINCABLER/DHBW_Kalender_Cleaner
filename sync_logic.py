import re
import requests
import arrow
import time
from datetime import datetime, timedelta, timezone
from googleapiclient.errors import HttpError
from ics import Calendar

class CalendarSyncer:
    def __init__(self, service, log_callback=print, user_log_file=None):
        self.service = service
        self.system_log = log_callback  # Dies ist print() -> geht an system.log/docker logs
        self.user_log_file = user_log_file # Pfad zur <user_id>.log

    def log(self, message):
        # 1. Immer in den System-Log (für den Admin)
        self.system_log(message) 
        
        # 2. Zusätzlich in die User-Log-Datei (für das UI)
        if self.user_log_file:
            try:
                # 'a' für append (anhängen)
                with open(self.user_log_file, 'a') as f:
                    # Fügt die Nachricht mit einem Zeilenumbruch an
                    f.write(message + '\n')
            except Exception as e:
                # Wichtig: Der Sync darf nicht fehlschlagen, nur weil das Loggen fehlschlägt.
                self.system_log(f"!!! KRITISCHER LOG-FEHLER: Konnte nicht in User-Log schreiben {self.user_log_file}: {e}")

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
        self.log(f"Rufe Google Kalender-Ereignisse ab für: {calendar_id}")
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
                    
            self.log(f"  -> Insgesamt {len(all_events)} Events von Google Calendar abgerufen (über {len(all_events)//250 + 1} Seiten)")
            return all_events
        except HttpError as error:
            self.log(f'Fehler beim Abrufen von Google-Ereignissen: {error}')
            return []

    def fetch_ics_events(self, url, time_min_dt=None, time_max_dt=None, source_timezone='Europe/Berlin'): # Zeitzone hinzugefügt
        """Ruft Ereignisse aus einer ICS-URL ab und filtert sie nach Zeit."""
        self.log(f"Rufe ICS-Ereignisse ab von: {url}")
        self.log(f"Verwende Quell-Zeitzone: {source_timezone} für 'naive' Zeitangaben.")
        try:
            response = requests.get(url)
            response.raise_for_status()
            calendar = Calendar(response.text)
            
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

                # --- *** NEUE ZEITZONEN-KORREKTUR START *** ---
                start_arrow = event.begin
                end_arrow = event.end

                # Wir ignorieren die (potenziell falsche) Zeitzone der ICS-Datei
                # und stempeln die "naive" Zeit (z.B. 09:00) mit der vom Benutzer gewählten Zeitzone.
                # Das löst das 1-Stunden-Offset-Problem.
                start_arrow = arrow.get(start_arrow.naive, tzinfo=source_timezone)
                end_arrow = arrow.get(end_arrow.naive, tzinfo=source_timezone)
                
                event.begin = start_arrow
                event.end = end_arrow
                # --- *** NEUE ZEITZONEN-KORREKTUR ENDE *** ---

                # Falls kein Zeitfenster gesetzt ist, alle Ereignisse übernehmen
                if time_min_dt is None or time_max_dt is None:
                    events.append(self.standardize_event(event, 'ics'))
                else:
                    if event.end > time_min_dt and event.begin < time_max_dt:
                        events.append(self.standardize_event(event, 'ics'))
            
            if duplicate_count > 0:
                self.log(f"  -> {duplicate_count} doppelte ICS-Events übersprungen (gleiche UID)")
            return events
        except Exception as e:
            self.log(f'Fehler beim Abrufen oder Parsen der ICS-URL: {e}')
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
                self.log(f"  -> Ignoriere ungültiges RegEx-Muster '{pattern}': {e}")

        if invalid_count > 0 and not regex_patterns:
            self.log("Keine gültigen RegEx-Filter gefunden. Alle Ereignisse bleiben erhalten.")
        elif invalid_count > 0:
            self.log(f"  -> {invalid_count} ungültige RegEx-Muster ignoriert.")

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
                self.log(f"  -> Ausgeschlossen: '{summary}'")
                
        self.log(f"{excluded_count} Ereignisse ausgeschlossen, {len(filtered_events)} Ereignisse verbleiben.")
        return filtered_events, excluded_count

    def sync_to_target(self, target_id, events_to_sync, time_min=None, time_max=None):
        self.log(f"Lösche vorhandene Ereignisse im Zielkalender ({target_id})...")
        deleted_count = 0
        max_retries = 3
        
        # Phase 1: Lösche alle vorhandenen Events
        for attempt in range(max_retries):
            try:
                page_token = None
                events_to_delete = []
                
                # Sammle alle Event-IDs zum Löschen
                while True:
                    params = {
                        'calendarId': target_id,
                        'singleEvents': True,
                        'pageToken': page_token,
                        'maxResults': 250
                    }
                    # Füge timeMin/timeMax nur hinzu, wenn gesetzt (sonst werden alle Events abgefragt)
                    if time_min:
                        params['timeMin'] = time_min
                    if time_max:
                        params['timeMax'] = time_max

                    existing_events = self.service.events().list(**params).execute()
                    
                    items = existing_events.get('items', [])
                    events_to_delete.extend(items)
                    
                    page_token = existing_events.get('nextPageToken')
                    if not page_token:
                        break
                
                self.log(f"  -> {len(events_to_delete)} Events zum Löschen gefunden")
                
                # Lösche alle Events
                for event in events_to_delete:
                    try:
                        self.service.events().delete(calendarId=target_id, eventId=event['id']).execute()
                        deleted_count += 1
                    except HttpError as e:
                        if e.resp.status == 410:  # Already deleted
                            self.log(f"  -> Event {event['id']} wurde bereits gelöscht")
                            deleted_count += 1
                        elif e.resp.status == 404:  # Not found
                            self.log(f"  -> Event {event['id']} nicht gefunden (bereits gelöscht?)")
                        else:
                            self.log(f"  -> Fehler beim Löschen von Event {event['id']}: {e}")
                
                self.log(f"{deleted_count} Ereignisse im Zielkalender gelöscht.")
                break  # Erfolg, verlasse Retry-Schleife
                
            except HttpError as e:
                self.log(f"Fehler beim Abrufen von Zielereignissen (Versuch {attempt + 1}/{max_retries}): {e}")
                if attempt < max_retries - 1:
                    self.log(f"  -> Warte 2 Sekunden vor erneutem Versuch...")
                    time.sleep(2)
                else:
                    self.log("  -> Maximale Anzahl an Versuchen erreicht. Breche Löschvorgang ab.")
                    return 0, 0

        # Phase 2: Warte kurz, damit API-Änderungen konsistent sind
        if deleted_count > 0:
            self.log("Warte 1 Sekunde für API-Konsistenz...")
            time.sleep(1)

        # Phase 3: Erstelle neue Events
        self.log(f"Erstelle {len(events_to_sync)} neue Ereignisse...")
        created_count = 0
        failed_count = 0
        
        for event_body in events_to_sync:
            retry_count = 0
            max_event_retries = 2
            
            while retry_count < max_event_retries:
                try:
                    self.service.events().insert(calendarId=target_id, body=event_body).execute()
                    created_count += 1
                    break  # Erfolg
                except HttpError as e:
                    retry_count += 1
                    if retry_count < max_event_retries:
                        self.log(f"  -> Fehler beim Erstellen von '{event_body['summary']}', Versuch {retry_count}/{max_event_retries}")
                        time.sleep(0.5)
                    else:
                        self.log(f"  -> Fehler beim Erstellen von Event '{event_body['summary']}': {e}")
                        failed_count += 1
        
        if failed_count > 0:
            self.log(f"WARNUNG: {failed_count} Events konnten nicht erstellt werden")
        self.log(f"{created_count} Ereignisse erfolgreich erstellt.")
        return created_count, deleted_count

    def run_sync(self, config):
        """Führt den gesamten Sync-Prozess für eine gegebene Konfiguration aus."""
        self.log(f"Starte Sync für Quelle '{config.get('source_id')}'...")
        SOURCE_CALENDAR_ID = config.get('source_id')
        TARGET_CALENDAR_ID = config.get('target_id')
        REGEX_PATTERNS = config.get('regex_patterns', [])
        # Zeitzone des Benutzers holen, Standard ist Berlin
        SOURCE_TIMEZONE = config.get('source_timezone', 'Europe/Berlin') 

        if not SOURCE_CALENDAR_ID or not TARGET_CALENDAR_ID:
            self.log("Fehler: source_id oder target_id nicht konfiguriert.")
            return

        # Standard: synchronisiere ALLE Ereignisse (kein Zeitfenster)
        time_min_iso = None
        time_max_iso = None
        self.log("Zeitfenster: vollständig (keine Einschränkung). Achtung: dies kann viele Events betreffen.")

        source_events = []
        is_ics = SOURCE_CALENDAR_ID.startswith('http://') or SOURCE_CALENDAR_ID.startswith('https://')

        if is_ics:
            # Zeitzone wird übergeben; ohne Zeitfenster alle ICS-Ereignisse übernehmen
            source_events = self.fetch_ics_events(SOURCE_CALENDAR_ID, time_min_iso, time_max_iso, SOURCE_TIMEZONE)
        else:
            source_events = self.fetch_google_events(SOURCE_CALENDAR_ID, time_min_iso, time_max_iso)

        self.log(f"{len(source_events)} Ereignisse aus der Quelle abgerufen.")
        eligible_events, excluded = self.filter_events(source_events, REGEX_PATTERNS)
        created, deleted = self.sync_to_target(TARGET_CALENDAR_ID, eligible_events, time_min_iso, time_max_iso)

        self.log(f"Sync abgeschlossen: {created} erstellt, {deleted} gelöscht, {excluded} ausgeschlossen.")