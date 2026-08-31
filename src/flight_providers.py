"""
Suchdienste (Provider) für die Flugsuche.

Jeder Provider kapselt eine externe API und liefert fertig geparste
FlightOffer-Objekte zurück. Damit bleiben die Aufrufer unabhängig davon,
welcher Dienst die Daten tatsächlich geliefert hat.

Aktuell verfügbar:
- SerpApiProvider   → Google Flights über SerpApi (Free-Tier: 100 Suchen/Monat)
- SkyScrapperProvider → Skyscanner-Daten über RapidAPI (Fallback)
"""

import json
import logging
import time
from abc import ABC, abstractmethod
from datetime import date, datetime
from pathlib import Path
from typing import Any

import requests

from .config import FlightConfig, RapidApiConfig, SerpApiConfig
from .models import FlightOffer, FlightSegment, LuggageType

logger = logging.getLogger(__name__)

# Platzhalter für nicht lesbare Zeitangaben.
# Wichtig: Filter müssen diesen Wert erkennen und durchlassen, statt den Flug
# zu verwerfen. Sonst würde ein Formatwechsel der API alle Treffer lautlos
# aussortieren, weil "00:00" außerhalb jedes erlaubten Zeitfensters liegt.
UNKNOWN_TIME = datetime(2000, 1, 1)


class QuotaExceededError(Exception):
    """
    Das Kontingent des Providers ist erschöpft.

    Der Orchestrator schaltet daraufhin dauerhaft auf den nächsten
    Provider in der Kette um.
    """


class ProviderError(Exception):
    """Ein nicht behebbarer Fehler des Providers (z.B. ungültiger Key)."""


class FlightProvider(ABC):
    """Basisklasse für alle Suchdienste."""

    #: Kurzname des Providers (erscheint in Logs und im Frontend)
    name: str = "unknown"

    #: Menschenlesbarer Anzeigename
    display_name: str = "Unbekannt"

    def __init__(self) -> None:
        self.calls_made: int = 0
        self.exhausted: bool = False
        self._last_request_time: float = 0.0

    @abstractmethod
    def is_configured(self) -> bool:
        """Ist der Provider einsatzbereit (API-Key vorhanden)?"""

    @abstractmethod
    def search(
        self,
        origin: str,
        destination: str,
        outbound_date: date,
        return_date: date,
        flight_config: FlightConfig,
        luggage_type: LuggageType = LuggageType.WITH_LUGGAGE,
    ) -> list[FlightOffer]:
        """
        Sucht Flüge für eine konkrete Route und ein konkretes Datumspaar.

        Raises:
            QuotaExceededError: Kontingent erschöpft
            ProviderError: dauerhafter Fehler (z.B. ungültiger Key)
        """

    # --- Gemeinsame Helfer ---

    def _rate_limit(self, delay_seconds: float) -> None:
        """Hält einen Mindestabstand zwischen zwei Anfragen ein."""
        elapsed = time.time() - self._last_request_time
        if elapsed < delay_seconds:
            time.sleep(delay_seconds - elapsed)
        self._last_request_time = time.time()

    def _passes_departure_time_filter(
        self, segments: list[FlightSegment], flight_config: FlightConfig
    ) -> bool:
        """
        Prüft ob die Abflugzeit in den gewünschten Zeitraum fällt.

        Ist die Zeit nicht lesbar, wird der Flug durchgelassen. Lieber ein
        Flug mit unbekannter Abflugzeit als ein leeres Ergebnis, weil sich
        das Datumsformat der API geändert hat.
        """
        time_range = flight_config.get_departure_time_range()
        if not time_range or not segments:
            return True

        departure = segments[0].departure_time
        if departure == UNKNOWN_TIME:
            logger.warning(
                f"[{self.name}] Abflugzeit unbekannt – Zeitfilter übersprungen "
                f"({segments[0].departure_airport}→{segments[0].arrival_airport})"
            )
            return True

        dep_time = departure.strftime("%H:%M")
        return time_range[0] <= dep_time <= time_range[1]


# =====================================================================
# SerpApi (Google Flights)
# =====================================================================


class SerpApiProvider(FlightProvider):
    """Google Flights über SerpApi."""

    name = "serpapi"
    display_name = "Google Flights"

    BASE_URL = "https://serpapi.com/search.json"
    REQUEST_DELAY_SECONDS = 0.5
    MAX_RETRIES = 3

    #: Textbausteine in SerpApi-Fehlermeldungen die auf Kontingent-Ende hindeuten
    QUOTA_HINTS = ("run out", "exceeded", "plan limit", "searches left", "upgrade")

    def __init__(self, config: SerpApiConfig):
        super().__init__()
        self.config = config

    def is_configured(self) -> bool:
        return self.config.is_configured()

    def search(
        self,
        origin: str,
        destination: str,
        outbound_date: date,
        return_date: date,
        flight_config: FlightConfig,
        luggage_type: LuggageType = LuggageType.WITH_LUGGAGE,
    ) -> list[FlightOffer]:
        raw = self._request(
            origin=origin,
            destination=destination,
            outbound_date=outbound_date,
            return_date=return_date,
            adults=flight_config.adults,
            children=flight_config.num_children,
            max_stops=flight_config.max_stops,
            luggage_type=luggage_type,
        )
        if not raw:
            return []

        flights = self._parse(
            raw, origin, destination, luggage_type, flight_config, outbound_date
        )
        # SerpApi liefert das Rückflugdatum nicht zuverlässig mit → setzen
        for flight in flights:
            flight.return_date = return_date
        return flights

    def _request(
        self,
        origin: str,
        destination: str,
        outbound_date: date,
        return_date: date,
        adults: int,
        children: int,
        max_stops: int,
        luggage_type: LuggageType,
    ) -> dict[str, Any]:
        """Führt die HTTP-Anfrage inkl. Retry-Logik aus."""
        self._rate_limit(self.REQUEST_DELAY_SECONDS)

        # Unsere Config → SerpApi Parameter
        # SerpApi: 1 = nonstop, 2 = max 1 Stopp, 3 = max 2 Stopps
        stops_map = {0: 1, 1: 2, 2: 3}
        stops_param = stops_map.get(max_stops, 0)

        params: dict[str, Any] = {
            "engine": "google_flights",
            "api_key": self.config.api_key,
            "departure_id": origin,
            "arrival_id": destination,
            "outbound_date": outbound_date.isoformat(),
            "return_date": return_date.isoformat(),
            "adults": adults,
            "children": children,
            "currency": "EUR",
            "hl": "de",
            "gl": "de",
            "type": "1",  # Round Trip
            "bags": 1 if luggage_type == LuggageType.WITH_LUGGAGE else 0,
        }
        if stops_param > 0:
            params["stops"] = stops_param

        for attempt in range(self.MAX_RETRIES):
            try:
                logger.debug(
                    f"[{self.name}] {origin}→{destination} "
                    f"({outbound_date} – {return_date})"
                )
                response = requests.get(self.BASE_URL, params=params, timeout=60)
                self.calls_made += 1

                if response.status_code == 429:
                    # Kann Rate-Limit ODER Kontingent-Ende sein.
                    # Beim letzten Versuch als Kontingent-Ende behandeln.
                    if attempt < self.MAX_RETRIES - 1:
                        wait = (2 ** attempt) * 5
                        logger.warning(
                            f"[{self.name}] 429 erhalten, warte {wait}s "
                            f"(Versuch {attempt + 1}/{self.MAX_RETRIES})"
                        )
                        time.sleep(wait)
                        continue
                    raise QuotaExceededError(
                        "SerpApi antwortet dauerhaft mit 429 – Kontingent vermutlich erschöpft"
                    )

                if response.status_code == 401:
                    raise ProviderError("SerpApi: API-Key ungültig (401)")

                response.raise_for_status()
                data = response.json()

                if "error" in data:
                    message = str(data["error"])
                    lowered = message.lower()
                    if any(hint in lowered for hint in self.QUOTA_HINTS):
                        raise QuotaExceededError(f"SerpApi: {message}")
                    logger.error(f"[{self.name}] API-Fehler: {message}")
                    return {}

                found = len(data.get("best_flights", [])) + len(data.get("other_flights", []))
                logger.info(f"[{self.name}] {origin}→{destination}: {found} Angebote")
                return data

            except requests.Timeout:
                if attempt < self.MAX_RETRIES - 1:
                    wait = (2 ** attempt) * 3
                    logger.warning(
                        f"[{self.name}] Timeout, warte {wait}s "
                        f"(Versuch {attempt + 1}/{self.MAX_RETRIES})"
                    )
                    time.sleep(wait)
                    continue
                logger.error(f"[{self.name}] Timeout nach {self.MAX_RETRIES} Versuchen")
                return {}

            except requests.RequestException as e:
                logger.error(f"[{self.name}] Fehler bei {origin}→{destination}: {e}")
                return {}

        return {}

    def _parse(
        self,
        raw_data: dict[str, Any],
        origin: str,
        destination: str,
        luggage_type: LuggageType,
        flight_config: FlightConfig,
        search_date: date,
    ) -> list[FlightOffer]:
        """Wandelt die SerpApi-Antwort in FlightOffer-Objekte um."""
        results = raw_data.get("best_flights", []) + raw_data.get("other_flights", [])
        flights: list[FlightOffer] = []

        for result in results:
            try:
                offer = self._parse_one(
                    result, origin, destination, luggage_type, flight_config, search_date
                )
                if offer:
                    flights.append(offer)
            except (KeyError, ValueError, IndexError, TypeError) as e:
                logger.warning(f"[{self.name}] Angebot nicht lesbar: {e}")

        # Sichtbar machen wenn Angebote ankamen, aber alle an Filtern scheitern.
        # Ohne diese Zeile sieht ein Filterproblem wie "keine Flüge verfügbar" aus.
        if results and not flights:
            logger.warning(
                f"[{self.name}] {origin}→{destination}: {len(results)} Angebote von der API, "
                f"aber 0 nach Filtern (Stopps, Abflugzeit, Umsteigezeit) übrig"
            )
        elif results:
            logger.debug(
                f"[{self.name}] {origin}→{destination}: "
                f"{len(flights)} von {len(results)} Angeboten übernommen"
            )

        return flights

    def _parse_one(
        self,
        result: dict[str, Any],
        origin: str,
        destination: str,
        luggage_type: LuggageType,
        flight_config: FlightConfig,
        search_date: date,
    ) -> FlightOffer | None:
        price_total = result.get("price")
        if price_total is None:
            return None

        legs = result.get("flights", [])
        if not legs:
            return None

        segments = self._parse_segments(legs, search_date)
        if not segments:
            return None

        if not self._passes_departure_time_filter(segments, flight_config):
            return None

        layovers = result.get("layovers", [])
        if not self._connection_time_ok(layovers, flight_config.min_connection_time_hours):
            return None

        # Datum aus dem Flug übernehmen, sonst das angefragte Suchdatum
        parsed_date = segments[0].departure_time.date()
        outbound_date = search_date if parsed_date.year < 2000 else parsed_date
        airline = legs[0].get("airline", "")

        from .school_holidays import is_weekend_departure

        return FlightOffer(
            departure_airport=origin,
            destination_airport=destination,
            outbound_date=outbound_date,
            return_date=outbound_date,  # wird vom Aufrufer korrigiert
            price_total=float(price_total),
            price_per_person=float(price_total) / flight_config.total_passengers,
            currency="EUR",
            luggage_type=luggage_type,
            airline=airline,
            stops_outbound=len(layovers),
            stops_return=0,
            duration_outbound_minutes=result.get("total_duration", 0),
            duration_return_minutes=0,
            segments_outbound=segments,
            segments_return=[],
            is_weekend_flight=is_weekend_departure(outbound_date, outbound_date),
            source=self.name,
        )

    def _parse_segments(
        self, legs: list[dict[str, Any]], search_date: date
    ) -> list[FlightSegment]:
        segments: list[FlightSegment] = []
        for leg in legs:
            dep = leg.get("departure_airport", {})
            arr = leg.get("arrival_airport", {})
            segments.append(
                FlightSegment(
                    departure_airport=dep.get("id", "???"),
                    arrival_airport=arr.get("id", "???"),
                    departure_time=_parse_serpapi_datetime(
                        dep.get("time", ""), search_date, dep.get("date", "")
                    ),
                    arrival_time=_parse_serpapi_datetime(
                        arr.get("time", ""), search_date, arr.get("date", "")
                    ),
                    airline=leg.get("airline", ""),
                    flight_number=str(leg.get("flight_number", "")),
                    duration_minutes=leg.get("duration", 0),
                )
            )
        return segments

    def _connection_time_ok(
        self, layovers: list[dict[str, Any]], min_hours: float
    ) -> bool:
        """Prüft ob alle Umsteigezeiten lang genug sind."""
        if not layovers:
            return True
        min_minutes = min_hours * 60
        for layover in layovers:
            if layover.get("duration", 0) < min_minutes:
                logger.debug(
                    f"[{self.name}] Umsteigezeit zu kurz in "
                    f"{layover.get('name', '?')}: {layover.get('duration', 0)}min"
                )
                return False
        return True


def _parse_serpapi_datetime(
    value: str,
    reference_date: date | None = None,
    date_hint: str = "",
) -> datetime:
    """
    Parst SerpApi-Zeitangaben.

    SerpApi liefert im Feld 'time' meist Datum und Uhrzeit ('2026-12-23 08:30'),
    gelegentlich aber nur die Uhrzeit ('08:30'). Eine reine Uhrzeit wird am
    mitgegebenen Datum verankert – sie darf nicht verworfen werden, sonst
    entsteht '00:00' und der Nachtflug-Filter löscht alle Treffer.

    Args:
        value: Der Wert aus dem 'time'-Feld
        reference_date: Suchdatum, an dem eine reine Uhrzeit verankert wird
        date_hint: Optionales separates 'date'-Feld aus der Antwort

    Returns:
        Geparste Zeit, oder UNKNOWN_TIME wenn nichts passt
    """
    if not value:
        return UNKNOWN_TIME

    # Datum und Uhrzeit in einem Feld
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %I:%M %p"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue

    # Separates Datumsfeld mit der Uhrzeit kombinieren
    if date_hint:
        for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %I:%M %p"):
            try:
                return datetime.strptime(f"{date_hint} {value}", fmt)
            except ValueError:
                continue

    # Nur Uhrzeit → am Suchdatum verankern
    for fmt in ("%H:%M", "%I:%M %p"):
        try:
            parsed = datetime.strptime(value, fmt)
        except ValueError:
            continue
        anchor = reference_date or UNKNOWN_TIME.date()
        return datetime.combine(anchor, parsed.time())

    logger.warning(f"[serpapi] Zeitangabe nicht lesbar: {value!r}")
    return UNKNOWN_TIME


# =====================================================================
# Sky Scrapper (RapidAPI / Skyscanner-Daten)
# =====================================================================


class SkyScrapperProvider(FlightProvider):
    """
    Skyscanner-Daten über die Sky-Scrapper-API auf RapidAPI.

    Zweistufig: Flughäfen müssen erst zu skyId/entityId aufgelöst werden.
    Diese IDs sind stabil und werden dauerhaft in einer JSON-Datei gecacht,
    damit pro Flughafen nur eine einzige Auflösung nötig ist.

    HINWEIS: Die Antwortstruktur ist nach der öffentlichen Dokumentation
    umgesetzt. Beim ersten echten Lauf sollte das Parsing verifiziert werden –
    RapidAPI-Anbieter ändern Feldnamen gelegentlich.
    """

    name = "skyscrapper"
    display_name = "Skyscanner"

    AIRPORT_PATH = "/api/v1/flights/searchAirport"
    SEARCH_PATH = "/api/v2/flights/searchFlights"
    REQUEST_DELAY_SECONDS = 1.0
    MAX_RETRIES = 3

    def __init__(self, config: RapidApiConfig, cache_file: str | None = None):
        super().__init__()
        self.config = config
        self.cache_file = cache_file
        self._airport_ids: dict[str, dict[str, str]] = {}
        self._load_airport_cache()

    def is_configured(self) -> bool:
        return self.config.is_configured()

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "x-rapidapi-key": self.config.api_key,
            "x-rapidapi-host": self.config.host,
        }

    @property
    def _base_url(self) -> str:
        host = (self.config.host or "").strip()
        if not host:
            raise ProviderError(
                "Sky Scrapper: Kein Host gesetzt. RAPIDAPI_HOST ist leer – "
                "entweder nicht setzen (dann greift der Standardwert) oder "
                "auf den Host aus dem RapidAPI-Codebeispiel setzen."
            )
        return f"https://{host}"

    # --- Flughafen-IDs ---

    def _load_airport_cache(self) -> None:
        if not self.cache_file:
            return
        path = Path(self.cache_file)
        if not path.exists():
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                self._airport_ids = json.load(f)
            logger.debug(
                f"[{self.name}] {len(self._airport_ids)} Flughafen-IDs aus Cache geladen"
            )
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(f"[{self.name}] Flughafen-Cache nicht lesbar: {e}")

    def _save_airport_cache(self) -> None:
        if not self.cache_file:
            return
        path = Path(self.cache_file)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self._airport_ids, f, indent=2, ensure_ascii=False)
        except OSError as e:
            logger.warning(f"[{self.name}] Flughafen-Cache nicht schreibbar: {e}")

    def _resolve_airport(self, iata: str) -> dict[str, str] | None:
        """
        Löst einen IATA-Code zu skyId und entityId auf.
        Ergebnisse werden gecacht, da sie sich praktisch nie ändern.

        Raises:
            ProviderError: Die Anfrage selbst scheiterte (falscher Host,
                Netzwerkfehler, unlesbare Antwort). Solche Fehler wiederholen
                sich bei jedem Flughafen, deshalb wird der Provider dadurch
                stillgelegt statt hunderte Male dasselbe zu versuchen.
            QuotaExceededError: Kontingent erschöpft.
        """
        if iata in self._airport_ids:
            return self._airport_ids[iata]

        self._rate_limit(self.REQUEST_DELAY_SECONDS)
        try:
            response = requests.get(
                f"{self._base_url}{self.AIRPORT_PATH}",
                headers=self._headers,
                params={"query": iata, "locale": "de-DE"},
                timeout=30,
            )
            self.calls_made += 1
            self._raise_for_quota(response)
            response.raise_for_status()
            payload = response.json()
        except (QuotaExceededError, ProviderError):
            raise
        except (requests.RequestException, ValueError) as e:
            raise ProviderError(
                f"Sky Scrapper: Flughafen-Auflösung für {iata} fehlgeschlagen: {e}"
            ) from e

        entries = payload.get("data") or []
        if not entries:
            logger.error(
                f"[{self.name}] Leere Antwort bei Auflösung von {iata}. "
                f"Antwort-Schlüssel: {sorted(payload.keys())}"
            )
            return None

        candidates = [self._extract_place(entry) for entry in entries]
        candidates = [c for c in candidates if c]

        if not candidates:
            logger.error(f"[{self.name}] Keine IDs für Flughafen {iata} gefunden")
            return None

        # Genau diesen Flughafen bevorzugen. Die API liefert Städte zuerst,
        # und eine Stadt schließt andere Flughäfen ein – bei Teheran etwa den
        # Inlandsflughafen. Wir wollen den angefragten IATA-Code.
        exact = [
            c for c in candidates
            if c["entityType"] == "AIRPORT" and c["skyId"].upper() == iata.upper()
        ]
        any_airport = [c for c in candidates if c["entityType"] == "AIRPORT"]
        chosen = (exact or any_airport or candidates)[0]

        if not exact:
            logger.warning(
                f"[{self.name}] Kein exakter Flughafen-Treffer für {iata}, "
                f"nutze {chosen['skyId']} ({chosen['entityType']}). "
                f"Alternativen: {[(c['skyId'], c['entityType']) for c in candidates[:5]]}"
            )

        resolved = {"skyId": chosen["skyId"], "entityId": chosen["entityId"]}
        self._airport_ids[iata] = resolved
        self._save_airport_cache()
        logger.info(
            f"[{self.name}] {iata} aufgelöst: {resolved} ({chosen['entityType']})"
        )
        return resolved

    @staticmethod
    def _extract_place(entry: dict[str, Any]) -> dict[str, str] | None:
        """Holt skyId, entityId und Typ aus einem Ort-Eintrag der Antwort."""
        nav = entry.get("navigation") or {}
        params = nav.get("relevantFlightParams") or {}

        sky_id = params.get("skyId") or entry.get("skyId")
        entity_id = params.get("entityId") or nav.get("entityId") or entry.get("entityId")
        entity_type = (
            params.get("flightPlaceType")
            or nav.get("entityType")
            or ""
        )

        if not sky_id or not entity_id:
            return None

        return {
            "skyId": str(sky_id),
            "entityId": str(entity_id),
            "entityType": str(entity_type).upper(),
        }

    # --- Suche ---

    def search(
        self,
        origin: str,
        destination: str,
        outbound_date: date,
        return_date: date,
        flight_config: FlightConfig,
        luggage_type: LuggageType = LuggageType.WITH_LUGGAGE,
    ) -> list[FlightOffer]:
        origin_ids = self._resolve_airport(origin)
        dest_ids = self._resolve_airport(destination)
        if not origin_ids or not dest_ids:
            return []

        params = {
            "originSkyId": origin_ids["skyId"],
            "destinationSkyId": dest_ids["skyId"],
            "originEntityId": origin_ids["entityId"],
            "destinationEntityId": dest_ids["entityId"],
            "date": outbound_date.isoformat(),
            "returnDate": return_date.isoformat(),
            "cabinClass": "economy",
            "adults": flight_config.adults,
            "childrens": flight_config.num_children,
            # "best" ist der neutrale Standardwert. Zuvor stand hier
            # "price_high" – das hätte die teuersten Flüge zuerst geliefert.
            "sortBy": "best",
            "currency": "EUR",
            "market": "de-DE",
            "countryCode": "DE",
            "limit": 15,
        }

        raw = self._request(params, origin, destination)
        if not raw:
            return []

        return self._parse(raw, origin, destination, return_date, luggage_type, flight_config)

    def _request(
        self, params: dict[str, Any], origin: str, destination: str
    ) -> dict[str, Any]:
        self._rate_limit(self.REQUEST_DELAY_SECONDS)

        for attempt in range(self.MAX_RETRIES):
            try:
                logger.debug(f"[{self.name}] {origin}→{destination}")
                response = requests.get(
                    f"{self._base_url}{self.SEARCH_PATH}",
                    headers=self._headers,
                    params=params,
                    timeout=60,
                )
                self.calls_made += 1
                self._raise_for_quota(response)

                if response.status_code == 401:
                    raise ProviderError("Sky Scrapper: RapidAPI-Key ungültig (401)")

                response.raise_for_status()
                data = response.json()

                itineraries = (data.get("data") or {}).get("itineraries") or []
                logger.info(f"[{self.name}] {origin}→{destination}: {len(itineraries)} Angebote")

                if not itineraries:
                    self._log_empty_response(data, origin, destination)

                return data

            except QuotaExceededError:
                raise
            except requests.Timeout:
                if attempt < self.MAX_RETRIES - 1:
                    wait = (2 ** attempt) * 3
                    logger.warning(
                        f"[{self.name}] Timeout, warte {wait}s "
                        f"(Versuch {attempt + 1}/{self.MAX_RETRIES})"
                    )
                    time.sleep(wait)
                    continue
                logger.error(f"[{self.name}] Timeout nach {self.MAX_RETRIES} Versuchen")
                return {}
            except (requests.RequestException, ValueError) as e:
                logger.error(f"[{self.name}] Fehler bei {origin}→{destination}: {e}")
                return {}

        return {}

    def _log_empty_response(
        self, data: dict[str, Any], origin: str, destination: str
    ) -> None:
        """
        Protokolliert die Struktur einer Antwort ohne Treffer.

        Ohne diese Ausgabe lässt sich nicht unterscheiden, ob die API
        tatsächlich keine Flüge kennt, ob sie einen Fehler im Rumpf meldet,
        oder ob die Ergebnisse an einer anderen Stelle im JSON stehen als
        erwartet. Jeder Testlauf kostet Kontingent, also muss ein einzelner
        Lauf die Antwort erklären.
        """
        prefix = f"[{self.name}] {origin}→{destination} ohne Treffer"

        logger.warning(f"{prefix} – Antwort-Schlüssel: {sorted(data.keys())}")

        for key in ("status", "message", "error", "errors", "timestamp"):
            if key in data:
                logger.warning(f"{prefix} – {key}: {str(data[key])[:300]}")

        payload = data.get("data")
        if isinstance(payload, dict):
            logger.warning(f"{prefix} – data-Schlüssel: {sorted(payload.keys())}")
            context = payload.get("context")
            if isinstance(context, dict):
                logger.warning(f"{prefix} – context: {str(context)[:300]}")
            # Manche Varianten liefern die Ergebnisse unter anderem Namen
            for alt in ("itineraries", "results", "flights", "legs", "buckets"):
                value = payload.get(alt)
                if isinstance(value, list):
                    logger.warning(f"{prefix} – data.{alt}: {len(value)} Einträge")
        elif isinstance(payload, list):
            logger.warning(f"{prefix} – data ist eine Liste mit {len(payload)} Einträgen")
        else:
            logger.warning(f"{prefix} – data-Typ: {type(payload).__name__}")

        logger.debug(f"{prefix} – Rohantwort (gekürzt): {str(data)[:1500]}")

    def _raise_for_quota(self, response: requests.Response) -> None:
        """
        Prüft die Antwort auf Kontingent- und Zugangsprobleme.

        Wichtig ist die Unterscheidung: ein fehlendes Abo ist ein
        Einrichtungsfehler den man beheben kann, ein erschöpftes Kontingent
        dagegen eine Frage der Zeit. Beides braucht andere Hinweise.
        """
        if response.status_code == 429:
            raise QuotaExceededError(
                "Sky Scrapper: RapidAPI-Kontingent erschöpft (429)"
            )

        if response.status_code == 403:
            body = (response.text or "").lower()
            if "not subscribed" in body:
                raise ProviderError(
                    "Sky Scrapper: Der RapidAPI-Key ist für diese API nicht freigeschaltet. "
                    "Auf rapidapi.com die Sky-Scrapper-API öffnen und dort den kostenlosen "
                    "Plan abonnieren – ein Key allein genügt nicht."
                )
            if "quota" in body:
                raise QuotaExceededError(
                    f"Sky Scrapper: Kontingent erschöpft – {response.text[:200]}"
                )
            raise ProviderError(f"Sky Scrapper: Zugriff verweigert – {response.text[:200]}")

    def _parse(
        self,
        raw_data: dict[str, Any],
        origin: str,
        destination: str,
        return_date: date,
        luggage_type: LuggageType,
        flight_config: FlightConfig,
    ) -> list[FlightOffer]:
        itineraries = (raw_data.get("data") or {}).get("itineraries") or []
        flights: list[FlightOffer] = []

        for itinerary in itineraries:
            try:
                offer = self._parse_one(
                    itinerary, origin, destination, return_date, luggage_type, flight_config
                )
                if offer:
                    flights.append(offer)
            except (KeyError, ValueError, IndexError, TypeError) as e:
                logger.warning(f"[{self.name}] Angebot nicht lesbar: {e}")

        if itineraries and not flights:
            logger.warning(
                f"[{self.name}] {origin}→{destination}: {len(itineraries)} Angebote von der API, "
                f"aber 0 nach Filtern übrig"
            )
        elif itineraries:
            logger.debug(
                f"[{self.name}] {origin}→{destination}: "
                f"{len(flights)} von {len(itineraries)} Angeboten übernommen"
            )

        return flights

    def _parse_one(
        self,
        itinerary: dict[str, Any],
        origin: str,
        destination: str,
        return_date: date,
        luggage_type: LuggageType,
        flight_config: FlightConfig,
    ) -> FlightOffer | None:
        price_raw = (itinerary.get("price") or {}).get("raw")
        if price_raw is None:
            return None

        legs = itinerary.get("legs") or []
        if not legs:
            return None

        outbound_leg = legs[0]
        return_leg = legs[1] if len(legs) > 1 else None

        segments_out = self._parse_leg_segments(outbound_leg)
        segments_ret = self._parse_leg_segments(return_leg) if return_leg else []

        if not segments_out:
            return None

        if not self._passes_departure_time_filter(segments_out, flight_config):
            return None

        outbound_date = segments_out[0].departure_time.date()
        actual_return = return_date
        if segments_ret:
            actual_return = segments_ret[0].departure_time.date()

        airline = self._extract_airline(outbound_leg)

        from .school_holidays import is_weekend_departure

        return FlightOffer(
            departure_airport=origin,
            destination_airport=destination,
            outbound_date=outbound_date,
            return_date=actual_return,
            price_total=float(price_raw),
            price_per_person=float(price_raw) / flight_config.total_passengers,
            currency="EUR",
            luggage_type=luggage_type,
            airline=airline,
            stops_outbound=int(outbound_leg.get("stopCount", 0) or 0),
            stops_return=int(return_leg.get("stopCount", 0) or 0) if return_leg else 0,
            duration_outbound_minutes=int(outbound_leg.get("durationInMinutes", 0) or 0),
            duration_return_minutes=int(return_leg.get("durationInMinutes", 0) or 0) if return_leg else 0,
            segments_outbound=segments_out,
            segments_return=segments_ret,
            is_weekend_flight=is_weekend_departure(outbound_date, actual_return),
            source=self.name,
        )

    def _extract_airline(self, leg: dict[str, Any]) -> str:
        carriers = (leg.get("carriers") or {}).get("marketing") or []
        if carriers:
            return carriers[0].get("name", "") or carriers[0].get("alternateId", "")
        return ""

    def _parse_leg_segments(self, leg: dict[str, Any] | None) -> list[FlightSegment]:
        if not leg:
            return []

        segments: list[FlightSegment] = []
        raw_segments = leg.get("segments") or []

        for seg in raw_segments:
            dep_time = _parse_iso_datetime(seg.get("departure", ""))
            arr_time = _parse_iso_datetime(seg.get("arrival", ""))
            origin_info = seg.get("origin") or {}
            dest_info = seg.get("destination") or {}
            carrier = seg.get("marketingCarrier") or {}

            segments.append(
                FlightSegment(
                    departure_airport=_airport_code(origin_info),
                    arrival_airport=_airport_code(dest_info),
                    departure_time=dep_time,
                    arrival_time=arr_time,
                    airline=carrier.get("name", ""),
                    flight_number=str(seg.get("flightNumber", "")),
                    duration_minutes=int(seg.get("durationInMinutes", 0) or 0),
                )
            )

        # Fallback: manche Antworten enthalten keine segments, nur Leg-Daten
        if not segments:
            dep_time = _parse_iso_datetime(leg.get("departure", ""))
            arr_time = _parse_iso_datetime(leg.get("arrival", ""))
            segments.append(
                FlightSegment(
                    departure_airport=_airport_code(leg.get("origin") or {}),
                    arrival_airport=_airport_code(leg.get("destination") or {}),
                    departure_time=dep_time,
                    arrival_time=arr_time,
                    airline=_first_carrier_name(leg),
                    flight_number="",
                    duration_minutes=int(leg.get("durationInMinutes", 0) or 0),
                )
            )

        return segments


def _airport_code(info: dict[str, Any]) -> str:
    """Holt den IATA-Code aus einem Sky-Scrapper Ort-Objekt."""
    code = (
        info.get("displayCode")
        or info.get("flightPlaceId")
        or info.get("id")
        or "???"
    )
    code = str(code)[:3].upper()
    return code if len(code) == 3 else "???"


def _first_carrier_name(leg: dict[str, Any]) -> str:
    carriers = (leg.get("carriers") or {}).get("marketing") or []
    return carriers[0].get("name", "") if carriers else ""


def _parse_iso_datetime(value: str) -> datetime:
    """
    Parst ISO-Zeitangaben wie '2026-12-23T08:30:00'.

    Gibt bei Misserfolg UNKNOWN_TIME zurück und protokolliert das.
    """
    if not value:
        return UNKNOWN_TIME
    cleaned = value.replace("Z", "")
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(cleaned, fmt)
        except ValueError:
            continue
    logger.warning(f"[skyscrapper] Zeitangabe nicht lesbar: {value!r}")
    return UNKNOWN_TIME


# =====================================================================
# Factory
# =====================================================================


def build_providers(
    provider_names: list[str],
    serpapi_config: SerpApiConfig,
    rapidapi_config: RapidApiConfig,
    airport_cache_file: str | None = None,
) -> list[FlightProvider]:
    """
    Erzeugt die Provider-Kette in der gewünschten Reihenfolge.
    Nicht konfigurierte Dienste werden übersprungen.
    """
    providers: list[FlightProvider] = []

    for name in provider_names:
        if name == "serpapi":
            provider: FlightProvider = SerpApiProvider(serpapi_config)
        elif name == "skyscrapper":
            provider = SkyScrapperProvider(rapidapi_config, cache_file=airport_cache_file)
        else:
            logger.warning(f"Unbekannter Provider übersprungen: {name}")
            continue

        if not provider.is_configured():
            logger.info(f"Provider '{name}' übersprungen (kein API-Key)")
            continue

        providers.append(provider)

    return providers
