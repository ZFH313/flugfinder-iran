# ✈️ FlugFinder Iran

Automatische Suche nach den günstigsten Flügen von Deutschland nach Iran. Läuft zweimal pro Woche über GitHub Actions und benachrichtigt dich per Telegram wenn besonders günstige Flüge gefunden werden.

## Features

- 🔍 **Suche Mo + Do** – 4 Abflughäfen, Ziel-Rotation, 3 Ferienzeiten
- 🏖 **Schulferien** – Nächste Niedersachsen-Ferien, inklusive angrenzender Wochenenden
- 🔁 **Zwei Suchdienste** – SerpApi zuerst, bei Kontingent-Ende automatisch Sky Scrapper
- 💰 **Günstig-Alarm** – Telegram-Benachrichtigung bei Preisen unter Durchschnitt
- 📈 **Preis-Trend** – Verlauf als Balken in der App
- 🔮 **Vorhersage** – "Jetzt buchen" oder "Noch warten" auf Basis der Preishistorie
- 📱 **PWA-App** – Installierbar auf iPhone/Android (kein App Store nötig)

## Routen

**Abflughäfen:** Hannover (HAJ), Berlin (BER), Hamburg (HAM), Frankfurt (FRA)

**Ziele mit Rotation:**

| Lauf | Ziele | API-Anfragen |
|------|-------|--------------|
| Montag | Teheran (IKA) | 12 |
| Donnerstag | Teheran (IKA) + Mashhad (MHD) | 24 |

Mashhad wird nur einmal pro Woche mitgesucht, weil jedes zusätzliche Ziel den Verbrauch verdoppelt.

**Reisende:** 2 Erwachsene + 2 Kinder

**Aufenthalt:** mindestens 7 Nächte, in den Sommerferien 3 Wochen

## Setup

### 1. Repository klonen

```bash
git clone https://github.com/DEIN-USERNAME/flugfinder-iran.git
cd flugfinder-iran
```

### 2. Python-Umgebung einrichten

```bash
python -m venv venv
source venv/bin/activate  # Linux/Mac
# oder: venv\Scripts\activate  # Windows
pip install -r requirements.txt
```

### 3. Umgebungsvariablen konfigurieren

```bash
cp .env.example .env
# .env bearbeiten und API-Keys einfügen
```

### 4. Suchdienste einrichten

Die App nutzt eine Kette aus zwei Diensten. Es genügt wenn einer eingerichtet ist, mit beiden bist du gegen Kontingent-Ende gewappnet.

**SerpApi (primär)**

1. Registrieren: [serpapi.com/users/sign_up](https://serpapi.com/users/sign_up)
2. Key kopieren von [serpapi.com/manage-api-key](https://serpapi.com/manage-api-key)
3. In `.env` als `SERPAPI_API_KEY` eintragen

> Kostenlos sind 100 Suchen pro Monat.

**Sky Scrapper über RapidAPI (Fallback)**

1. Account anlegen: [rapidapi.com](https://rapidapi.com)
2. Sky Scrapper suchen und den kostenlosen Plan abonnieren
3. Den `x-rapidapi-key` kopieren → in `.env` als `RAPIDAPI_KEY`

> Kiwi Tequila und Amadeus Self-Service stehen nicht mehr zur Verfügung: Kiwi hat den Self-Service-Zugang 2024 geschlossen, Amadeus wurde im Juli 2026 abgeschaltet.

### 5. Telegram Bot einrichten

1. In Telegram: **@BotFather** anschreiben
2. `/newbot` senden → Bot-Name wählen
3. **Bot-Token** kopieren → in `.env` als `TELEGRAM_BOT_TOKEN`
4. Eine Nachricht an deinen neuen Bot senden
5. Öffne: `https://api.telegram.org/bot<DEIN-TOKEN>/getUpdates`
6. Die **Chat-ID** aus der Antwort kopieren → in `.env` als `TELEGRAM_CHAT_ID`

### 6. Lokal testen

```bash
# Suchplan und Budget prüfen, OHNE API-Anfragen (kostet nichts)
python main.py --dry-run --verbose

# Normale Suche (nur Teheran)
python main.py

# Suche inklusive Mashhad
python main.py --all-destinations

# Manuelle Suche mit bestimmtem Datum
python main.py --dates 2026-12-23:2027-01-06

# Ohne Telegram-Benachrichtigung
python main.py --no-notify

# Ausführliche Logs
python main.py --verbose
```

> Starte immer erst mit `--dry-run`. Damit siehst du welche Ferienzeiten und Termine gesucht würden und wie viele Anfragen das kostet, ohne Kontingent zu verbrauchen.

## GitHub Actions einrichten

### Secrets konfigurieren

In deinem GitHub Repository unter **Settings → Secrets and variables → Actions**:

| Secret | Wert | Pflicht |
|--------|------|---------|
| `SERPAPI_API_KEY` | Dein SerpApi Key | ja |
| `RAPIDAPI_KEY` | Dein RapidAPI Key für Sky Scrapper | empfohlen |
| `TELEGRAM_BOT_TOKEN` | Dein Telegram Bot Token | für Benachrichtigungen |
| `TELEGRAM_CHAT_ID` | Deine Telegram Chat ID | für Benachrichtigungen |

### GitHub Pages aktivieren

1. **Settings → Pages**
2. Source: **GitHub Actions** auswählen
3. Die PWA ist dann erreichbar unter: `https://DEIN-USERNAME.github.io/flugfinder-iran/`

### Automatische Suche

Die Suche läuft zweimal pro Woche um 8:00 Uhr deutscher Zeit:

- **Montag** – nur Teheran (12 Anfragen)
- **Donnerstag** – Teheran und Mashhad (24 Anfragen)

**Manuelle Suche starten:**
1. **Actions** Tab → "Flight Search"
2. **Run workflow** klicken
3. Optional: Datum eingeben (`2026-12-23:2027-01-06`) und/oder Mashhad dazuschalten

> Jede manuelle Suche kostet ein volles Anfrage-Paket. Bei 100 kostenlosen SerpApi-Anfragen pro Monat sind das etwa 4 zusätzliche Suchen, bevor der Fallback greift.

## PWA auf dem Handy installieren

### iPhone (Safari)
1. Öffne `https://DEIN-USERNAME.github.io/flugfinder-iran/`
2. Tippe auf das **Teilen-Symbol** (Quadrat mit Pfeil)
3. Wähle **"Zum Home-Bildschirm"**

### Android (Chrome)
1. Öffne die URL in Chrome
2. Tippe auf die **drei Punkte** → **"App installieren"**
3. Oder warte auf den automatischen Install-Banner

## Projektstruktur

```
flugfinder-iran/
├── main.py                      # Entry Point
├── src/
│   ├── config.py                # Alle Einstellungen
│   ├── models.py                # Pydantic Datenmodelle
│   ├── school_holidays.py       # Schulferien + Wochenend-Erweiterung
│   ├── flight_providers.py      # SerpApi + Sky Scrapper Provider
│   ├── flight_search.py         # Orchestrator mit Fallback + Budget
│   ├── price_analyzer.py        # Preisvergleich & Trends
│   ├── price_predictor.py       # ML Vorhersage
│   ├── combo_search.py          # Kombi-Tickets
│   ├── notifier.py              # Telegram Bot
│   └── main.py                  # Pipeline-Orchestrierung
├── frontend/
│   ├── index.html               # PWA Startseite
│   ├── style.css                # Styling
│   ├── app.js                   # Frontend-Logik
│   ├── sw.js                    # Service Worker (Offline)
│   ├── manifest.json            # PWA Manifest
│   ├── data.json                # Aktuelle Suchergebnisse
│   └── icons/                   # App-Icons
├── data/
│   ├── holidays_niedersachsen.json
│   └── price_history.json
├── results/
│   └── latest_results.json
├── .github/workflows/
│   ├── daily_search.yml         # Suche Mo + Do
│   └── deploy_pages.yml         # GitHub Pages Deploy
├── requirements.txt
├── .env.example
└── .gitignore
```

## Konfiguration anpassen

Alle Einstellungen in `src/config.py`:

| Parameter | Standard | Beschreibung |
|-----------|----------|--------------|
| `primary_destinations` | `["IKA"]` | Ziele bei jedem Lauf |
| `secondary_destinations` | `["MHD"]` | Ziele nur mit `--all-destinations` |
| `max_api_calls_per_run` | 24 | Harte Obergrenze pro Lauf |
| `max_holidays_per_run` | 3 | Wie viele Ferienzeiten geprüft werden |
| `max_date_pairs_per_holiday` | 1 | Termine pro Ferienzeit |
| `max_stops` | 1 | Maximale Zwischenstopps |
| `departure_time_preference` | "no_night" | Keine Nachtflüge |
| `price_limit_alert` | 1500 | Preislimit für Alarm (€) |
| `flexibility_days` | 0 | ±Tage Flexibilität um den Termin |
| `enable_combo_tickets` | false | Kostet ~32 Anfragen, daher aus |
| `enable_price_prediction` | true | Vorhersage aktiv |

### Verbrauch selbst nachrechnen

```
Anfragen pro Lauf = Abflughäfen × Ziele × Gepäckvarianten × Termine
```

Beispiel Donnerstag: 4 × 2 × 1 × 3 = 24. Die Route-Zahl ist der größte Hebel, weil sie jeden Termin multipliziert.

## Hinweise

- Preise ändern sich ständig – keine Buchungsgarantie
- Der Preisverlauf wird aussagekräftiger mit mehr Datenpunkten (nach 2+ Wochen)
- Icons müssen noch als PNG erstellt werden (siehe `frontend/generate-icons.html`)
- Das Sky-Scrapper-Parsing ist nach Dokumentation gebaut, aber noch nicht mit einem echten Key gegengetestet
- `frontend/data.json` enthält aktuell Demo-Daten, keine echten Preise

## Icons generieren

Erstelle ein quadratisches Logo (z.B. 512×512px) und generiere alle Größen:
- Nutze [realfavicongenerator.net](https://realfavicongenerator.net/) 
- Oder erstelle manuell: 72, 96, 128, 144, 152, 192, 384, 512px

## Lizenz

Privates Projekt – nicht zur Weiterverbreitung bestimmt.
