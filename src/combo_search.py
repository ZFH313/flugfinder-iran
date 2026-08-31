"""
Kombi-Ticket Suche.
Prüft ob ein anderer Rückflughafen günstiger ist als der Hinflughafen.
Beispiel: Hinflug HAM→IKA, Rückflug IKA→FRA

Achtung: Diese Suche ist teuer. Bei 4 Abflughäfen und 2 Zielen sind es
bis zu 32 API-Anfragen. Sie bricht daher ab sobald das Anfrage-Budget
knapp wird.
"""

import logging
from datetime import date

from .config import FlightConfig
from .flight_search import BudgetExhaustedError, FlightSearchClient
from .models import ComboTicket, LuggageType

logger = logging.getLogger(__name__)


def search_combo_tickets(
    client: FlightSearchClient,
    flight_config: FlightConfig,
    outbound_date: date,
    return_date: date,
    min_savings: int = 100,
) -> list[ComboTicket]:
    """
    Sucht Kombi-Tickets (unterschiedlicher Hin-/Rückflughafen).

    Args:
        client: Flugsuche-Orchestrator
        flight_config: Flug-Konfiguration
        outbound_date: Hinflug-Datum
        return_date: Rückflug-Datum
        min_savings: Nur anzeigen wenn mindestens X€ günstiger

    Returns:
        Liste günstiger Kombi-Tickets, sortiert nach Ersparnis
    """
    if not flight_config.enable_combo_tickets:
        logger.info("Kombi-Ticket Suche deaktiviert")
        return []

    if not client.has_capacity():
        logger.warning("Kombi-Ticket Suche übersprungen – kein Anfrage-Budget mehr")
        return []

    logger.info("Starte Kombi-Ticket Suche...")

    # Schritt 1: normale Preise ermitteln (gleicher Hin-/Rückflughafen)
    regular_prices = _get_regular_prices(
        client, flight_config, outbound_date, return_date
    )

    if not regular_prices:
        logger.warning("Keine regulären Preise gefunden – Kombi-Vergleich nicht möglich")
        return []

    combos: list[ComboTicket] = []

    # Schritt 2: alle Kombinationen mit abweichendem Rückflughafen prüfen
    for dest_airport in flight_config.destination_airports:
        for dep_airport in flight_config.departure_airports:
            for ret_airport in flight_config.departure_airports:
                # Gleicher Flughafen = normales Ticket, kein Kombi
                if dep_airport == ret_airport:
                    continue

                if not client.has_capacity():
                    logger.warning(
                        "Kombi-Suche vorzeitig beendet – Anfrage-Budget erschöpft"
                    )
                    combos.sort(key=lambda c: c.savings, reverse=True)
                    return combos

                combo_price = _search_combo_price(
                    client=client,
                    flight_config=flight_config,
                    departure_airport=dep_airport,
                    destination=dest_airport,
                    outbound_date=outbound_date,
                    return_date=return_date,
                )

                if combo_price is None:
                    continue

                # Vergleich mit dem günstigeren der beiden normalen Preise
                regular_price = min(
                    regular_prices.get(f"{dep_airport}-{dest_airport}", float("inf")),
                    regular_prices.get(f"{ret_airport}-{dest_airport}", float("inf")),
                )

                if regular_price == float("inf"):
                    continue

                savings = regular_price - combo_price

                if savings >= min_savings:
                    combos.append(
                        ComboTicket(
                            departure_airport=dep_airport,
                            return_airport=ret_airport,
                            destination_airport=dest_airport,
                            outbound_date=outbound_date,
                            return_date=return_date,
                            price_total=combo_price,
                            price_regular=regular_price,
                            savings=savings,
                            airline_outbound="",
                            airline_return="",
                            luggage_type=LuggageType.WITH_LUGGAGE,
                        )
                    )
                    logger.info(
                        f"  Kombi gefunden: {dep_airport}→{dest_airport}→{ret_airport} "
                        f"= {combo_price:.0f}€ (Ersparnis: {savings:.0f}€)"
                    )

    combos.sort(key=lambda c: c.savings, reverse=True)
    logger.info(f"Kombi-Ticket Suche abgeschlossen: {len(combos)} günstige Kombis")
    return combos


def _get_regular_prices(
    client: FlightSearchClient,
    flight_config: FlightConfig,
    outbound_date: date,
    return_date: date,
) -> dict[str, float]:
    """
    Ermittelt die regulären Preise (gleicher Hin-/Rückflughafen) je Route.

    Returns:
        Dict Route ("HAJ-IKA") → günstigster Preis
    """
    regular_prices: dict[str, float] = {}

    for dep_airport in flight_config.departure_airports:
        for dest_airport in flight_config.destination_airports:
            if not client.has_capacity():
                logger.warning("Preis-Erhebung abgebrochen – Anfrage-Budget erschöpft")
                return regular_prices

            try:
                flights = client.search_flights(
                    origin=dep_airport,
                    destination=dest_airport,
                    outbound_date=outbound_date,
                    return_date=return_date,
                    flight_config=flight_config,
                    luggage_type=LuggageType.WITH_LUGGAGE,
                )
            except BudgetExhaustedError as e:
                logger.warning(f"Preis-Erhebung abgebrochen: {e}")
                return regular_prices

            if flights:
                regular_prices[f"{dep_airport}-{dest_airport}"] = min(
                    f.price_total for f in flights
                )

    return regular_prices


def _search_combo_price(
    client: FlightSearchClient,
    flight_config: FlightConfig,
    departure_airport: str,
    destination: str,
    outbound_date: date,
    return_date: date,
) -> float | None:
    """Sucht den günstigsten Preis für eine Kombi-Route."""
    try:
        flights = client.search_flights(
            origin=departure_airport,
            destination=destination,
            outbound_date=outbound_date,
            return_date=return_date,
            flight_config=flight_config,
            luggage_type=LuggageType.WITH_LUGGAGE,
        )
    except BudgetExhaustedError as e:
        logger.warning(f"Kombi-Preis nicht ermittelbar: {e}")
        return None

    if not flights:
        return None

    return min(f.price_total for f in flights)
