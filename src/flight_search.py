"""
Flugsuche über SerpApi (Google Flights).
Nutzt die google_flights Engine von SerpApi für Flugpreisabfragen.
"""

import logging
import time
from datetime import date, datetime
from typing import Any

import requests

from .config import FlightConfig, SerpApiConfig
from .models import FlightOffer, FlightSegment, LuggageType

logger = logging.getLogger(__name__)

# Rate Limiting: SerpApi erlaubt mehr, aber wir sind vorsichtig
REQUEST_DELAY_SECONDS = 0.5

# SerpApi Airport-Codes (gleich wie IATA)
# HAJ = Hannover, BER = Berlin, HAM = Hamburg, FRA = Frankfurt
# IKA = Teheran Imam Khomeini, MHD = Mashhad


class SerpApiClient:
    """Client für die SerpApi Google Flights API."""

    BASE_URL = "https://serpapi.com/search.json"

    def __init__(self, config: SerpApiConfig):
        self.config = config
        self._last_request_time: float = 0

    def _rate_limit(self) -> None:
        """Wartet wenn nötig um Rate Limit einzuhalten."""
        elapsed = time.time() - self._last_request_time
        if elapsed < REQUEST_DELAY_SECONDS:
            time.sleep(REQUEST_DELAY_SECONDS - elapsed)
        self._last_request_time = time.time()

    def search_flights(
        self,
        origin: str,
        destination: str,
        departure_date: date,
        return_date: date,
        adults: int,
        children: int,
        max_stops: int = 1,
        luggage_type: LuggageType = LuggageType.WITH_LUGGAGE,
    ) -> dict[str, Any]:
        """
        Sucht Flüge über SerpApi Google Flights.

        Args:
            origin: Abflughafen IATA-Code (z.B. "HAJ")
            destination: Zielflughafen IATA-Code (z.B. "IKA")
            departure_date: Hinflug-Datum
            return_date: Rückflug-Datum
            adults: Anzahl Erwachsene
            children: Anzahl Kinder
            max_stops: Maximale Zwischenstopps (0, 1, 2)
            luggage_type: Mit oder ohne Gepäck

        Returns:
            Rohe API-Antwort als Dict
        """
        self._rate_limit()

        # Stopps-Parameter: 0=beliebig, 1=max 1, 2=max 2, 3=nur direkt
        # SerpApi: stops = 0 (any), 1 (nonstop), 2 (1 stop or fewer), 3 (2 stops or fewer)
        stops_map = {0: 1, 1: 2, 2: 3}  # unsere Config → SerpApi Parameter
        stops_param = stops_map.get(max_stops, 0)

        # Gepäck: bags Parameter (0 = kein Aufgabegepäck, 1+ = mit)
        bags = 1 if luggage_type == LuggageType.WITH_LUGGAGE else 0

        params = {
            "engine": "google_flights",
            "api_key": self.config.api_key,
            "departure_id": origin,
            "arrival_id": destination,
            "outbound_date": departure_date.isoformat(),
            "return_date": return_date.isoformat(),
            "adults": adults,
            "children": children,
            "currency": "EUR",
            "hl": "de",  # Sprache: Deutsch
            "gl": "de",  # Land: Deutschland
            "type": "1",  # 1 = Round Trip, 2 = One Way
            "bags": bags,
        }

        # Stopps nur setzen wenn nicht "beliebig"
        if stops_param > 0:
            params["stops"] = stops_param

        try:
            logger.debug(f"Suche: {origin}→{destination} ({departure_date} – {return_date})")
            response = requests.get(self.BASE_URL, params=params, timeout=60)
            response.raise_for_status()
            data = response.json()

            # Prüfe auf API-Fehler
            if "error" in data:
                logger.error(f"  SerpApi Fehler: {data['error']}")
                return {}

            # Ergebnis-Info loggen
            best_flights = data.get("best_flights", [])
            other_flights = data.get("other_flights", [])
            total = len(best_flights) + len(other_flights)
            logger.info(f"  {origin}→{destination}: {total} Angebote gefunden")

            return data

        except requests.RequestException as e:
            logger.error(f"  Fehler bei {origin}→{destination}: {e}")
            return {}


def parse_serpapi_response(
    raw_data: dict[str, Any],
    origin: str,
    destination: str,
    luggage_type: LuggageType,
    flight_config: FlightConfig,
) -> list[FlightOffer]:
    """
    Parst die SerpApi Google Flights Antwort in FlightOffer Objekte.

    Args:
        raw_data: Rohe API-Antwort
        origin: Abflughafen
        destination: Zielflughafen
        luggage_type: Gepäck-Variante
        flight_config: Flug-Konfiguration für Filter

    Returns:
        Liste validierter FlightOffer Objekte
    """
    if not raw_data:
        return []

    flights = []

    # SerpApi gibt "best_flights" und "other_flights" zurück
    all_results = raw_data.get("best_flights", []) + raw_data.get("other_flights", [])

    for result in all_results:
        try:
            flight = _parse_single_result(result, origin, destination, luggage_type, flight_config)
            if flight:
                flights.append(flight)
        except (KeyError, ValueError, IndexError, TypeError) as e:
            logger.warning(f"Konnte Angebot nicht parsen: {e}")
            continue

    return flights


def _parse_single_result(
    result: dict[str, Any],
    origin: str,
    destination: str,
    luggage_type: LuggageType,
    flight_config: FlightConfig,
) -> FlightOffer | None:
    """Parst ein einzelnes Flugergebnis von SerpApi."""

    # Preis
    price_total = result.get("price")
    if price_total is None:
        return None

    # SerpApi Preis ist pro Person → multiplizieren
    # ACHTUNG: Google Flights zeigt Gesamtpreis für alle Reisende
    # Je nach SerpApi-Antwort kann es pro Person oder gesamt sein
    # Wir nehmen den Preis wie er kommt (Google zeigt Gesamtpreis)
    total_passengers = flight_config.total_passengers
    price_per_person = price_total / total_passengers

    # Flüge: SerpApi gibt "flights" Array zurück (Hin- und Rückflug-Segmente)
    flight_legs = result.get("flights", [])
    if not flight_legs:
        return None

    # Gesamtdauer
    total_duration = result.get("total_duration", 0)  # in Minuten

    # Layovers (Zwischenstopps)
    layovers = result.get("layovers", [])
    num_stops = len(layovers)

    # Typ: "Round trip" hat separate outbound/return in der Antwort
    # Bei SerpApi sind die flights im Result alle vom Hinflug
    # Der Rückflug kommt in einem separaten "return_flights" oder
    # ist in der gleichen Liste (wenn Round Trip angefordert)

    # Segmente parsen
    segments = _parse_segments(flight_legs)

    if not segments:
        return None

    # Abflugzeit-Filter
    time_range = flight_config.get_departure_time_range()
    if time_range and segments:
        dep_time = segments[0].departure_time.strftime("%H:%M")
        if dep_time < time_range[0] or dep_time > time_range[1]:
            return None

    # Umsteigezeit prüfen
    if not _check_connection_time(layovers, flight_config.min_connection_time_hours):
        return None

    # Daten aus erstem/letztem Segment
    outbound_date = segments[0].departure_time.date()
    # Rückflugdatum: Wenn vorhanden aus den Daten, sonst approximieren
    # SerpApi Round-Trip: separate Ergebnisse für Hin und Rück
    return_date_val = outbound_date  # Wird beim Aufruf korrekt gesetzt

    # Airline (erste im Ergebnis)
    airline = ""
    if flight_legs:
        airline = flight_legs[0].get("airline", "")

    # Wochenend-Check
    from .school_holidays import is_weekend_departure
    is_weekend = is_weekend_departure(outbound_date, return_date_val)

    flight = FlightOffer(
        departure_airport=origin,
        destination_airport=destination,
        outbound_date=outbound_date,
        return_date=return_date_val,
        price_total=float(price_total),
        price_per_person=price_per_person,
        currency="EUR",
        luggage_type=luggage_type,
        airline=airline,
        stops_outbound=num_stops,
        stops_return=0,  # Wird separat befüllt
        duration_outbound_minutes=total_duration,
        duration_return_minutes=0,  # Wird separat befüllt
        segments_outbound=segments,
        segments_return=[],
        is_weekend_flight=is_weekend,
    )

    return flight


def _parse_segments(flight_legs: list[dict[str, Any]]) -> list[FlightSegment]:
    """Parst Flug-Segmente aus der SerpApi-Antwort."""
    segments = []

    for leg in flight_legs:
        departure_airport_data = leg.get("departure_airport", {})
        arrival_airport_data = leg.get("arrival_airport", {})

        # Zeitformat von SerpApi: "2026-12-23 08:30" oder ähnlich
        dep_time_str = departure_airport_data.get("time", "")
        arr_time_str = arrival_airport_data.get("time", "")

        # Datum aus departure_airport.date oder dem Kontext
        dep_date = departure_airport_data.get("date", "")

        # Versuche verschiedene Zeitformate
        dep_time = _parse_datetime(dep_date, dep_time_str)
        arr_time = _parse_datetime(
            arrival_airport_data.get("date", dep_date),
            arr_time_str,
        )

        segment = FlightSegment(
            departure_airport=departure_airport_data.get("id", "???"),
            arrival_airport=arrival_airport_data.get("id", "???"),
            departure_time=dep_time,
            arrival_time=arr_time,
            airline=leg.get("airline", ""),
            flight_number=leg.get("flight_number", ""),
            duration_minutes=leg.get("duration", 0),
        )
        segments.append(segment)

    return segments


def _parse_datetime(date_str: str, time_str: str) -> datetime:
    """
    Parst Datum und Uhrzeit aus SerpApi-Antwort.
    Verschiedene Formate werden unterstützt.
    """
    # Format 1: "2026-12-23 08:30"
    if date_str and time_str:
        try:
            combined = f"{date_str} {time_str}"
            return datetime.strptime(combined, "%Y-%m-%d %H:%M")
        except ValueError:
            pass

        try:
            combined = f"{date_str} {time_str}"
            return datetime.strptime(combined, "%Y-%m-%d %I:%M %p")
        except ValueError:
            pass

    # Format 2: time_str enthält schon Datum+Zeit
    if time_str:
        for fmt in ["%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M", "%H:%M"]:
            try:
                return datetime.strptime(time_str, fmt)
            except ValueError:
                continue

    # Fallback
    return datetime(2000, 1, 1, 0, 0)


def _check_connection_time(layovers: list[dict[str, Any]], min_hours: float) -> bool:
    """
    Prüft ob alle Umsteigezeiten ausreichend sind.
    SerpApi gibt layovers als [{duration: 120, name: "Istanbul"}, ...] zurück.
    """
    if not layovers:
        return True  # Direktflug

    min_minutes = min_hours * 60

    for layover in layovers:
        duration = layover.get("duration", 0)  # in Minuten
        if duration < min_minutes:
            logger.debug(
                f"Umsteigezeit zu kurz: {duration}min "
                f"(min: {min_minutes:.0f}min) bei {layover.get('name', '?')}"
            )
            return False

    return True


def search_all_routes(
    client: SerpApiClient,
    flight_config: FlightConfig,
    travel_dates: list[tuple[date, date]],
) -> list[FlightOffer]:
    """
    Durchsucht alle Routen (Abflughäfen × Zielflughäfen × Daten × Gepäck).

    Args:
        client: SerpApi Client
        flight_config: Flug-Konfiguration
        travel_dates: Liste der (Hinflug, Rückflug) Datum-Kombinationen

    Returns:
        Alle gefundenen Flüge, sortiert nach Preis
    """
    all_flights: list[FlightOffer] = []
    total_searches = 0

    for dep_airport in flight_config.departure_airports:
        for dest_airport in flight_config.destination_airports:
            for outbound_date, return_date in travel_dates:
                # Suche MIT Gepäck
                if flight_config.search_with_luggage:
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
                    total_searches += 1

                    flights = parse_serpapi_response(
                        raw, dep_airport, dest_airport,
                        LuggageType.WITH_LUGGAGE, flight_config
                    )
                    # Rückflug-Datum korrekt setzen
                    for f in flights:
                        f.return_date = return_date
                    all_flights.extend(flights)

                # Suche OHNE Gepäck
                if flight_config.search_without_luggage:
                    raw = client.search_flights(
                        origin=dep_airport,
                        destination=dest_airport,
                        departure_date=outbound_date,
                        return_date=return_date,
                        adults=flight_config.adults,
                        children=flight_config.num_children,
                        max_stops=flight_config.max_stops,
                        luggage_type=LuggageType.WITHOUT_LUGGAGE,
                    )
                    total_searches += 1

                    flights = parse_serpapi_response(
                        raw, dep_airport, dest_airport,
                        LuggageType.WITHOUT_LUGGAGE, flight_config
                    )
                    for f in flights:
                        f.return_date = return_date
                    all_flights.extend(flights)

    # Nach Preis sortieren
    all_flights.sort(key=lambda f: f.price_total)

    logger.info(
        f"Suche abgeschlossen: {total_searches} API-Anfragen, "
        f"{len(all_flights)} Flüge gefunden"
    )

    return all_flights
