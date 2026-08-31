"""
Konfiguration für FlugFinder Iran.
Alle Einstellungen zentral an einem Ort.
"""

import os
import logging
from dataclasses import dataclass, field
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

#: Standard-Reihenfolge der Suchdienste
DEFAULT_PROVIDER_ORDER = ["serpapi", "skyscrapper"]

#: Standard-Host der Sky-Scrapper-API auf RapidAPI
DEFAULT_RAPIDAPI_HOST = "sky-scrapper.p.rapidapi.com"


def _env_or_default(name: str, default: str) -> str:
    """
    Liest eine Umgebungsvariable und behandelt Leerstring wie "nicht gesetzt".

    Nötig weil os.getenv(name, default) den Standardwert nur zurückgibt wenn
    die Variable fehlt. GitHub Actions setzt nicht definierte Variablen aber
    als Leerstring – damit wäre der Standardwert ausgehebelt.
    """
    return os.getenv(name, "").strip() or default


def _provider_order_from_env() -> list[str]:
    """
    Liest die Provider-Reihenfolge aus PROVIDER_ORDER (kommagetrennt).

    Nützlich wenn ein Dienst bekanntlich ausgefallen ist: dann lässt sich
    die Kette ohne Code-Änderung umstellen, etwa über eine GitHub-Variable.
    """
    raw = os.getenv("PROVIDER_ORDER", "").strip()
    if not raw:
        return list(DEFAULT_PROVIDER_ORDER)
    return [name.strip() for name in raw.split(",") if name.strip()]


@dataclass
class FlightConfig:
    """Flug-Suchkonfiguration."""

    # Abflughäfen (IATA-Codes)
    departure_airports: list[str] = field(
        default_factory=lambda: ["HAJ", "BER", "HAM", "FRA"]
    )

    # --- Zielflughäfen (IATA-Codes) ---
    # Ziele werden rotiert um API-Anfragen zu sparen:
    #   primär   → bei JEDEM Lauf gesucht
    #   sekundär → nur bei Läufen mit --all-destinations (1× pro Woche)
    primary_destinations: list[str] = field(
        default_factory=lambda: ["IKA"]  # Teheran
    )
    secondary_destinations: list[str] = field(
        default_factory=lambda: ["MHD"]  # Mashhad
    )

    # Wird zur Laufzeit gesetzt (CLI-Flag --all-destinations)
    include_secondary_destinations: bool = False

    # Reisende
    adults: int = 2
    children_ages: list[int] = field(default_factory=lambda: [5, 8])

    # Gepäck-Optionen (nur MIT Gepäck suchen um API-Calls zu sparen)
    search_with_luggage: bool = True
    search_without_luggage: bool = False

    # Flexibilität in Tagen (±) — 0 = nur exaktes Feriendatum
    flexibility_days: int = 0

    # Zwischenstopp-Filter
    max_stops: int = 1  # 0 = nur direkt, 1 = max 1 Stopp, 2 = max 2 Stopps
    min_connection_time_hours: float = 2.0  # Mindest-Umsteigezeit in Stunden

    # Abflugzeit-Präferenz
    # Optionen: "morning", "afternoon", "evening", "no_night", "any"
    departure_time_preference: str = "no_night"

    # Preislimit für Alarm (Gesamtpreis alle Personen in €)
    price_limit_alert: int = 1500

    # Preis-Bewertung
    cheap_threshold_percent: float = 20.0  # "Sehr günstig" wenn X% unter Durchschnitt

    # Kombi-Tickets
    # Standardmäßig AUS: die Suche kostet allein ca. 32 API-Anfragen
    # (8 Routen für Referenzpreise + 24 Kombinationen) und würde das
    # Budget für die Hauptsuche auffressen. Nur bewusst einschalten und
    # dann max_api_calls_per_run entsprechend erhöhen.
    enable_combo_tickets: bool = False
    combo_min_savings: int = 100  # Nur anzeigen wenn >X€ günstiger

    # Preis-Vorhersage
    enable_price_prediction: bool = True
    prediction_min_data_days: int = 14  # Mindestens X Tage Daten für Vorhersage

    # --- Provider-Kette ---
    # Reihenfolge in der die Suchdienste probiert werden. Ist ein Dienst
    # nicht konfiguriert oder sein Kontingent erschöpft, übernimmt der nächste.
    # Gültige Werte: "serpapi", "skyscrapper"
    #
    # Per Umgebungsvariable überschreibbar, um einen bekannt ausgefallenen
    # Dienst zu überspringen ohne den Code zu ändern:
    #   PROVIDER_ORDER=skyscrapper              → nur Sky Scrapper
    #   PROVIDER_ORDER=skyscrapper,serpapi      → Reihenfolge tauschen
    provider_order: list[str] = field(default_factory=lambda: _provider_order_from_env())

    # --- API-Budget (SerpApi Free-Tier: 100 Suchen/Monat) ---
    #
    # Kosten einer Suche:
    #   1 Anfrage = 1 Abflughafen → 1 Ziel, 1 Datumspaar, 1 Gepäckvariante
    #   Routen pro Datumspaar = Abflughäfen × Ziele × Gepäckvarianten
    #
    # Aktuelle Belegung mit Ziel-Rotation und 3 Ferienzeiten:
    #   Teheran-Lauf:  4 Abflughäfen × 1 Ziel × 3 Datumspaare = 12 Anfragen
    #   Mashhad-Lauf:  4 Abflughäfen × 2 Ziele × 3 Datumspaare = 24 Anfragen
    #
    # Das Limit muss den größeren Lauf abdecken → 24.
    # Der Teheran-Lauf bleibt automatisch bei 12, weil nur 3 Datumspaare
    # existieren (3 Ferienzeiten × 1 Paar).
    #
    # Größter Sparhebel ist die Route-Zahl, weil sie jedes Datumspaar
    # multipliziert. Ein Ziel weniger halbiert den Verbrauch sofort.
    max_api_calls_per_run: int = 24

    # Datumspaare pro Ferienperiode. Bei 1 bekommt jede Ferienzeit genau
    # einen Termin – so deckt das Budget alle Ferien ab, statt dass eine
    # einzelne Periode mehrere Varianten belegt.
    max_date_pairs_per_holiday: int = 1

    # Notbremse: Liefern die ersten N erfolgreichen Suchen zusammen keinen
    # einzigen Flug, bricht der Lauf ab. Schützt davor dass ein struktureller
    # Fehler (falsche Parameter, geändertes Antwortformat) das ganze
    # Monatskontingent für leere Ergebnisse verbrennt.
    # 0 schaltet die Notbremse ab.
    abort_after_empty_searches: int = 3

    # Wie viele Ferienperioden maximal durchsuchen.
    # Gezählt werden nur Perioden die tatsächlich buchbare Termine liefern –
    # bereits laufende Ferien mit zu wenig Restzeit fallen vorher raus.
    max_holidays_per_run: int = 3

    @property
    def destination_airports(self) -> list[str]:
        """
        Die in diesem Lauf zu durchsuchenden Ziele.

        Ohne --all-destinations nur die primären Ziele (Teheran),
        mit Flag zusätzlich die sekundären (Mashhad).
        """
        if self.include_secondary_destinations:
            return [*self.primary_destinations, *self.secondary_destinations]
        return list(self.primary_destinations)

    @property
    def num_routes(self) -> int:
        """Anzahl Routen (Abflughäfen × Zielflughäfen)."""
        return len(self.departure_airports) * len(self.destination_airports)

    @property
    def luggage_variants(self) -> int:
        """Anzahl Gepäck-Varianten die gesucht werden."""
        return int(self.search_with_luggage) + int(self.search_without_luggage)

    @property
    def max_date_pairs_total(self) -> int:
        """
        Wie viele Datumspaare passen ins API-Budget?
        Ein Datumspaar kostet num_routes × luggage_variants Anfragen.
        """
        cost_per_pair = self.num_routes * max(self.luggage_variants, 1)
        if cost_per_pair == 0:
            return 0
        return max(1, self.max_api_calls_per_run // cost_per_pair)

    @property
    def num_children(self) -> int:
        """Anzahl der Kinder."""
        return len(self.children_ages)

    @property
    def total_passengers(self) -> int:
        """Gesamtanzahl Reisende."""
        return self.adults + self.num_children

    def get_departure_time_range(self) -> tuple[str, str] | None:
        """
        Gibt den erlaubten Abflugzeit-Bereich zurück.
        Returns None wenn 'any' (keine Einschränkung).
        """
        ranges = {
            "morning": ("06:00", "12:00"),
            "afternoon": ("12:00", "18:00"),
            "evening": ("18:00", "22:00"),
            "no_night": ("06:00", "22:00"),
            "any": None,
        }
        return ranges.get(self.departure_time_preference)


@dataclass
class SerpApiConfig:
    """
    SerpApi Konfiguration (Google Flights).

    Achtung Free-Tier: 100 Suchen pro Monat. Das Budget wird über
    FlightConfig.max_api_calls_per_run hart begrenzt.
    """

    api_key: str = field(default_factory=lambda: os.getenv("SERPAPI_API_KEY", ""))

    def is_configured(self) -> bool:
        """Prüft ob API-Key gesetzt ist."""
        return bool(self.api_key)


@dataclass
class RapidApiConfig:
    """
    RapidAPI Konfiguration (Sky Scrapper – Skyscanner-Daten).

    Dient als Fallback wenn das SerpApi-Kontingent erschöpft ist.
    Registrierung: https://rapidapi.com → Sky Scrapper abonnieren (Free-Tier).
    """

    api_key: str = field(default_factory=lambda: os.getenv("RAPIDAPI_KEY", "").strip())
    host: str = field(
        default_factory=lambda: _env_or_default("RAPIDAPI_HOST", DEFAULT_RAPIDAPI_HOST)
    )

    def is_configured(self) -> bool:
        """Prüft ob Key und Host gesetzt sind."""
        return bool(self.api_key and self.host)


@dataclass
class TelegramConfig:
    """Telegram Bot Konfiguration."""

    bot_token: str = field(default_factory=lambda: os.getenv("TELEGRAM_BOT_TOKEN", ""))
    chat_id: str = field(default_factory=lambda: os.getenv("TELEGRAM_CHAT_ID", ""))

    def is_configured(self) -> bool:
        """Prüft ob Telegram-Credentials gesetzt sind."""
        return bool(self.bot_token and self.chat_id)


@dataclass
class PathConfig:
    """Pfad-Konfiguration für Daten und Ergebnisse."""

    # Basis-Verzeichnis (Projekt-Root)
    base_dir: str = field(
        default_factory=lambda: os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    )

    @property
    def data_dir(self) -> str:
        return os.path.join(self.base_dir, "data")

    @property
    def results_dir(self) -> str:
        return os.path.join(self.base_dir, "results")

    @property
    def price_history_file(self) -> str:
        return os.path.join(self.data_dir, "price_history.json")

    @property
    def holidays_file(self) -> str:
        return os.path.join(self.data_dir, "holidays_niedersachsen.json")

    @property
    def airport_ids_file(self) -> str:
        """Cache für Sky-Scrapper Flughafen-IDs (skyId/entityId)."""
        return os.path.join(self.data_dir, "airport_ids.json")

    @property
    def latest_results_file(self) -> str:
        return os.path.join(self.results_dir, "latest_results.json")

    @property
    def frontend_data_file(self) -> str:
        """JSON-Datei die das Frontend liest (für GitHub Pages)."""
        return os.path.join(self.base_dir, "frontend", "data.json")


@dataclass
class AppConfig:
    """Haupt-Konfiguration die alle Teil-Configs zusammenfasst."""

    flight: FlightConfig = field(default_factory=FlightConfig)
    serpapi: SerpApiConfig = field(default_factory=SerpApiConfig)
    rapidapi: RapidApiConfig = field(default_factory=RapidApiConfig)
    telegram: TelegramConfig = field(default_factory=TelegramConfig)
    paths: PathConfig = field(default_factory=PathConfig)

    @property
    def configured_providers(self) -> list[str]:
        """
        Gibt die konfigurierten Provider in der gewünschten Reihenfolge zurück.
        Nicht konfigurierte Dienste werden übersprungen.
        """
        available = {
            "serpapi": self.serpapi.is_configured(),
            "skyscrapper": self.rapidapi.is_configured(),
        }
        return [name for name in self.flight.provider_order if available.get(name)]

    def has_any_provider(self) -> bool:
        """Ist mindestens ein Suchdienst nutzbar?"""
        return bool(self.configured_providers)

    def validate(self) -> list[str]:
        """
        Validiert die Konfiguration.
        Gibt eine Liste von Fehlermeldungen zurück (leer = alles OK).
        """
        errors = []

        if not self.has_any_provider():
            errors.append(
                "Kein Suchdienst konfiguriert – setze SERPAPI_API_KEY und/oder RAPIDAPI_KEY"
            )

        unknown = [
            name for name in self.flight.provider_order
            if name not in ("serpapi", "skyscrapper")
        ]
        if unknown:
            errors.append(f"Unbekannte Provider in provider_order: {unknown}")

        if not self.telegram.is_configured():
            errors.append("Telegram Bot Token/Chat ID nicht konfiguriert")

        if self.flight.max_stops not in (0, 1, 2):
            errors.append(f"max_stops muss 0, 1 oder 2 sein (ist: {self.flight.max_stops})")

        valid_time_prefs = ("morning", "afternoon", "evening", "no_night", "any")
        if self.flight.departure_time_preference not in valid_time_prefs:
            errors.append(
                f"departure_time_preference ungültig: {self.flight.departure_time_preference}"
            )

        return errors


def load_config(config: AppConfig | None = None) -> AppConfig:
    """
    Validiert die App-Konfiguration und protokolliert sie.

    Args:
        config: Optional eine vorbereitete Konfiguration (z.B. mit gesetzter
                Ziel-Rotation). Ohne Angabe werden die Defaults genutzt.
    """
    config = config or AppConfig()
    errors = config.validate()

    if errors:
        for error in errors:
            logger.warning(f"Konfigurations-Warnung: {error}")

    logger.info("Konfiguration geladen")
    logger.info(f"  Abflughäfen: {config.flight.departure_airports}")
    logger.info(
        f"  Ziele diesen Lauf: {config.flight.destination_airports}"
        + (
            " (inkl. sekundäre)"
            if config.flight.include_secondary_destinations
            else f" – sekundär {config.flight.secondary_destinations} übersprungen"
        )
    )
    logger.info(f"  Reisende: {config.flight.adults} Erwachsene + {config.flight.num_children} Kinder")
    logger.info(f"  Flexibilität: ±{config.flight.flexibility_days} Tage")
    logger.info(f"  Max Stopps: {config.flight.max_stops}")
    logger.info(f"  Preislimit: {config.flight.price_limit_alert}€")
    logger.info("  --- Suchdienste ---")
    active = config.configured_providers
    if active:
        logger.info(f"  Provider-Kette: {' → '.join(active)}")
    else:
        logger.warning("  Kein Suchdienst konfiguriert!")
    for name, ok in (
        ("SerpApi", config.serpapi.is_configured()),
        ("Sky Scrapper", config.rapidapi.is_configured()),
    ):
        logger.info(f"    {name}: {'konfiguriert' if ok else 'fehlt'}")

    logger.info("  --- API-Budget ---")
    logger.info(f"  Routen pro Datumspaar: {config.flight.num_routes}")
    logger.info(f"  Gepäck-Varianten: {config.flight.luggage_variants}")
    logger.info(f"  Max API-Anfragen/Lauf: {config.flight.max_api_calls_per_run}")
    logger.info(f"  → Max Datumspaare: {config.flight.max_date_pairs_total}")

    return config
