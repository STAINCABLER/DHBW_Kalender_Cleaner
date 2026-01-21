# Security Policy

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| latest  | :white_check_mark: |
| < 1.0   | :x:                |

## Reporting a Vulnerability

Wir nehmen Sicherheit ernst. Wenn Sie eine Sicherheitslücke in diesem Projekt entdecken, bitten wir Sie, diese verantwortungsvoll zu melden.

### So melden Sie eine Sicherheitslücke

1. **Nicht öffentlich melden**: Bitte erstellen Sie **kein** öffentliches GitHub Issue für Sicherheitslücken.

2. **Private Meldung**: Nutzen Sie eine der folgenden Methoden:
   - **GitHub Security Advisories**: [Security Advisory erstellen](../../security/advisories/new)
   - **E-Mail**: Kontaktieren Sie uns über [thulium-labs.de/contact](https://thulium-labs.de/contact)

3. **Informationen bereitstellen**:
   - Beschreibung der Schwachstelle
   - Schritte zur Reproduktion
   - Betroffene Versionen
   - Mögliche Auswirkungen
   - Vorschläge zur Behebung (falls vorhanden)

## Bekannte Sicherheitsmaßnahmen

Dieses Projekt implementiert folgende Sicherheitsmaßnahmen:

- ✅ **CSRF-Schutz** via Flask-WTF
- ✅ **Security Headers** via Flask-Talisman (HSTS, CSP, X-Frame-Options)
- ✅ **Rate Limiting** via Flask-Limiter
- ✅ **Token-Verschlüsselung** via Fernet (AES-128-CBC + HMAC-SHA256)
- ✅ **Secure Cookies** (HttpOnly, Secure)
- ✅ **Vulnerability Scanning** via Trivy in CI/CD
- ✅ **SBOM Generation** für Supply Chain Transparenz

## Externe Abhängigkeiten

Sicherheitsupdates für Dependencies werden automatisch durch Dependabot überwacht und getestet.
