# ✈️ FlugFinder Iran

Automatische Suche nach den günstigsten Flügen von Deutschland nach Iran. Läuft täglich über GitHub Actions und benachrichtigt dich per Telegram wenn besonders günstige Flüge gefunden werden.

## Features

- 🔍 **Tägliche Suche** – 4 Abflughäfen × 2 Zielflughäfen × alle Datumskombinationen
- 🏖 **Schulferien** – Automatisch die nächsten Niedersachsen-Ferien mit ±2 Tagen Flexibilität
- 💰 **Günstig-Alarm** – Telegram-Benachrichtigung bei Preisen unter Durchschnitt
- 📈 **Preis-Trend** – Wöchentlicher Verlauf als Graph
- 🔮 **Vorhersage** – "Jetzt buchen" oder "Noch warten" basierend auf ML
- 🔀 **Kombi-Tickets** – Hin ab Hamburg, Rück nach Frankfurt wenn günstiger
- 📱 **PWA-App** – Installierbar auf iPhone/Android (kein App Store nötig)

## Routen

| Abflug | Ziel |
|--------|------|
| Hannover (HAJ) | Teheran IKA |
| Berlin (BER) | Mashhad (MHD) |
| Hamburg (HAM) | |
| Frankfurt (FRA) | |

**Reisende:** 2 Erwachsene + 2 Kinder

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

### 4. Amadeus API Key holen

1. Gehe zu [developers.amadeus.com/register](https://developers.amadeus.com/register)
2. Account erstellen (kostenlos)
3. Unter "My Self-Service Workspace" → "Create new app"
4. **API Key** und **API Secret** kopieren → in `.env` eintragen

> Der Self-Service (Test) Tier ist kostenlos und reicht für tägliche Suchen.

### 5. Telegram Bot einrichten

1. In Telegram: **@BotFather** anschreiben
2. `/newbot` senden → Bot-Name wählen
3. **Bot-Token** kopieren → in `.env` als `TELEGRAM_BOT_TOKEN`
4. Eine Nachricht an deinen neuen Bot senden
5. Öffne: `https://api.telegram.org/bot<DEIN-TOKEN>/getUpdates`
6. Die **Chat-ID** aus der Antwort kopieren → in `.env` als `TELEGRAM_CHAT_ID`

### 6. Lokal testen

```bash
# Automatische Suche (nächste Ferien)
python main.py

# Manuelle Suche mit bestimmtem Datum
python main.py --dates 2026-12-23:2027-01-06

# Ohne Telegram-Benachrichtigung
python main.py --no-notify

# Ausführliche Logs
python main.py --verbose
```

## GitHub Actions einrichten

### Secrets konfigurieren

In deinem GitHub Repository unter **Settings → Secrets and variables → Actions**:

| Secret | Wert |
|--------|------|
| `AMADEUS_API_KEY` | Dein Amadeus API Key |
| `AMADEUS_API_SECRET` | Dein Amadeus API Secret |
| `TELEGRAM_BOT_TOKEN` | Dein Telegram Bot Token |
| `TELEGRAM_CHAT_ID` | Deine Telegram Chat ID |

### GitHub Pages aktivieren

1. **Settings → Pages**
2. Source: **GitHub Actions** auswählen
3. Die PWA ist dann erreichbar unter: `https://DEIN-USERNAME.github.io/flugfinder-iran/`

### Tägliche Suche

Die Suche läuft automatisch jeden Tag um 8:00 Uhr (deutscher Zeit).

**Manuelle Suche starten:**
1. **Actions** Tab → "Daily Flight Search"
2. **Run workflow** klicken
3. Optional: Datum eingeben (Format: `2026-12-23:2027-01-06`)

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
│   ├── school_holidays.py       # Schulferien + Flexibilität
│   ├── flight_search.py         # Amadeus API Client
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
│   ├── daily_search.yml         # Tägliche Suche
│   └── deploy_pages.yml         # GitHub Pages Deploy
├── requirements.txt
├── .env.example
└── .gitignore
```

## Konfiguration anpassen

Alle Einstellungen in `src/config.py`:

| Parameter | Standard | Beschreibung |
|-----------|----------|--------------|
| `max_stops` | 1 | Maximale Zwischenstopps |
| `departure_time_preference` | "no_night" | Keine Nachtflüge |
| `prefer_weekend_departure` | true | Fr/Sa Hinflug bevorzugen |
| `price_limit_alert` | 1500 | Preislimit für Alarm (€) |
| `flexibility_days` | 2 | ±Tage Flexibilität |
| `enable_combo_tickets` | true | Kombi-Tickets suchen |
| `enable_price_prediction` | true | ML Vorhersage aktiv |

## Hinweise

- Die Amadeus Test-API liefert manchmal keine Ergebnisse für bestimmte Routen
- Preise ändern sich ständig – keine Buchungsgarantie
- Der Preisverlauf wird besser mit mehr Datenpunkten (nach 2+ Wochen)
- Icons müssen noch als PNG-Dateien erstellt werden (siehe `frontend/icons/`)

## Icons generieren

Erstelle ein quadratisches Logo (z.B. 512×512px) und generiere alle Größen:
- Nutze [realfavicongenerator.net](https://realfavicongenerator.net/) 
- Oder erstelle manuell: 72, 96, 128, 144, 152, 192, 384, 512px

## Lizenz

Privates Projekt – nicht zur Weiterverbreitung bestimmt.
