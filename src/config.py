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


@dataclass
class FlightConfig:
    """Flug-Suchkonfiguration."""

    # Abflughäfen (IATA-Codes)
    departure_airports: list[str] = field(
        default_factory=lambda: ["HAJ", "BER", "HAM", "FRA"]
    )

    # Zielflughäfen (IATA-Codes)
    destination_airports: list[str] = field(
        default_factory=lambda: ["IKA", "MHD"]
    )

    # Reisende
    adults: int = 2
    children_ages: list[int] = field(default_factory=lambda: [5, 8])

    # Gepäck-Optionen (immer beides suchen)
    search_with_luggage: bool = True
    search_without_luggage: bool = True

    # Flexibilität in Tagen (±)
    flexibility_days: int = 2

    # Zwischenstopp-Filter
    max_stops: int = 1  # 0 = nur direkt, 1 = max 1 Stopp, 2 = max 2 Stopps
    min_connection_time_hours: float = 2.0  # Mindest-Umsteigezeit in Stunden

    # Abflugzeit-Präferenz
    # Optionen: "morning", "afternoon", "evening", "no_night", "any"
    departure_time_preference: str = "no_night"

    # Wochenend-Präferenz
    prefer_weekend_departure: bool = True  # Freitag/Samstag Hinflug bevorzugen
    prefer_weekend_return: bool = True  # Sonntag Rückflug bevorzugen
    weekend_price_tolerance: int = 100  # Max Aufpreis in € für Wochenend-Option

    # Preislimit für Alarm (Gesamtpreis alle Personen in €)
    price_limit_alert: int = 1500

    # Preis-Bewertung
    cheap_threshold_percent: float = 20.0  # "Sehr günstig" wenn X% unter Durchschnitt

    # Kombi-Tickets
    enable_combo_tickets: bool = True
    combo_min_savings: int = 100  # Nur anzeigen wenn >X€ günstiger

    # Preis-Vorhersage
    enable_price_prediction: bool = True
    prediction_min_data_days: int = 14  # Mindestens X Tage Daten für Vorhersage

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
    """SerpApi Konfiguration (Google Flights)."""

    api_key: str = field(default_factory=lambda: os.getenv("SERPAPI_API_KEY", ""))

    def is_configured(self) -> bool:
        """Prüft ob API-Key gesetzt ist."""
        return bool(self.api_key)


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
    telegram: TelegramConfig = field(default_factory=TelegramConfig)
    paths: PathConfig = field(default_factory=PathConfig)

    def validate(self) -> list[str]:
        """
        Validiert die Konfiguration.
        Gibt eine Liste von Fehlermeldungen zurück (leer = alles OK).
        """
        errors = []

        if not self.serpapi.is_configured():
            errors.append("SerpApi API Key nicht konfiguriert (SERPAPI_API_KEY)")

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


def load_config() -> AppConfig:
    """Lädt und validiert die App-Konfiguration."""
    config = AppConfig()
    errors = config.validate()

    if errors:
        for error in errors:
            logger.warning(f"Konfigurations-Warnung: {error}")

    logger.info("Konfiguration geladen")
    logger.info(f"  Abflughäfen: {config.flight.departure_airports}")
    logger.info(f"  Zielflughäfen: {config.flight.destination_airports}")
    logger.info(f"  Reisende: {config.flight.adults} Erwachsene + {config.flight.num_children} Kinder")
    logger.info(f"  Flexibilität: ±{config.flight.flexibility_days} Tage")
    logger.info(f"  Max Stopps: {config.flight.max_stops}")
    logger.info(f"  Preislimit: {config.flight.price_limit_alert}€")

    return config
