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
from .flight_search import FlightSearchClient, search_all_routes
from .models import SearchResult
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
    get_all_upcoming_holidays,
    is_weekend_departure,
    load_holidays,
)

# Logging konfigurieren
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def _collect_usable_holidays(config: AppConfig) -> list[dict]:
    """
    Sammelt die nächsten Ferienzeiten die tatsächlich buchbare Termine liefern.

    Erst werden für alle Kandidaten die Termine berechnet, dann ausgewählt.
    Eine bereits laufende Ferienzeit deren Ende zu nah ist liefert keine
    Termine mehr (Mindestaufenthalt passt nicht mehr rein) und darf keinen
    der begrenzten Slots belegen.

    Returns:
        Liste von {"holiday": HolidayPeriod, "dates": [(hin, rück), ...]}
    """
    holidays = load_holidays(config.paths.holidays_file)
    candidates = get_all_upcoming_holidays(holidays, min_duration_days=3)

    if not candidates:
        logger.error("Keine anstehenden Ferien gefunden!")
        return []

    usable: list[dict] = []
    for holiday in candidates:
        dates = calculate_travel_dates(
            holiday,
            flexibility_days=config.flight.flexibility_days,
        )
        if dates:
            usable.append({"holiday": holiday, "dates": dates})
        else:
            logger.info(
                f"Ferienzeit übersprungen: {holiday.name} "
                f"(endet {holiday.end}, kein Termin mit Mindestaufenthalt möglich)"
            )
        if len(usable) >= config.flight.max_holidays_per_run:
            break

    return usable


def _build_search_plan(
    travel_dates: list[tuple[date, date]],
    holidays_info: list,
    flight_config,
) -> list[tuple[date, date]]:
    """
    Wählt aus allen möglichen Datumspaaren die aus, die ins Anfrage-Budget passen.

    Strategie: pro Runde ein Datumspaar je Ferienperiode nehmen (Round-Robin).
    So bekommt jede Ferienzeit mindestens einen Treffer, bevor eine einzelne
    Periode mehrere Varianten belegt.

    Args:
        travel_dates: Alle berechneten Datumspaare
        holidays_info: Liste von {holiday, dates} (leer bei manueller Suche)
        flight_config: Flug-Konfiguration mit den Budget-Grenzen

    Returns:
        Die tatsächlich zu durchsuchenden Datumspaare
    """
    budget_limit = flight_config.max_date_pairs_total

    if not holidays_info:
        # Manuelle Suche: einfach die ersten Paare nehmen
        selected = sorted(travel_dates)[:budget_limit]
        logger.info(
            f"Suchplan (manuell): {len(selected)} von {len(travel_dates)} Datumspaaren"
        )
        return selected

    # Kandidaten je Ferienperiode, bevorzugt Wochenend-Flüge
    per_holiday: list[list[tuple[date, date]]] = []
    for info in holidays_info:
        dates = sorted(info["dates"])
        if not dates:
            continue
        dates.sort(key=lambda pair: (not is_weekend_departure(pair[0], pair[1]), pair[0]))
        per_holiday.append(dates[: flight_config.max_date_pairs_per_holiday])

    # Round-Robin über die Ferienperioden
    selected: list[tuple[date, date]] = []
    round_index = 0
    while len(selected) < budget_limit:
        added_this_round = False
        for candidates in per_holiday:
            if round_index < len(candidates) and len(selected) < budget_limit:
                selected.append(candidates[round_index])
                added_this_round = True
        if not added_this_round:
            break
        round_index += 1

    logger.info(
        f"Suchplan: {len(selected)} von {len(travel_dates)} Datumspaaren "
        f"(Budget erlaubt {budget_limit})"
    )
    for outbound, ret in selected:
        weekend = " [Wochenende]" if is_weekend_departure(outbound, ret) else ""
        logger.info(f"  {outbound} → {ret} ({(ret - outbound).days} Nächte){weekend}")

    return selected


def run_search(config: AppConfig, target_dates: list[tuple[date, date]] | None = None) -> tuple[SearchResult, list]:
    """
    Führt die komplette Flugsuche durch.

    Args:
        config: App-Konfiguration
        target_dates: Optionale manuelle Reisedaten. Wenn None, werden Schulferien genutzt.

    Returns:
        Tuple aus (Komplettes Suchergebnis, Liste der Ferien-Infos für Frontend-Gruppierung)
    """
    start_time = time.time()
    result = SearchResult(search_date=datetime.now())

    # --- 1. Reisedaten bestimmen ---
    holidays_info = []  # Liste von {holiday, dates} für Frontend-Gruppierung

    if target_dates:
        travel_dates = target_dates
        result.holiday_period = "Manuelle Suche"
        logger.info(f"Manuelle Suche mit {len(travel_dates)} Datums-Kombinationen")
    else:
        usable = _collect_usable_holidays(config)

        if not usable:
            logger.error("Keine Ferienzeit mit buchbaren Terminen gefunden!")
            result.errors.append("Keine buchbaren Ferientermine")
            return result, []

        holidays_info = usable
        travel_dates = [pair for entry in usable for pair in entry["dates"]]

        holiday_names = [entry["holiday"].name for entry in usable]
        result.holiday_period = " | ".join(holiday_names)
        result.holiday_start = usable[0]["holiday"].start
        result.holiday_end = usable[-1]["holiday"].end

        logger.info(f"Suche für {len(usable)} Ferienzeiten: {holiday_names}")
        logger.info(f"Gesamt: {len(travel_dates)} Datums-Kombinationen")

    if not travel_dates:
        logger.error("Keine gültigen Reisedaten berechnet!")
        result.errors.append("Keine gültigen Reisedaten")
        return result, holidays_info

    # --- 2. Flugsuche ---
    # Datumspaare aufs Anfrage-Budget eindampfen
    search_dates = _build_search_plan(travel_dates, holidays_info, config.flight)

    if not search_dates:
        logger.error("Suchplan ist leer!")
        result.errors.append("Suchplan leer")
        return result, holidays_info

    planned_calls = (
        len(search_dates) * config.flight.num_routes * max(config.flight.luggage_variants, 1)
    )

    logger.info("=" * 60)
    logger.info("FLUGSUCHE STARTEN")
    logger.info(f"  Ferienzeiten: {result.holiday_period}")
    logger.info(f"  Provider-Kette: {' → '.join(config.configured_providers) or 'keine'}")
    logger.info(f"  Datumspaare: {len(search_dates)}")
    logger.info(f"  Routen pro Datumspaar: {config.flight.num_routes}")
    logger.info(f"  Geplante API-Anfragen: {planned_calls} (Limit {config.flight.max_api_calls_per_run})")
    logger.info("=" * 60)

    client = FlightSearchClient.from_config(config)

    if not client.providers:
        logger.error("Kein Suchdienst verfügbar – Suche abgebrochen")
        result.errors.append("Kein Suchdienst konfiguriert")
        return result, holidays_info

    try:
        flights = search_all_routes(client, config.flight, search_dates)
        result.flights = flights
        logger.info(f"Gesamt: {len(flights)} Flüge gefunden")
    except Exception as e:
        logger.error(f"Fehler bei der Flugsuche: {e}")
        result.errors.append(f"Flugsuche fehlgeschlagen: {e}")
        return result, holidays_info

    if not flights:
        logger.warning("Keine Flüge gefunden!")
        result.errors.append("Keine Flüge gefunden")
        return result, holidays_info

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
    # Nur wenn nach der Hauptsuche noch Budget übrig ist
    if config.flight.enable_combo_tickets and search_dates:
        if client.has_capacity():
            best_date_pair = search_dates[len(search_dates) // 2]
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
        else:
            logger.info("Kombi-Ticket Suche übersprungen – Anfrage-Budget aufgebraucht")

    # --- Fertig ---
    result.duration_seconds = time.time() - start_time
    result.total_searches = client.calls_used
    logger.info("=" * 60)
    logger.info(f"SUCHE ABGESCHLOSSEN in {result.duration_seconds:.1f}s")
    logger.info(f"  Flüge gefunden: {len(result.flights)}")
    logger.info(f"  Günstig-Alarme: {sum(1 for f in result.flights if f.is_very_cheap)}")
    logger.info(f"  Kombi-Tickets: {len(result.combo_tickets)}")
    for line in client.stats_summary():
        logger.info(f"  {line}")
    logger.info("=" * 60)

    return result, holidays_info


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


def export_for_frontend(config: AppConfig, result: SearchResult, holidays_info: list) -> None:
    """Exportiert die Suchergebnisse als JSON für das PWA-Frontend, gruppiert nach Ferienperiode."""

    def flight_to_dict(f):
        return {
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
            "booking_link": f.booking_link,
            "source": f.source,
        }

    # Flüge nach Ferienperiode gruppieren
    holidays_data = []
    if holidays_info:
        for info in holidays_info:
            holiday = info["holiday"]
            dates_set = set(info["dates"])

            # Wochenend-Erweiterung berechnen für Frontend-Anzeige
            from .school_holidays import extend_with_weekends
            ext_start, ext_end = extend_with_weekends(holiday)

            # Flüge zuordnen: Hinflug-Datum muss in den Daten dieser Ferienperiode liegen
            holiday_flights = [
                f for f in result.flights
                if (f.outbound_date, f.return_date) in dates_set
            ]
            holiday_flights.sort(key=lambda f: f.price_total)

            holiday_entry = {
                "name": holiday.name,
                "start": holiday.start.isoformat(),
                "end": holiday.end.isoformat(),
                "flights": [flight_to_dict(f) for f in holiday_flights[:20]],
            }
            # Nur anzeigen wenn tatsächlich erweitert
            if ext_start != holiday.start or ext_end != holiday.end:
                holiday_entry["extended_start"] = ext_start.isoformat()
                holiday_entry["extended_end"] = ext_end.isoformat()

            holidays_data.append(holiday_entry)
    else:
        # Manuelle Suche oder Fallback: alle Flüge in eine Gruppe
        top_flights = sorted(result.flights, key=lambda f: f.price_total)[:20]
        holidays_data.append({
            "name": result.holiday_period or "Suchergebnisse",
            "start": result.holiday_start.isoformat() if result.holiday_start else None,
            "end": result.holiday_end.isoformat() if result.holiday_end else None,
            "flights": [flight_to_dict(f) for f in top_flights],
        })

    # Auch eine flache Liste für Rückwärtskompatibilität
    top_flights = sorted(result.flights, key=lambda f: f.price_total)[:20]

    frontend_data = {
        "last_updated": result.search_date.isoformat(),
        "holiday_period": result.holiday_period,
        "holidays": holidays_data,
        "flights": [flight_to_dict(f) for f in top_flights],
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
            "passengers": {
                "adults": config.flight.adults,
                "children_ages": list(config.flight.children_ages),
            },
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


def _run_dry_run(config: AppConfig, target_dates: list[tuple[date, date]] | None = None) -> None:
    """
    Dry-Run: Zeigt an welche Ferien und Daten durchsucht würden, ohne API-Aufrufe.
    Nützlich um die Pipeline-Logik zu verifizieren.
    """
    logger.info("=" * 60)
    logger.info("DRY RUN – Keine API-Anfragen werden gesendet")
    logger.info("=" * 60)

    holidays_info: list = []

    if target_dates:
        travel_dates = target_dates
        logger.info(f"Manuelle Suche mit {len(travel_dates)} Datumskombinationen")
    else:
        holidays_info = _collect_usable_holidays(config)
        if not holidays_info:
            logger.error("Keine Ferienzeit mit buchbaren Terminen gefunden!")
            return
        travel_dates = [pair for entry in holidays_info for pair in entry["dates"]]

    if not travel_dates:
        logger.error("Keine gültigen Reisedaten berechnet!")
        return

    # Suchplan wie im Echtlauf berechnen
    search_dates = _build_search_plan(travel_dates, holidays_info, config.flight)

    planned_calls = (
        len(search_dates) * config.flight.num_routes * max(config.flight.luggage_variants, 1)
    )

    logger.info("")
    logger.info("ZUSAMMENFASSUNG:")
    logger.info(f"  Provider-Kette: {' → '.join(config.configured_providers) or 'keine konfiguriert'}")
    logger.info(f"  Mögliche Datumspaare: {len(travel_dates)}")
    logger.info(f"  Davon im Suchplan: {len(search_dates)}")
    logger.info(f"  Abflughäfen: {config.flight.departure_airports}")
    logger.info(f"  Zielflughäfen: {config.flight.destination_airports}")
    logger.info(f"  Routen pro Datumspaar: {config.flight.num_routes}")
    logger.info(f"  Gepäck-Varianten: {max(config.flight.luggage_variants, 1)}")
    logger.info(f"  Geplante API-Anfragen: {planned_calls}")
    logger.info(f"  Budget-Limit: {config.flight.max_api_calls_per_run}")
    logger.info(f"  Geschätzte Dauer: ~{planned_calls * 0.5 / 60:.1f} Minuten")
    logger.info("")

    if search_dates:
        dates_sorted = sorted(search_dates)
        logger.info(f"  Frühester Hinflug: {dates_sorted[0][0]}")
        logger.info(f"  Spätester Rückflug: {dates_sorted[-1][1]}")
        logger.info("")

        logger.info("BEISPIEL-SUCHEN (erste 5):")
        for out_date, ret_date in dates_sorted[:5]:
            dep = config.flight.departure_airports[0]
            dest = config.flight.destination_airports[0]
            logger.info(f"  {dep} → {dest}: {out_date} – {ret_date}")

    logger.info("")
    logger.info("✓ Dry-Run abgeschlossen. Starte ohne --dry-run für echte Suche.")


def main():
    """Entry Point der Anwendung."""
    parser = argparse.ArgumentParser(description="FlugFinder Iran – Günstige Flüge nach Iran finden")
    parser.add_argument("--dates", type=str, help="Manuelle Reisedaten (Format: YYYY-MM-DD:YYYY-MM-DD)")
    parser.add_argument("--no-notify", action="store_true", help="Keine Telegram-Benachrichtigungen")
    parser.add_argument("--no-frontend", action="store_true", help="Keine Frontend-Daten exportieren")
    parser.add_argument("--dry-run", action="store_true", help="Nur Ferien und Daten anzeigen, keine API-Anfragen")
    parser.add_argument(
        "--all-destinations",
        action="store_true",
        help="Auch die sekundären Ziele (Mashhad) durchsuchen – verdoppelt die API-Anfragen",
    )
    parser.add_argument("--verbose", "-v", action="store_true", help="DEBUG Log-Level")

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    logger.info("🛫 FlugFinder Iran gestartet")

    # Konfiguration laden – Ziel-Rotation vor dem Logging setzen
    config = AppConfig()
    config.flight.include_secondary_destinations = args.all_destinations
    config = load_config(config)

    # Manuelle Daten?
    target_dates = None
    if args.dates:
        target_dates = parse_manual_dates(args.dates)
        if not target_dates:
            logger.error("Konnte Daten nicht parsen. Format: YYYY-MM-DD:YYYY-MM-DD")
            sys.exit(1)

    # Dry-Run: nur Ferien + Daten anzeigen, keine API-Calls
    if args.dry_run:
        _run_dry_run(config, target_dates)
        return

    if not config.has_any_provider():
        logger.error(
            "Kein Suchdienst konfiguriert! Setze SERPAPI_API_KEY und/oder RAPIDAPI_KEY in .env."
        )
        sys.exit(1)

    # Suche durchführen
    result, holidays_info = run_search(config, target_dates)

    # Benachrichtigungen
    if not args.no_notify:
        send_notifications(config, result)

    # Frontend-Daten
    if not args.no_frontend:
        export_for_frontend(config, result, holidays_info)

    if result.errors and not result.flights:
        sys.exit(1)

    logger.info("🏁 FlugFinder Iran beendet")


if __name__ == "__main__":
    main()
