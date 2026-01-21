# Datenschutzerklärung

*Informationen zur Verarbeitung personenbezogener Daten gemäß Art. 13 und 14 DSGVO – Stand: Januar 2026*

## 1. Verantwortlicher

Tobias Maimone  
c/o flexdienst – #20124  
Kurt-Schumacher-Straße 76  
67663 Kaiserslautern  
Deutschland

Kontakt: [thulium-labs.de/contact](https://thulium-labs.de/contact)

## 2. Übersicht der Verarbeitungen

Diese Datenschutzerklärung informiert Sie über Art, Umfang und Zweck der Verarbeitung personenbezogener Daten innerhalb dieser Anwendung. Personenbezogene Daten sind alle Daten, die auf Sie persönlich beziehbar sind, z.B. Name, E-Mail-Adresse, IP-Adresse.

## 3. Google OAuth 2.0 Authentifizierung

Wenn Sie sich über "Mit Google anmelden" authentifizieren, erhalten wir von Google folgende Daten:

- Ihre eindeutige Google User-ID (Sub)
- Ihre E-Mail-Adresse

Wir speichern Ihre User-ID und Ihre E-Mail-Adresse in einer Konfigurationsdatei auf dem Server, um Ihr Konto zu verwalten.

## 4. Google Kalender Daten

Die Anwendung fordert die Berechtigung an, auf Ihre Google Kalender zuzugreifen. Diese Berechtigung wird verwendet, um:

- Ereignisse aus Ihrem Quellkalender zu lesen.
- Ereignisse in Ihrem Zielkalender zu löschen.
- Gefilterte Ereignisse in Ihrem Zielkalender zu erstellen.

Um den Dienst im Hintergrund (per Cronjob) ausführen zu können, speichern wir einen von Google bereitgestellten **Refresh-Token**. Dieser Token wird verschlüsselt (Fernet/AES) in Ihrer Benutzer-Konfigurationsdatei auf dem Server gespeichert.

## 5. Konfigurationsdaten

Wir speichern die von Ihnen im Dashboard eingegebenen Daten (Quell-ID, Ziel-ID, RegEx-Filter, Zeitzone), um den Synchronisierungsdienst auszuführen.

## 6. Log-Dateien

Jede Synchronisierung (manuell oder automatisch) wird in einer benutzerspezifischen Log-Datei auf dem Server protokolliert. Diese Logs sind nur für den jeweiligen Benutzer im Dashboard sichtbar und werden beim Löschen des Kontos ebenfalls entfernt.

## 7. Datensicherheit

Kritische Authentifizierungsdaten (Refresh-Token) werden vor der Speicherung mit einem symmetrischen Schlüssel (Fernet/AES-128-CBC + HMAC-SHA256) verschlüsselt. Die Verbindung zur Anwendung erfolgt ausschließlich über HTTPS.

## 8. Hosting

Diese Anwendung wird auf einem selbst betriebenen Server gehostet. Es werden keine Daten an Dritte weitergegeben, außer an Google im Rahmen der Kalender-Synchronisation.

## 9. Ihre Rechte

Sie haben gegenüber dem Verantwortlichen folgende Rechte bezüglich Ihrer personenbezogenen Daten:

- Recht auf Auskunft (Art. 15 DSGVO)
- Recht auf Berichtigung (Art. 16 DSGVO)
- Recht auf Löschung (Art. 17 DSGVO)
- Recht auf Einschränkung der Verarbeitung (Art. 18 DSGVO)
- Recht auf Datenübertragbarkeit (Art. 20 DSGVO)
- Recht auf Widerspruch (Art. 21 DSGVO)

Sie können Ihr Konto und alle zugehörigen Daten jederzeit über die Funktion "Konto dauerhaft löschen" im Dashboard selbst entfernen.

## 10. Beschwerderecht

Sie haben das Recht, sich bei einer Datenschutz-Aufsichtsbehörde über die Verarbeitung Ihrer personenbezogenen Daten zu beschweren.

Eine Liste der Datenschutzbeauftragten: [bfdi.bund.de](https://www.bfdi.bund.de/DE/Service/Anschriften/Laender/Laender-node.html)
