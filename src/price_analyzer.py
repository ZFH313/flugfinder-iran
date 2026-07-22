"""
Preisanalyse und Trend-Erkennung.
Speichert Preisverlauf, vergleicht mit historischen Daten,
erkennt "sehr günstige" Angebote und erstellt Trend-Graphen.
"""

import json
import logging
from datetime import date, datetime
from pathlib import Path
from statistics import mean, stdev

import matplotlib
matplotlib.use("Agg")  # Kein Display nötig (Server/CI)
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

from .config import FlightConfig, PathConfig
from .models import (
    FlightOffer,
    LuggageType,
    PriceAnalysis,
    PriceHistoryEntry,
    PriceTrend,
)

logger = logging.getLogger(__name__)


def load_price_history(history_file: str) -> list[PriceHistoryEntry]:
    """Lädt den gespeicherten Preisverlauf aus JSON."""
    file_path = Path(history_file)

    if not file_path.exists():
        logger.info("Keine Preisverlauf-Datei gefunden. Starte mit leerer History.")
        return []

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        entries = [PriceHistoryEntry(**entry) for entry in data]
        logger.info(f"Preisverlauf geladen: {len(entries)} Einträge")
        return entries

    except (json.JSONDecodeError, IOError, ValueError) as e:
        logger.error(f"Fehler beim Laden des Preisverlaufs: {e}")
        return []


def save_price_history(entries: list[PriceHistoryEntry], history_file: str) -> None:
    """Speichert den Preisverlauf in JSON."""
    file_path = Path(history_file)
    file_path.parent.mkdir(parents=True, exist_ok=True)

    data = [
        {
            "search_date": e.search_date.isoformat(),
            "route": e.route,
            "price_with_luggage": e.price_with_luggage,
            "price_without_luggage": e.price_without_luggage,
            "cheapest_airline": e.cheapest_airline,
        }
        for e in entries
    ]

    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    logger.info(f"Preisverlauf gespeichert: {len(entries)} Einträge")


def add_to_history(
    flights: list[FlightOffer],
    history: list[PriceHistoryEntry],
) -> list[PriceHistoryEntry]:
    """
    Fügt die heutigen Suchergebnisse zum Preisverlauf hinzu.
    Pro Route wird der günstigste Preis (mit/ohne Gepäck) gespeichert.
    """
    today = date.today()

    # Gruppiere nach Route
    routes: dict[str, list[FlightOffer]] = {}
    for flight in flights:
        route_key = f"{flight.departure_airport}-{flight.destination_airport}"
        if route_key not in routes:
            routes[route_key] = []
        routes[route_key].append(flight)

    # Pro Route den günstigsten Preis speichern
    new_entries = []
    for route, route_flights in routes.items():
        # Günstigster mit Gepäck
        with_luggage = [f for f in route_flights if f.luggage_type == LuggageType.WITH_LUGGAGE]
        price_with = min((f.price_total for f in with_luggage), default=None) if with_luggage else None

        # Günstigster ohne Gepäck
        without_luggage = [f for f in route_flights if f.luggage_type == LuggageType.WITHOUT_LUGGAGE]
        price_without = min((f.price_total for f in without_luggage), default=None) if without_luggage else None

        # Günstigste Airline
        cheapest = min(route_flights, key=lambda f: f.price_total) if route_flights else None
        airline = cheapest.airline if cheapest else ""

        entry = PriceHistoryEntry(
            search_date=today,
            route=route,
            price_with_luggage=price_with,
            price_without_luggage=price_without,
            cheapest_airline=airline,
        )
        new_entries.append(entry)

    # Zur History hinzufügen
    history.extend(new_entries)

    logger.info(f"{len(new_entries)} neue Preis-Einträge hinzugefügt (Gesamt: {len(history)})")
    return history


def analyze_prices(
    flights: list[FlightOffer],
    history: list[PriceHistoryEntry],
    cheap_threshold_percent: float = 20.0,
) -> list[PriceAnalysis]:
    """
    Analysiert die aktuellen Preise im Vergleich zum historischen Durchschnitt.

    Args:
        flights: Aktuelle Suchergebnisse
        history: Historische Preisdaten
        cheap_threshold_percent: Ab wieviel % unter Durchschnitt = "sehr günstig"

    Returns:
        Liste der Preisanalysen pro Route
    """
    analyses = []

    # Gruppiere aktuelle Flüge nach Route
    routes: dict[str, list[FlightOffer]] = {}
    for flight in flights:
        route_key = f"{flight.departure_airport}-{flight.destination_airport}"
        if route_key not in routes:
            routes[route_key] = []
        routes[route_key].append(flight)

    for route, route_flights in routes.items():
        # Aktueller günstigster Preis
        current_price = min(f.price_total for f in route_flights)

        # Historische Preise für diese Route
        route_history = [
            e for e in history
            if e.route == route and e.price_with_luggage is not None
        ]

        if len(route_history) < 2:
            # Nicht genug Daten für Analyse
            analysis = PriceAnalysis(
                route=route,
                current_price=current_price,
                average_price=current_price,
                min_price_historical=current_price,
                max_price_historical=current_price,
                trend=PriceTrend.UNKNOWN,
                percent_vs_average=0.0,
                is_very_cheap=False,
                data_points=len(route_history),
            )
            analyses.append(analysis)
            continue

        # Historische Preis-Werte
        historical_prices = [
            e.price_with_luggage for e in route_history
            if e.price_with_luggage is not None
        ]

        if not historical_prices:
            continue

        avg_price = mean(historical_prices)
        min_price = min(historical_prices)
        max_price = max(historical_prices)

        # Prozentuale Abweichung vom Durchschnitt
        percent_diff = ((current_price - avg_price) / avg_price) * 100

        # Ist es "sehr günstig"?
        is_cheap = percent_diff <= -cheap_threshold_percent

        # Trend berechnen (letzte 7 Einträge)
        trend = _calculate_trend(route_history)

        analysis = PriceAnalysis(
            route=route,
            current_price=current_price,
            average_price=round(avg_price, 2),
            min_price_historical=min_price,
            max_price_historical=max_price,
            trend=trend,
            percent_vs_average=round(percent_diff, 1),
            is_very_cheap=is_cheap,
            data_points=len(route_history),
        )
        analyses.append(analysis)

        if is_cheap:
            logger.info(
                f"🚨 GÜNSTIG: {route} bei {current_price}€ "
                f"({percent_diff:.1f}% unter Durchschnitt {avg_price:.0f}€)"
            )

    return analyses


def mark_cheap_flights(
    flights: list[FlightOffer],
    analyses: list[PriceAnalysis],
    price_limit: int,
) -> list[FlightOffer]:
    """
    Markiert Flüge als "sehr günstig" basierend auf der Analyse
    und prüft das Preislimit.
    """
    analysis_map = {a.route: a for a in analyses}

    for flight in flights:
        route_key = f"{flight.departure_airport}-{flight.destination_airport}"
        analysis = analysis_map.get(route_key)

        if analysis and analysis.is_very_cheap:
            flight.is_very_cheap = True
            flight.savings_percent = abs(analysis.percent_vs_average)

        # Zusätzlich: unter Preislimit ist auch "günstig"
        if flight.price_total <= price_limit:
            flight.is_very_cheap = True

    return flights


def _calculate_trend(history: list[PriceHistoryEntry]) -> PriceTrend:
    """
    Berechnet den Preis-Trend basierend auf den letzten Einträgen.
    Vergleicht die letzten 3 Einträge mit den 3 davor.
    """
    if len(history) < 6:
        return PriceTrend.UNKNOWN

    # Sortiere nach Datum
    sorted_history = sorted(history, key=lambda e: e.search_date)

    # Letzte 3 vs. vorherige 3
    recent = sorted_history[-3:]
    previous = sorted_history[-6:-3]

    recent_prices = [
        e.price_with_luggage for e in recent if e.price_with_luggage is not None
    ]
    previous_prices = [
        e.price_with_luggage for e in previous if e.price_with_luggage is not None
    ]

    if not recent_prices or not previous_prices:
        return PriceTrend.UNKNOWN

    recent_avg = mean(recent_prices)
    previous_avg = mean(previous_prices)

    # Signifikante Änderung: >5%
    change_percent = ((recent_avg - previous_avg) / previous_avg) * 100

    if change_percent > 5:
        return PriceTrend.RISING
    elif change_percent < -5:
        return PriceTrend.FALLING
    else:
        return PriceTrend.STABLE


def create_price_trend_graph(
    history: list[PriceHistoryEntry],
    output_path: str,
    routes: list[str] | None = None,
) -> str | None:
    """
    Erstellt einen Preis-Trend-Graphen als PNG-Bild.

    Args:
        history: Preisverlauf
        output_path: Pfad für das Ausgabe-Bild
        routes: Welche Routen anzeigen (None = alle)

    Returns:
        Pfad zum erstellten Bild oder None bei Fehler
    """
    if len(history) < 2:
        logger.info("Nicht genug Daten für Trend-Graph (min. 2 Einträge)")
        return None

    # Daten gruppieren nach Route
    route_data: dict[str, list[tuple[date, float]]] = {}

    for entry in history:
        if routes and entry.route not in routes:
            continue
        if entry.price_with_luggage is None:
            continue

        if entry.route not in route_data:
            route_data[entry.route] = []
        route_data[entry.route].append((entry.search_date, entry.price_with_luggage))

    if not route_data:
        logger.info("Keine Daten für Graph verfügbar")
        return None

    # Graph erstellen
    fig, ax = plt.subplots(figsize=(12, 6))

    colors = ["#2196F3", "#4CAF50", "#FF9800", "#E91E63", "#9C27B0", "#00BCD4", "#FF5722", "#607D8B"]

    for i, (route, data_points) in enumerate(sorted(route_data.items())):
        # Sortiere nach Datum
        data_points.sort(key=lambda x: x[0])
        dates = [d[0] for d in data_points]
        prices = [d[1] for d in data_points]

        color = colors[i % len(colors)]
        ax.plot(dates, prices, marker="o", label=route, color=color, linewidth=2, markersize=4)

    # Styling
    ax.set_xlabel("Datum", fontsize=11)
    ax.set_ylabel("Preis (€, 4 Personen)", fontsize=11)
    ax.set_title("FlugFinder Iran – Preisverlauf", fontsize=14, fontweight="bold")
    ax.legend(loc="upper right", fontsize=9)
    ax.grid(True, alpha=0.3)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d.%m"))
    ax.xaxis.set_major_locator(mdates.WeekdayLocator(interval=1))
    fig.autofmt_xdate()

    # Preislimit-Linie
    ax.axhline(y=1500, color="red", linestyle="--", alpha=0.5, label="Preislimit 1.500€")

    plt.tight_layout()

    # Speichern
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(output, dpi=150, bbox_inches="tight")
    plt.close()

    logger.info(f"Trend-Graph erstellt: {output_path}")
    return str(output)
