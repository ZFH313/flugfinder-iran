# FlugFinder Iran – Projektplan & Roadmap

## Projektziel

Automatische Flugsuche für eine 4-köpfige Familie (2 Erwachsene + 2 Kinder) von Deutschland nach Iran. Günstige Flüge finden, benachrichtigen, und einfach buchbar machen.

## Aktueller Stand (v1.1)

### ✅ Fertig
- Pipeline: Schulferien → Suchplan → Flugsuche → Preisanalyse → Telegram → Frontend-Export
- **Provider-Kette mit Fallback**: SerpApi zuerst, bei Kontingent-Ende automatisch Sky Scrapper
- **Hartes Anfrage-Budget** pro Lauf, damit ein Durchlauf nie das Monatskontingent sprengt
- Retry mit Exponential Backoff auf 429 und Timeout
- PWA Frontend: Ferien-Karten, Filter, Sortierung, Preisverlauf-Balken, Buchungslinks
- GitHub Actions: wöchentliche Suche + manueller Start + GitHub Pages Deploy
- Wochenend-Erweiterung: prüft ob ein Wochenende vor/nach den Ferien anschließt
- Mindestaufenthalt 7 Tage (Sommerferien: 3 Wochen)
- Dry-Run Modus (`--dry-run`) zeigt Suchplan und Budget ohne API-Aufrufe
- Preis-Vorhersage (braucht min. 14 Tage Datenhistorie)
- Kombi-Tickets (unterschiedliche Hin-/Rückflughäfen), nur bei verbleibendem Budget

### 🔧 Bekannte Probleme / offene Punkte
- **Sky-Scrapper-Parsing ungetestet**: nach der Doku umgesetzt, muss beim ersten Lauf mit echtem RapidAPI-Key verifiziert werden. RapidAPI-Anbieter ändern Feldnamen gelegentlich.
- iPhone-Icon braucht PNG (SVG wird nicht als App-Icon angezeigt) → `frontend/generate-icons.html` nutzen
- Google-Flights-Fallback-URL ist fragil (Parameterformat kann sich ändern)
- Keine automatisierten Tests für Provider-Kette, Suchplan und Wochenend-Erweiterung
- `frontend/data.json` enthält aktuell Demo-Daten, keine echten Preise

## Suchdienste (Provider)

### Warum diese Kette
| Dienst | Status | Free-Tier | Rolle |
|--------|--------|-----------|-------|
| SerpApi (Google Flights) | ✅ nutzbar | 100 Suchen/Monat | Primär |
| Sky Scrapper (RapidAPI) | ✅ nutzbar, nur RapidAPI-Account nötig | vorhanden | Fallback |
| Kiwi Tequila | ❌ Self-Service 2024 geschlossen; Partnerkanal verlangt 50.000 MAU | – | ausgeschlossen |
| Amadeus Self-Service | ❌ am 17.07.2026 abgeschaltet, Keys deaktiviert | – | ausgeschlossen |
| Skyscanner offiziell | ❌ Business-Review, Wochen Vorlauf | – | ausgeschlossen |

### Fallback-Semantik (wichtig)
Ein **erfolgreicher** Aufruf gilt als erledigt, auch wenn er null Flüge findet. Nur bei `QuotaExceededError` oder `ProviderError` wird auf den nächsten Provider umgeschaltet – und zwar dauerhaft für den restlichen Lauf. Andernfalls würde jede leere Route das Budget mehrfach belasten.

### Umschaltauslöser
- SerpApi: HTTP 429 nach allen Retries, oder Fehlertext mit „run out“, „exceeded“, „plan limit“
- Sky Scrapper: HTTP 429, oder 403 mit „quota“/„not subscribed“
- Ungültiger Key (401): Provider wird deaktiviert, nächster übernimmt

## API-Budget-Planung

Ein Datumspaar kostet `num_routes × luggage_variants` Anfragen.
Bei 4 Abflughäfen × 2 Zielen × 1 Gepäckvariante = **8 Anfragen pro Datumspaar**.

### Ziel-Rotation
Um Anfragen zu sparen werden die Ziele rotiert:

| Lauf | Ziele | Routen | Termine | Anfragen |
|---|---|---|---|---|
| Montag | Teheran | 4 | 3 | 12 |
| Donnerstag | Teheran + Mashhad | 8 | 3 | 24 |

Gesteuert über das CLI-Flag `--all-destinations`. Der Workflow entscheidet anhand von `github.event.schedule`, welcher Lauf welches Set nutzt.

| Einstellung | Default | Wirkung |
|---|---|---|
| `primary_destinations` | `["IKA"]` | bei jedem Lauf |
| `secondary_destinations` | `["MHD"]` | nur mit `--all-destinations` |
| `max_api_calls_per_run` | 24 | deckt den größeren Donnerstags-Lauf ab |
| `max_date_pairs_per_holiday` | 1 | jede Ferienzeit bekommt genau einen Termin |
| `max_holidays_per_run` | 3 | nur Perioden mit buchbaren Terminen zählen |
| `enable_combo_tickets` | False | kostet allein ~32 Anfragen, daher bewusst aus |
| Cron | Mo + Do | ~8,7 Läufe/Monat |

**Monatsrechnung:** (12 + 24) × 4,35 Wochen ≈ **156 Anfragen/Monat**. SerpApi deckt die ersten ~100 ab, den Rest übernimmt Sky Scrapper.

### Spar-Hebel (absteigende Wirkung)
| Maßnahme | pro Monat |
|---|---|
| Aktuell (Mo Teheran + Do Mashhad) | ~156 |
| Nur Donnerstag laufen lassen | ~104 |
| Mashhad nur 1× pro Monat statt wöchentlich | ~76 |
| Zwei Abflughäfen weniger | ~78 |
| `max_holidays_per_run = 2` | ~104 |

**Achtung:** Jede manuelle Suche aus der PWA kostet einen vollen Lauf.

**Kombi-Tickets:** Beim Aktivieren `max_api_calls_per_run` auf mindestens 64 setzen, sonst bricht die Kombi-Suche mitten in der Auswertung ab und liefert unvollständige Vergleiche.

### Ferien-Auswahl beachtet die Enden
`_collect_usable_holidays()` berechnet erst die Termine und wählt **dann** aus. Eine bereits laufende Ferienzeit, deren Restzeit für den Mindestaufenthalt nicht mehr reicht, liefert keine Termine und belegt daher keinen der 3 Slots. Ohne diese Reihenfolge würden effektiv nur 2 statt 3 Ferienzeiten durchsucht.

## Roadmap

### Phase 1: Stabilität — teilweise erledigt
| # | Feature | Status | Datei |
|---|---------|--------|-------|
| 1 | Retry-Logik mit Backoff (429/Timeout) | ✅ fertig | `src/flight_providers.py` |
| 2 | Provider-Fallback bei Kontingent-Ende | ✅ fertig | `src/flight_search.py` |
| 3 | Hartes Anfrage-Budget | ✅ fertig | `src/config.py`, `src/main.py` |
| 4 | Sky-Scrapper-Parsing mit echtem Key verifizieren | ⏳ offen | `src/flight_providers.py` |
| 5 | Tages-Cache: gleiche Route nicht 2× am Tag | ⏳ offen | `src/flight_search.py` |
| 6 | Kinderalter via .env konfigurierbar | ⏳ offen | `src/config.py` |
| 7 | PNG-Icons generieren und committen | ⏳ offen | `frontend/icons/` |
| 8 | Telegram-Meldung wenn Workflow fehlschlägt | ⏳ offen | `src/notifier.py` |

### Phase 2: Bessere UX — teilweise erledigt
| # | Feature | Status | Datei |
|---|---------|--------|-------|
| 9 | Sortierung (Preis / Dauer / Datum) | ✅ fertig | `frontend/app.js` |
| 10 | Preis-Verlauf als CSS-Balken | ✅ fertig | `frontend/app.js`, `style.css` |
| 11 | Provider-Quelle am Flug anzeigen | ✅ fertig | `frontend/app.js` |
| 12 | Flugdauer anzeigen | ✅ fertig | `frontend/app.js` |
| 13 | Onboarding-Card für neue Nutzer | ⏳ offen | `frontend/index.html` |
| 14 | Manuelle Suche: nur das angefragte Datum prüfen (Budget schonen) | ⏳ offen | `src/main.py` |

### Phase 3: Multi-User
| # | Feature | Aufwand | Datei |
|---|---------|---------|-------|
| 15 | Bundesland wählbar (nicht nur Niedersachsen) | 2h | `src/school_holidays.py`, Frontend |
| 16 | Passagiere im Frontend einstellbar | 2h | Frontend + Config |
| 17 | Eigenen Preis-Alarm setzen | 1h | Frontend + Notifier |
| 18 | Telegram-Bot als Eingangskanal (`/suche Datum`) | 4h | neues Modul |
| 19 | Mehrere Familien mit eigenen Einstellungen | 8h | Backend-Redesign |

## Technische Entscheidungen

| Entscheidung | Begründung |
|--------------|-----------|
| Provider-Kette statt Einzeldienst | Kein Ausfall bei Kontingent-Ende; freie Tiers sind alle klein |
| Ziel-Rotation statt beide Ziele immer | Mashhad wird seltener gebraucht; halbiert die Anfragen an 6 von 7 Tagen |
| Termine berechnen vor Ferien-Auswahl | Sonst belegen abgelaufene Ferien einen Slot und liefern nichts |
| Provider liefern geparste `FlightOffer` | Aufrufer bleiben providerunabhängig, kein Raw-Dict-Handling |
| Hartes Call-Budget statt „bis es knallt“ | Free-Tier war zweimal in einem Lauf verbraucht |
| Wöchentlich statt täglich | Ferienpreise Monate im Voraus ändern sich nicht täglich |
| GitHub Actions statt eigener Server | Kostenlos, wartungsfrei |
| PWA statt native App | Kein App Store nötig, läuft auf iOS + Android |
| Keine Datenbank | JSON-Dateien reichen für eine Familie |
| Nur MIT Gepäck suchen | Halbiert die Anfragen; Iran-Flug ohne Aufgabegepäck unrealistisch |
| Suche serverseitig, nicht im Frontend | API-Keys dürfen nicht im Browser landen |

## Architektur: wie die App funktioniert

Die PWA ist ein **Anzeigefenster**, kein Suchmotor:

1. GitHub Actions führt `python main.py` aus (Keys aus den Repo-Secrets)
2. Ergebnisse landen in `frontend/data.json` und werden committed
3. GitHub Pages deployt neu, die App lädt die aktualisierte `data.json`
4. Telegram erhält Zusammenfassung + Günstig-Alarme

Die manuelle Suche in der App startet über die GitHub-API den Workflow (daher der GitHub-Token). Ergebnis kommt zuerst per Telegram, die App zeigt es nach dem Pages-Deploy – insgesamt rund 5–10 Minuten Verzögerung.

## Dateistruktur-Referenz

```
src/config.py           → Alle Einstellungen (Airports, Passagiere, Budget, Provider-Reihenfolge)
src/models.py           → Pydantic-Modelle (FlightOffer mit source + booking_link)
src/school_holidays.py  → Ferien laden, Wochenend-Erweiterung, Datumsberechnung
src/flight_providers.py → Provider-Implementierungen (SerpApi, Sky Scrapper) + build_providers()
src/flight_search.py    → Orchestrator: FlightSearchClient mit Fallback + Budget, search_all_routes()
src/price_analyzer.py   → Preis-Historie, Trends, "Günstig"-Markierung
src/price_predictor.py  → Vorhersage (braucht min. 14 Tage Daten)
src/combo_search.py     → Kombi-Tickets (anderer Rückflughafen), budgetbewusst
src/notifier.py         → Telegram-Nachrichten
src/main.py             → Pipeline, Ferien-Auswahl (_collect_usable_holidays),
                          Suchplan (_build_search_plan), Frontend-Export, Dry-Run
frontend/app.js         → PWA-Logik (Ferien-Karten, Filter, Sortierung, Buchungslinks)
frontend/style.css      → Styling
frontend/data.json      → Aktuelle Suchergebnisse (generiert)
data/airport_ids.json   → Cache der Sky-Scrapper Flughafen-IDs (skyId/entityId)
data/price_history.json → Preisverlauf für Analyse und Vorhersage
```

## Wichtige Schnittstellen

```python
# Orchestrator aufbauen
client = FlightSearchClient.from_config(config)

# Einzelne Suche (mit automatischem Fallback)
flights: list[FlightOffer] = client.search_flights(
    origin="HAJ", destination="IKA",
    outbound_date=date(...), return_date=date(...),
    flight_config=config.flight,
    luggage_type=LuggageType.WITH_LUGGAGE,
)

# Budget prüfen bevor teure Zusatzsuchen starten
if client.has_capacity():
    ...

# Nutzungsbericht für Logs
for line in client.stats_summary():
    logger.info(line)
```

## Konventionen
- Deutsche Docstrings und Log-Meldungen, englische Bezeichner im Code
- `logging` statt `print`
- Pydantic für alle validierten Daten
- Fehler pro Route isoliert: eine fehlgeschlagene Route bricht den Lauf nicht ab
- Vor teuren Suchen immer `client.has_capacity()` prüfen
- Neue Provider erben von `FlightProvider` und werden in `build_providers()` registriert
