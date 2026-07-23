"""
FlugFinder Iran – Hauptprogramm.
Orchestriert die gesamte Pipeline:
Config → Ferien → Flugsuche → Preisanalyse → Vorhersage → Benachrichtigung → Frontend-Daten
"""

import argparse
import json
import logging
import sys
import time
from datetime import date, datetime
from pathlib import Path

from .combo_search import search_combo_tickets
from .config import AppConfig, load_config
from .flight_search import SerpApiClient, search_all_routes
from .models import LuggageType, SearchResult
from .notifier import (
    TelegramNotifier,
    send_cheap_alert,
    send_daily_summary,
    send_price_graph,
)
from .price_analyzer import (
    add_to_history,
    analyze_prices,
    create_price_trend_graph,
    load_price_history,
    mark_cheap_flights,
    save_price_history,
)
from .price_predictor import predict_all_routes
from .school_holidays import (
    calculate_travel_dates,
    get_next_holiday,
    load_holidays,
)

# Logging konfigurieren
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def run_search(config: AppConfig, target_dates: list[tuple[date, date]] | None = None) -> SearchResult:
    """
    Führt die komplette Flugsuche durch.

    Args:
        config: App-Konfiguration
        target_dates: Optionale manuelle Reisedaten. Wenn None, werden Schulferien genutzt.

    Returns:
        Komplettes Suchergebnis
    """
    start_time = time.time()
    result = SearchResult(search_date=datetime.now())

    # --- 1. Reisedaten bestimmen ---
    if target_dates:
        travel_dates = target_dates
        result.holiday_period = "Manuelle Suche"
        logger.info(f"Manuelle Suche mit {len(travel_dates)} Datums-Kombinationen")
    else:
        # Schulferien laden – ALLE 4 nächsten Ferienzeiten suchen
        holidays = load_holidays(config.paths.holidays_file)
        from .school_holidays import get_all_upcoming_holidays
        upcoming = get_all_upcoming_holidays(holidays, min_duration_days=3)

        # Maximal die nächsten 4 Ferienperioden
        upcoming = upcoming[:4]

        if not upcoming:
            logger.error("Keine anstehenden Ferien gefunden!")
            result.errors.append("Keine anstehenden Ferien gefunden")
            return result

        # Ferien-Info für Ergebnis
        holiday_names = [h.name for h in upcoming]
        result.holiday_period = " | ".join(holiday_names)
        result.holiday_start = upcoming[0].start
        result.holiday_end = upcoming[-1].end

        logger.info(f"Suche für {len(upcoming)} Ferienzeiten: {holiday_names}")

        # Reisedaten für ALLE Ferienperioden berechnen
        travel_dates = []
        for holiday in upcoming:
            dates = calculate_travel_dates(
                holiday,
                flexibility_days=config.flight.flexibility_days,
            )
            travel_dates.extend(dates)

        logger.info(f"Gesamt: {len(travel_dates)} Datums-Kombinationen für alle Ferien")

    if not travel_dates:
        logger.error("Keine gültigen Reisedaten berechnet!")
        result.errors.append("Keine gültigen Reisedaten")
        return result

    # --- 2. Flugsuche ---
    logger.info("=" * 60)
    logger.info("FLUGSUCHE STARTEN")
    logger.info("=" * 60)

    client = SerpApiClient(config.serpapi)

    try:
        flights = search_all_routes(client, config.flight, travel_dates)
        result.flights = flights
        logger.info(f"Gesamt: {len(flights)} Flüge gefunden")
    except Exception as e:
        logger.error(f"Fehler bei der Flugsuche: {e}")
        result.errors.append(f"Flugsuche fehlgeschlagen: {e}")
        return result

    if not flights:
        logger.warning("Keine Flüge gefunden!")
        result.errors.append("Keine Flüge gefunden")
        return result

    # --- 3. Preisanalyse ---
    logger.info("Starte Preisanalyse...")
    history = load_price_history(config.paths.price_history_file)
    analyses = analyze_prices(flights, history, cheap_threshold_percent=config.flight.cheap_threshold_percent)
    result.price_analyses = analyses
    flights = mark_cheap_flights(flights, analyses, config.flight.price_limit_alert)
    result.flights = flights
    history = add_to_history(flights, history)
    save_price_history(history, config.paths.price_history_file)

    # --- 4. Preis-Vorhersage ---
    if config.flight.enable_price_prediction:
        logger.info("Starte Preis-Vorhersage...")
        routes = list(set(f"{f.departure_airport}-{f.destination_airport}" for f in flights))
        predictions = predict_all_routes(history, routes, min_data_days=config.flight.prediction_min_data_days)
        result.predictions = predictions

    # --- 5. Kombi-Tickets ---
    if config.flight.enable_combo_tickets and travel_dates:
        logger.info("Starte Kombi-Ticket Suche...")
        best_date_pair = travel_dates[len(travel_dates) // 2]
        try:
            combos = search_combo_tickets(
                client=client, flight_config=config.flight,
                outbound_date=best_date_pair[0], return_date=best_date_pair[1],
                min_savings=config.flight.combo_min_savings,
            )
            result.combo_tickets = combos
        except Exception as e:
            logger.error(f"Fehler bei Kombi-Ticket Suche: {e}")
            result.errors.append(f"Kombi-Suche fehlgeschlagen: {e}")

    # --- Fertig ---
    result.duration_seconds = time.time() - start_time
    logger.info("=" * 60)
    logger.info(f"SUCHE ABGESCHLOSSEN in {result.duration_seconds:.1f}s")
    logger.info(f"  Flüge gefunden: {len(result.flights)}")
    logger.info(f"  Günstig-Alarme: {sum(1 for f in result.flights if f.is_very_cheap)}")
    logger.info(f"  Kombi-Tickets: {len(result.combo_tickets)}")
    logger.info("=" * 60)

    return result


def send_notifications(config: AppConfig, result: SearchResult) -> None:
    """Sendet Telegram-Benachrichtigungen basierend auf den Ergebnissen."""
    notifier = TelegramNotifier(config.telegram)

    if not config.telegram.is_configured():
        logger.warning("Telegram nicht konfiguriert – überspringe Benachrichtigungen")
        return

    send_daily_summary(notifier, result)

    cheap_flights = [f for f in result.flights if f.is_very_cheap]
    for flight in cheap_flights[:3]:
        send_cheap_alert(notifier, flight)

    history = load_price_history(config.paths.price_history_file)
    if len(history) >= 7:
        graph_path = str(Path(config.paths.results_dir) / "price_trend.png")
        created = create_price_trend_graph(history, graph_path)
        if created:
            send_price_graph(notifier, graph_path)


def export_for_frontend(config: AppConfig, result: SearchResult) -> None:
    """Exportiert die Suchergebnisse als JSON für das PWA-Frontend."""
    top_flights = sorted(result.flights, key=lambda f: f.price_total)[:20]

    frontend_data = {
        "last_updated": result.search_date.isoformat(),
        "holiday_period": result.holiday_period,
        "holiday_start": result.holiday_start.isoformat() if result.holiday_start else None,
        "holiday_end": result.holiday_end.isoformat() if result.holiday_end else None,
        "flights": [
            {
                "departure_airport": f.departure_airport,
                "destination_airport": f.destination_airport,
                "outbound_date": f.outbound_date.isoformat(),
                "return_date": f.return_date.isoformat(),
                "price_total": f.price_total,
                "price_per_person": f.price_per_person,
                "luggage": f.luggage_type.value,
                "airline": f.airline,
                "stops_outbound": f.stops_outbound,
                "stops_return": f.stops_return,
                "duration_outbound_min": f.duration_outbound_minutes,
                "duration_return_min": f.duration_return_minutes,
                "is_very_cheap": f.is_very_cheap,
                "savings_percent": f.savings_percent,
                "is_weekend_flight": f.is_weekend_flight,
            }
            for f in top_flights
        ],
        "combo_tickets": [
            {
                "departure_airport": c.departure_airport,
                "return_airport": c.return_airport,
                "destination_airport": c.destination_airport,
                "outbound_date": c.outbound_date.isoformat(),
                "return_date": c.return_date.isoformat(),
                "price_total": c.price_total,
                "savings": c.savings,
            }
            for c in result.combo_tickets[:5]
        ],
        "price_analyses": [
            {
                "route": a.route,
                "current_price": a.current_price,
                "average_price": a.average_price,
                "trend": a.trend.value,
                "percent_vs_average": a.percent_vs_average,
                "is_very_cheap": a.is_very_cheap,
            }
            for a in result.price_analyses
        ],
        "predictions": [
            {
                "route": p.route,
                "predicted_price": p.predicted_price,
                "confidence": p.confidence,
                "advice": p.advice.value,
                "reason": p.reason,
            }
            for p in result.predictions
        ],
        "summary": {
            "total_flights": len(result.flights),
            "cheapest_price": top_flights[0].price_total if top_flights else None,
            "cheapest_airport": top_flights[0].departure_airport if top_flights else None,
            "has_alert": result.has_alert,
            "errors": result.errors,
        },
    }

    output_path = Path(config.paths.frontend_data_file)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(frontend_data, f, indent=2, ensure_ascii=False)
    logger.info(f"Frontend-Daten exportiert: {output_path}")

    results_path = Path(config.paths.latest_results_file)
    results_path.parent.mkdir(parents=True, exist_ok=True)
    with open(results_path, "w", encoding="utf-8") as f:
        json.dump(frontend_data, f, indent=2, ensure_ascii=False)


def parse_manual_dates(date_str: str) -> list[tuple[date, date]] | None:
    """
    Parst manuelle Datums-Eingabe.
    Format: "2026-12-23:2027-01-06" (Hin:Rück)
    """
    try:
        parts = date_str.split(":")
        if len(parts) != 2:
            return None

        outbound = date.fromisoformat(parts[0].strip())
        return_date = date.fromisoformat(parts[1].strip())

        if return_date <= outbound:
            logger.error("Rückflug muss nach Hinflug sein!")
            return None

        from .school_holidays import calculate_travel_dates
        from .models import HolidayPeriod
        pseudo_holiday = HolidayPeriod(name="Manuelle Suche", start=outbound, end=return_date)
        return calculate_travel_dates(pseudo_holiday, flexibility_days=2)

    except ValueError as e:
        logger.error(f"Ungültiges Datumsformat: {e}")
        return None


def main():
    """Entry Point der Anwendung."""
    parser = argparse.ArgumentParser(description="FlugFinder Iran – Günstige Flüge nach Iran finden")
    parser.add_argument("--dates", type=str, help="Manuelle Reisedaten (Format: YYYY-MM-DD:YYYY-MM-DD)")
    parser.add_argument("--no-notify", action="store_true", help="Keine Telegram-Benachrichtigungen")
    parser.add_argument("--no-frontend", action="store_true", help="Keine Frontend-Daten exportieren")
    parser.add_argument("--verbose", "-v", action="store_true", help="DEBUG Log-Level")

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    logger.info("🛫 FlugFinder Iran gestartet")

    # Konfiguration laden
    config = load_config()

    if not config.serpapi.is_configured():
        logger.error("SerpApi API Key nicht konfiguriert! Bitte SERPAPI_API_KEY in .env setzen.")
        sys.exit(1)

    # Manuelle Daten?
    target_dates = None
    if args.dates:
        target_dates = parse_manual_dates(args.dates)
        if not target_dates:
            logger.error("Konnte Daten nicht parsen. Format: YYYY-MM-DD:YYYY-MM-DD")
            sys.exit(1)

    # Suche durchführen
    result = run_search(config, target_dates)

    # Benachrichtigungen
    if not args.no_notify:
        send_notifications(config, result)

    # Frontend-Daten
    if not args.no_frontend:
        export_for_frontend(config, result)

    if result.errors and not result.flights:
        sys.exit(1)

    logger.info("🏁 FlugFinder Iran beendet")


if __name__ == "__main__":
    main()
