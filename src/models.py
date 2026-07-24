"""
Pydantic Datenmodelle für FlugFinder Iran.
Definiert die Struktur aller Daten die durch die App fließen.
"""

from datetime import date, datetime
from enum import Enum
from pydantic import BaseModel, Field, field_validator


class LuggageType(str, Enum):
    """Gepäck-Variante."""
    WITH_LUGGAGE = "with_luggage"
    WITHOUT_LUGGAGE = "without_luggage"


class PriceTrend(str, Enum):
    """Preis-Trend-Richtung."""
    RISING = "rising"
    FALLING = "falling"
    STABLE = "stable"
    UNKNOWN = "unknown"


class PredictionAdvice(str, Enum):
    """Buchungsempfehlung basierend auf Vorhersage."""
    BOOK_NOW = "book_now"
    WAIT = "wait"
    UNCERTAIN = "uncertain"


# --- Flug-Ergebnisse ---


class FlightSegment(BaseModel):
    """Ein einzelner Flugabschnitt (Teilstrecke)."""
    departure_airport: str = Field(..., min_length=3, max_length=3, description="IATA-Code Abflug")
    arrival_airport: str = Field(..., min_length=3, max_length=3, description="IATA-Code Ankunft")
    departure_time: datetime = Field(..., description="Abflugzeit")
    arrival_time: datetime = Field(..., description="Ankunftszeit")
    airline: str = Field(..., description="Airline Name oder Code")
    flight_number: str = Field(default="", description="Flugnummer")
    duration_minutes: int = Field(..., ge=0, description="Flugdauer in Minuten")


class FlightOffer(BaseModel):
    """Ein komplettes Flugangebot (Hin + Rück)."""
    # Routen-Info
    departure_airport: str = Field(..., min_length=3, max_length=3)
    destination_airport: str = Field(..., min_length=3, max_length=3)
    outbound_date: date = Field(..., description="Hinflug-Datum")
    return_date: date = Field(..., description="Rückflug-Datum")

    # Preis
    price_total: float = Field(..., ge=0, description="Gesamtpreis für alle Personen in €")
    price_per_person: float = Field(..., ge=0, description="Preis pro Person in €")
    currency: str = Field(default="EUR")
    luggage_type: LuggageType = Field(..., description="Mit oder ohne Gepäck")

    # Flug-Details
    airline: str = Field(..., description="Hauptairline")
    stops_outbound: int = Field(default=0, ge=0, description="Zwischenstopps Hinflug")
    stops_return: int = Field(default=0, ge=0, description="Zwischenstopps Rückflug")
    duration_outbound_minutes: int = Field(..., ge=0, description="Gesamtdauer Hinflug")
    duration_return_minutes: int = Field(..., ge=0, description="Gesamtdauer Rückflug")

    # Segmente (Detail-Info)
    segments_outbound: list[FlightSegment] = Field(default_factory=list)
    segments_return: list[FlightSegment] = Field(default_factory=list)

    # Bewertung
    is_very_cheap: bool = Field(default=False, description="Deutlich unter Durchschnitt")
    savings_percent: float = Field(default=0.0, description="Ersparnis in % zum Durchschnitt")
    is_weekend_flight: bool = Field(default=False, description="Hinflug Fr/Sa, Rückflug So")
    booking_link: str = Field(default="", description="Link zur Buchung (wenn verfügbar)")

    @property
    def total_stops(self) -> int:
        """Gesamtzahl der Stopps (Hin + Rück)."""
        return self.stops_outbound + self.stops_return

    @property
    def duration_total_hours(self) -> float:
        """Gesamtreisezeit in Stunden."""
        return (self.duration_outbound_minutes + self.duration_return_minutes) / 60

    @field_validator("outbound_date", "return_date", mode="before")
    @classmethod
    def parse_date(cls, v):
        """Akzeptiert sowohl date-Objekte als auch Strings."""
        if isinstance(v, str):
            return date.fromisoformat(v)
        return v


class ComboTicket(BaseModel):
    """Kombi-Ticket: unterschiedlicher Hin-/Rückflughafen."""
    departure_airport: str = Field(..., description="Abflughafen Hinflug")
    return_airport: str = Field(..., description="Ankunftshafen Rückflug (anders als Abflug)")
    destination_airport: str = Field(..., description="Zielflughafen")
    outbound_date: date
    return_date: date
    price_total: float = Field(..., ge=0)
    price_regular: float = Field(..., ge=0, description="Normaler Preis (gleicher Flughafen)")
    savings: float = Field(..., description="Ersparnis durch Kombi in €")
    airline_outbound: str
    airline_return: str
    luggage_type: LuggageType


# --- Preis-Analyse ---


class PriceHistoryEntry(BaseModel):
    """Ein Eintrag im Preisverlauf."""
    search_date: date = Field(..., description="Datum der Suche")
    route: str = Field(..., description="Route z.B. 'HAJ-IKA'")
    price_with_luggage: float | None = Field(default=None)
    price_without_luggage: float | None = Field(default=None)
    cheapest_airline: str = Field(default="")


class PriceAnalysis(BaseModel):
    """Ergebnis der Preisanalyse für eine Route."""
    route: str = Field(..., description="Route z.B. 'HAJ-IKA'")
    current_price: float = Field(..., ge=0)
    average_price: float = Field(..., ge=0)
    min_price_historical: float = Field(..., ge=0)
    max_price_historical: float = Field(..., ge=0)
    trend: PriceTrend = Field(default=PriceTrend.UNKNOWN)
    percent_vs_average: float = Field(default=0.0, description="% Differenz zum Durchschnitt")
    is_very_cheap: bool = Field(default=False)
    data_points: int = Field(default=0, description="Anzahl historischer Datenpunkte")


class PricePrediction(BaseModel):
    """Preis-Vorhersage basierend auf historischen Daten."""
    route: str
    prediction_date: date = Field(..., description="Für welches Datum vorhergesagt")
    predicted_price: float = Field(..., ge=0)
    confidence: float = Field(default=0.0, ge=0, le=1.0, description="Konfidenz 0-1")
    advice: PredictionAdvice = Field(default=PredictionAdvice.UNCERTAIN)
    reason: str = Field(default="", description="Begründung der Empfehlung")


# --- Such-Ergebnis (komplett) ---


class SearchResult(BaseModel):
    """Komplettes Suchergebnis eines Durchlaufs."""
    search_date: datetime = Field(default_factory=datetime.now)
    holiday_period: str = Field(default="", description="Welche Ferienperiode")
    holiday_start: date | None = Field(default=None)
    holiday_end: date | None = Field(default=None)

    # Alle Flüge sortiert nach Preis
    flights: list[FlightOffer] = Field(default_factory=list)

    # Kombi-Tickets (nur wenn günstiger)
    combo_tickets: list[ComboTicket] = Field(default_factory=list)

    # Preis-Analyse pro Route
    price_analyses: list[PriceAnalysis] = Field(default_factory=list)

    # Vorhersagen
    predictions: list[PricePrediction] = Field(default_factory=list)

    # Meta-Info
    total_searches: int = Field(default=0, description="Anzahl API-Anfragen")
    errors: list[str] = Field(default_factory=list, description="Fehler während der Suche")
    duration_seconds: float = Field(default=0.0, description="Gesamtdauer der Suche")

    @property
    def cheapest_flight(self) -> FlightOffer | None:
        """Günstigster Flug gesamt."""
        if not self.flights:
            return None
        return min(self.flights, key=lambda f: f.price_total)

    @property
    def cheapest_with_luggage(self) -> FlightOffer | None:
        """Günstigster Flug mit Gepäck."""
        with_luggage = [f for f in self.flights if f.luggage_type == LuggageType.WITH_LUGGAGE]
        if not with_luggage:
            return None
        return min(with_luggage, key=lambda f: f.price_total)

    @property
    def cheapest_without_luggage(self) -> FlightOffer | None:
        """Günstigster Flug ohne Gepäck."""
        without_luggage = [f for f in self.flights if f.luggage_type == LuggageType.WITHOUT_LUGGAGE]
        if not without_luggage:
            return None
        return min(without_luggage, key=lambda f: f.price_total)

    @property
    def has_alert(self) -> bool:
        """Gibt es einen Günstig-Alarm?"""
        return any(f.is_very_cheap for f in self.flights)

    def get_flights_by_airport(self, airport: str) -> list[FlightOffer]:
        """Alle Flüge ab einem bestimmten Flughafen."""
        return [f for f in self.flights if f.departure_airport == airport]

    def get_matrix(self) -> dict[str, dict[str, FlightOffer | None]]:
        """
        Multi-Datum-Matrix: Airport → Datum → günstigstes Angebot.
        Nützlich für die Übersichts-Tabelle.
        """
        matrix: dict[str, dict[str, FlightOffer | None]] = {}
        for flight in self.flights:
            airport = flight.departure_airport
            date_key = flight.outbound_date.isoformat()
            if airport not in matrix:
                matrix[airport] = {}
            existing = matrix[airport].get(date_key)
            if existing is None or flight.price_total < existing.price_total:
                matrix[airport][date_key] = flight
        return matrix


# --- Schulferien ---


class HolidayPeriod(BaseModel):
    """Eine Ferienperiode."""
    name: str = Field(..., description="Name z.B. 'Sommerferien 2026'")
    start: date = Field(..., description="Erster Ferientag")
    end: date = Field(..., description="Letzter Ferientag")
    state: str = Field(default="Niedersachsen")

    @property
    def duration_days(self) -> int:
        """Dauer der Ferien in Tagen."""
        return (self.end - self.start).days + 1

    def is_upcoming(self, reference_date: date | None = None) -> bool:
        """Prüft ob diese Ferien in der Zukunft liegen."""
        ref = reference_date or date.today()
        return self.start > ref
