"""
Kombi-Ticket Suche.
Prüft ob ein anderer Rückflughafen günstiger ist als der Hinflughafen.
Beispiel: Hinflug HAM→IKA, Rückflug IKA→FRA
"""

import logging
from datetime import date

from .config import FlightConfig
from .flight_search import SerpApiClient, parse_serpapi_response
from .models import ComboTicket, FlightOffer, LuggageType

logger = logging.getLogger(__name__)


def search_combo_tickets(
    client: SerpApiClient,
    flight_config: FlightConfig,
    outbound_date: date,
    return_date: date,
    min_savings: int = 100,
) -> list[ComboTicket]:
    """
    Sucht Kombi-Tickets (unterschiedlicher Hin-/Rückflughafen).

    Prüft alle Kombinationen:
    4 Abflughäfen × 4 Rückflughäfen × 2 Zielflughäfen = 32 Kombinationen
    (minus die 8 "normalen" wo Abflug = Rückflug)

    Args:
        client: Amadeus API Client
        flight_config: Flug-Konfiguration
        outbound_date: Hinflug-Datum
        return_date: Rückflug-Datum
        min_savings: Nur anzeigen wenn >X€ günstiger

    Returns:
        Liste günstiger Kombi-Tickets
    """
    if not flight_config.enable_combo_tickets:
        logger.info("Kombi-Ticket Suche deaktiviert")
        return []

    logger.info("Starte Kombi-Ticket Suche...")

    # Erst: normale Preise ermitteln (gleicher Hin-/Rückflughafen)
    regular_prices = _get_regular_prices(
        client, flight_config, outbound_date, return_date
    )

    if not regular_prices:
        logger.warning("Keine regulären Preise gefunden für Kombi-Vergleich")
        return []

    combos: list[ComboTicket] = []

    # Alle Kombinationen durchprobieren
    for dest_airport in flight_config.destination_airports:
        for dep_airport in flight_config.departure_airports:
            for ret_airport in flight_config.departure_airports:
                # Überspringe wenn gleicher Flughafen (das ist ein normales Ticket)
                if dep_airport == ret_airport:
                    continue

                # Suche: Hinflug dep→dest, Rückflug dest→ret
                combo_price = _search_combo_price(
                    client=client,
                    flight_config=flight_config,
                    departure_airport=dep_airport,
                    return_airport=ret_airport,
                    destination=dest_airport,
                    outbound_date=outbound_date,
                    return_date=return_date,
                )

                if combo_price is None:
                    continue

                # Vergleiche mit normalem Preis (günstigster von dep oder ret)
                regular_key_dep = f"{dep_airport}-{dest_airport}"
                regular_key_ret = f"{ret_airport}-{dest_airport}"

                regular_price = min(
                    regular_prices.get(regular_key_dep, float("inf")),
                    regular_prices.get(regular_key_ret, float("inf")),
                )

                if regular_price == float("inf"):
                    continue

                savings = regular_price - combo_price

                if savings >= min_savings:
                    combo = ComboTicket(
                        departure_airport=dep_airport,
                        return_airport=ret_airport,
                        destination_airport=dest_airport,
                        outbound_date=outbound_date,
                        return_date=return_date,
                        price_total=combo_price,
                        price_regular=regular_price,
                        savings=savings,
                        airline_outbound="",  # Wird beim Parsen gefüllt
                        airline_return="",
                        luggage_type=LuggageType.WITH_LUGGAGE,
                    )
                    combos.append(combo)

                    logger.info(
                        f"  Kombi gefunden: {dep_airport}→{dest_airport}→{ret_airport} "
                        f"= {combo_price:.0f}€ (Ersparnis: {savings:.0f}€)"
                    )

    # Sortiere nach Ersparnis
    combos.sort(key=lambda c: c.savings, reverse=True)

    logger.info(f"Kombi-Ticket Suche abgeschlossen: {len(combos)} günstige Kombis gefunden")
    return combos


def _get_regular_prices(
    client: SerpApiClient,
    flight_config: FlightConfig,
    outbound_date: date,
    return_date: date,
) -> dict[str, float]:
    """
    Ermittelt die regulären Preise (gleicher Hin-/Rückflughafen) für alle Routen.
    Returns: Dict Route → günstigster Preis
    """
    regular_prices: dict[str, float] = {}

    for dep_airport in flight_config.departure_airports:
        for dest_airport in flight_config.destination_airports:
            raw = client.search_flights(
                origin=dep_airport,
                destination=dest_airport,
                departure_date=outbound_date,
                return_date=return_date,
                adults=flight_config.adults,
                children=flight_config.num_children,
                max_stops=flight_config.max_stops,
                luggage_type=LuggageType.WITH_LUGGAGE,
            )

            if raw:
                flights = parse_serpapi_response(
                    raw, dep_airport, dest_airport,
                    LuggageType.WITH_LUGGAGE, flight_config
                )
                if flights:
                    cheapest = min(f.price_total for f in flights)
                    route_key = f"{dep_airport}-{dest_airport}"
                    regular_prices[route_key] = cheapest

    return regular_prices


def _search_combo_price(
    client: SerpApiClient,
    flight_config: FlightConfig,
    departure_airport: str,
    return_airport: str,
    destination: str,
    outbound_date: date,
    return_date: date,
) -> float | None:
    """
    Sucht den Preis für ein Kombi-Ticket (Hinflug von A, Rückflug nach B).
    """
    outbound_raw = client.search_flights(
        origin=departure_airport,
        destination=destination,
        departure_date=outbound_date,
        return_date=return_date,
        adults=flight_config.adults,
        children=flight_config.num_children,
        max_stops=flight_config.max_stops,
        luggage_type=LuggageType.WITH_LUGGAGE,
    )

    if not outbound_raw:
        return None

    flights = parse_serpapi_response(
        outbound_raw, departure_airport, destination,
        LuggageType.WITH_LUGGAGE, flight_config
    )

    if not flights:
        return None

    cheapest = min(f.price_total for f in flights)
    return cheapest
