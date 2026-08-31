"""
Flugsuche-Orchestrator.

Verwaltet eine Kette von Suchdiensten (Provider). Standardmäßig wird
SerpApi zuerst gefragt; ist dessen Kontingent erschöpft, übernimmt
automatisch Sky Scrapper.

Zusätzlich wacht ein hartes Anfrage-Budget darüber, dass ein einzelner
Lauf nicht das komplette Monatskontingent verbraucht.
"""

import logging
from datetime import date

from .config import AppConfig, FlightConfig
from .flight_providers import (
    FlightProvider,
    ProviderError,
    QuotaExceededError,
    build_providers,
)
from .models import FlightOffer, LuggageType

logger = logging.getLogger(__name__)


class BudgetExhaustedError(Exception):
    """Das Anfrage-Budget für diesen Lauf ist aufgebraucht."""


class FlightSearchClient:
    """
    Sucht Flüge über eine Kette von Providern mit automatischem Fallback.

    Ablauf pro Anfrage:
    1. Ersten nicht-erschöpften Provider nehmen
    2. Bei QuotaExceededError/ProviderError: Provider dauerhaft als erschöpft
       markieren und den nächsten probieren
    3. Ein erfolgreicher Aufruf gilt als erledigt – auch wenn er keine Flüge
       findet. Sonst würde jede leere Route das Budget mehrfach belasten.
    """

    def __init__(
        self,
        providers: list[FlightProvider],
        max_calls: int | None = None,
    ):
        self.providers = providers
        self.max_calls = max_calls
        self.searches_served: int = 0
        self.fallback_switches: int = 0

    @classmethod
    def from_config(cls, config: AppConfig) -> "FlightSearchClient":
        """Baut den Client aus der App-Konfiguration."""
        providers = build_providers(
            provider_names=config.flight.provider_order,
            serpapi_config=config.serpapi,
            rapidapi_config=config.rapidapi,
            airport_cache_file=config.paths.airport_ids_file,
        )
        return cls(providers, max_calls=config.flight.max_api_calls_per_run)

    # --- Zustand ---

    @property
    def calls_used(self) -> int:
        """Summe aller tatsächlich abgesetzten API-Anfragen."""
        return sum(p.calls_made for p in self.providers)

    @property
    def calls_remaining(self) -> int | None:
        """Wie viele Anfragen das Budget noch erlaubt (None = unbegrenzt)."""
        if self.max_calls is None:
            return None
        return max(0, self.max_calls - self.calls_used)

    @property
    def active_provider(self) -> FlightProvider | None:
        """Der Provider der aktuell die Anfragen bedient."""
        for provider in self.providers:
            if not provider.exhausted:
                return provider
        return None

    def has_capacity(self) -> bool:
        """Kann überhaupt noch gesucht werden?"""
        if not self.providers:
            return False
        if self.active_provider is None:
            return False
        remaining = self.calls_remaining
        return remaining is None or remaining > 0

    # --- Suche ---

    def search_flights(
        self,
        origin: str,
        destination: str,
        outbound_date: date,
        return_date: date,
        flight_config: FlightConfig,
        luggage_type: LuggageType = LuggageType.WITH_LUGGAGE,
    ) -> list[FlightOffer]:
        """
        Sucht Flüge für eine Route und ein Datumspaar.

        Returns:
            Gefundene Flüge (leer wenn nichts gefunden oder kein Provider mehr kann)

        Raises:
            BudgetExhaustedError: Anfrage-Budget aufgebraucht
        """
        remaining = self.calls_remaining
        if remaining is not None and remaining <= 0:
            raise BudgetExhaustedError(
                f"Anfrage-Budget von {self.max_calls} Aufrufen erreicht"
            )

        for provider in self.providers:
            if provider.exhausted:
                continue

            try:
                flights = provider.search(
                    origin=origin,
                    destination=destination,
                    outbound_date=outbound_date,
                    return_date=return_date,
                    flight_config=flight_config,
                    luggage_type=luggage_type,
                )
                self.searches_served += 1
                return flights

            except QuotaExceededError as e:
                provider.exhausted = True
                self.fallback_switches += 1
                logger.warning(
                    f"Provider '{provider.name}' erschöpft: {e}"
                )
                next_provider = self.active_provider
                if next_provider:
                    logger.info(f"Wechsle auf Provider '{next_provider.name}'")
                else:
                    logger.error("Kein weiterer Provider verfügbar!")

            except ProviderError as e:
                provider.exhausted = True
                logger.error(f"Provider '{provider.name}' deaktiviert: {e}")

        return []

    # --- Bericht ---

    def stats_summary(self) -> list[str]:
        """Kurzbericht über die Provider-Nutzung (für Logs)."""
        lines = [
            f"API-Anfragen gesamt: {self.calls_used}"
            + (f" von max. {self.max_calls}" if self.max_calls else ""),
            f"Bediente Suchen: {self.searches_served}",
        ]
        for provider in self.providers:
            state = "erschöpft" if provider.exhausted else "aktiv"
            lines.append(
                f"  {provider.display_name} ({provider.name}): "
                f"{provider.calls_made} Anfragen, {state}"
            )
        if self.fallback_switches:
            lines.append(f"Provider-Wechsel: {self.fallback_switches}")
        return lines


def search_all_routes(
    client: FlightSearchClient,
    flight_config: FlightConfig,
    travel_dates: list[tuple[date, date]],
) -> list[FlightOffer]:
    """
    Durchsucht alle Kombinationen aus Abflughafen, Zielflughafen,
    Datumspaar und Gepäckvariante – begrenzt durch das Anfrage-Budget.

    Args:
        client: Orchestrator mit Provider-Kette
        flight_config: Flug-Konfiguration
        travel_dates: Liste der (Hinflug, Rückflug) Datumspaare

    Returns:
        Alle gefundenen Flüge, sortiert nach Preis
    """
    if not client.providers:
        logger.error("Kein Suchdienst konfiguriert – Suche wird übersprungen")
        return []

    luggage_variants: list[LuggageType] = []
    if flight_config.search_with_luggage:
        luggage_variants.append(LuggageType.WITH_LUGGAGE)
    if flight_config.search_without_luggage:
        luggage_variants.append(LuggageType.WITHOUT_LUGGAGE)
    if not luggage_variants:
        luggage_variants = [LuggageType.WITH_LUGGAGE]

    all_flights: list[FlightOffer] = []
    skipped = 0

    for outbound_date, return_date in travel_dates:
        for dep_airport in flight_config.departure_airports:
            for dest_airport in flight_config.destination_airports:
                for luggage_type in luggage_variants:
                    if not client.has_capacity():
                        skipped += 1
                        continue

                    try:
                        flights = client.search_flights(
                            origin=dep_airport,
                            destination=dest_airport,
                            outbound_date=outbound_date,
                            return_date=return_date,
                            flight_config=flight_config,
                            luggage_type=luggage_type,
                        )
                        all_flights.extend(flights)
                    except BudgetExhaustedError as e:
                        logger.warning(f"Suche abgebrochen: {e}")
                        skipped += 1

    if skipped:
        logger.warning(
            f"{skipped} Suchanfragen übersprungen (Budget oder Provider erschöpft)"
        )

    all_flights.sort(key=lambda f: f.price_total)

    logger.info("Suche abgeschlossen:")
    for line in client.stats_summary():
        logger.info(f"  {line}")
    logger.info(f"  Gefundene Flüge: {len(all_flights)}")

    return all_flights
