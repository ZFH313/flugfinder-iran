"""
Schulferien Niedersachsen.
Lädt Feriendaten und berechnet Reisezeiträume mit Flexibilität.
"""

import json
import logging
from datetime import date, timedelta
from pathlib import Path

from .models import HolidayPeriod

logger = logging.getLogger(__name__)

# Niedersachsen Schulferien 2025/2026 und 2026/2027
# Quelle: https://www.schulferien.org/niedersachsen/
HOLIDAYS_DATA = [
    # --- Schuljahr 2025/2026 ---
    {
        "name": "Sommerferien 2025",
        "start": "2025-07-03",
        "end": "2025-08-13",
        "state": "Niedersachsen",
    },
    {
        "name": "Herbstferien 2025",
        "start": "2025-10-20",
        "end": "2025-10-31",
        "state": "Niedersachsen",
    },
    {
        "name": "Weihnachtsferien 2025/2026",
        "start": "2025-12-22",
        "end": "2026-01-05",
        "state": "Niedersachsen",
    },
    {
        "name": "Winterferien 2026",
        "start": "2026-02-02",
        "end": "2026-02-03",
        "state": "Niedersachsen",
    },
    {
        "name": "Osterferien 2026",
        "start": "2026-03-23",
        "end": "2026-04-07",
        "state": "Niedersachsen",
    },
    {
        "name": "Pfingstferien 2026",
        "start": "2026-05-26",
        "end": "2026-05-26",
        "state": "Niedersachsen",
    },
    # --- Schuljahr 2026/2027 ---
    {
        "name": "Sommerferien 2026",
        "start": "2026-07-02",
        "end": "2026-08-12",
        "state": "Niedersachsen",
    },
    {
        "name": "Herbstferien 2026",
        "start": "2026-10-19",
        "end": "2026-10-30",
        "state": "Niedersachsen",
    },
    {
        "name": "Weihnachtsferien 2026/2027",
        "start": "2026-12-23",
        "end": "2027-01-06",
        "state": "Niedersachsen",
    },
    {
        "name": "Winterferien 2027",
        "start": "2027-02-01",
        "end": "2027-02-02",
        "state": "Niedersachsen",
    },
    {
        "name": "Osterferien 2027",
        "start": "2027-03-22",
        "end": "2027-04-06",
        "state": "Niedersachsen",
    },
    {
        "name": "Pfingstferien 2027",
        "start": "2027-05-14",
        "end": "2027-05-25",
        "state": "Niedersachsen",
    },
    {
        "name": "Sommerferien 2027",
        "start": "2027-07-01",
        "end": "2027-08-11",
        "state": "Niedersachsen",
    },
]


def load_holidays(holidays_file: str | None = None) -> list[HolidayPeriod]:
    """
    Lädt Schulferien aus JSON-Datei oder nutzt eingebaute Daten.

    Args:
        holidays_file: Pfad zur JSON-Datei (optional, nutzt eingebaute Daten wenn None)

    Returns:
        Liste aller Ferienperioden
    """
    data = HOLIDAYS_DATA

    # Versuche externe Datei zu laden (überschreibt eingebaute Daten)
    if holidays_file:
        file_path = Path(holidays_file)
        if file_path.exists():
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                logger.info(f"Feriendaten aus Datei geladen: {holidays_file}")
            except (json.JSONDecodeError, IOError) as e:
                logger.warning(f"Fehler beim Laden der Feriendatei: {e}. Nutze eingebaute Daten.")
                data = HOLIDAYS_DATA
        else:
            logger.info("Keine externe Feriendatei gefunden. Nutze eingebaute Daten.")

    holidays = []
    for entry in data:
        try:
            holiday = HolidayPeriod(
                name=entry["name"],
                start=date.fromisoformat(entry["start"]),
                end=date.fromisoformat(entry["end"]),
                state=entry.get("state", "Niedersachsen"),
            )
            holidays.append(holiday)
        except (KeyError, ValueError) as e:
            logger.warning(f"Ungültiger Ferien-Eintrag übersprungen: {entry} ({e})")

    logger.info(f"{len(holidays)} Ferienperioden geladen")
    return holidays


def save_holidays(holidays: list[HolidayPeriod], holidays_file: str) -> None:
    """Speichert Feriendaten in JSON-Datei."""
    data = [
        {
            "name": h.name,
            "start": h.start.isoformat(),
            "end": h.end.isoformat(),
            "state": h.state,
        }
        for h in holidays
    ]

    file_path = Path(holidays_file)
    file_path.parent.mkdir(parents=True, exist_ok=True)

    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    logger.info(f"Feriendaten gespeichert: {holidays_file}")


def get_next_holiday(
    holidays: list[HolidayPeriod],
    reference_date: date | None = None,
    min_duration_days: int = 3,
) -> HolidayPeriod | None:
    """
    Findet die nächste anstehende Ferienperiode.

    Args:
        holidays: Alle Ferienperioden
        reference_date: Ab welchem Datum suchen (default: heute)
        min_duration_days: Mindestdauer der Ferien (kurze Ferien wie 1-2 Tage überspringen)

    Returns:
        Nächste Ferienperiode oder None
    """
    ref = reference_date or date.today()

    upcoming = [
        h for h in holidays
        if h.start > ref and h.duration_days >= min_duration_days
    ]

    if not upcoming:
        logger.warning("Keine anstehenden Ferien gefunden")
        return None

    # Sortiere nach Startdatum, nimm die nächste
    upcoming.sort(key=lambda h: h.start)
    next_holiday = upcoming[0]

    logger.info(f"Nächste Ferien: {next_holiday.name} ({next_holiday.start} – {next_holiday.end})")
    return next_holiday


def get_all_upcoming_holidays(
    holidays: list[HolidayPeriod],
    reference_date: date | None = None,
    min_duration_days: int = 3,
) -> list[HolidayPeriod]:
    """
    Gibt alle zukünftigen UND aktuell laufenden Ferienperioden zurück (sortiert).

    Eine Ferienperiode gilt als relevant wenn:
    - Sie noch nicht vorbei ist (end >= heute)
    - Sie mindestens min_duration_days lang ist
    """
    ref = reference_date or date.today()

    upcoming = [
        h for h in holidays
        if h.end >= ref and h.duration_days >= min_duration_days
    ]
    upcoming.sort(key=lambda h: h.start)

    logger.info(f"{len(upcoming)} relevante Ferienperioden gefunden (inkl. laufende)")
    for h in upcoming:
        status = "AKTIV" if h.start <= ref <= h.end else "kommend"
        logger.info(f"  [{status}] {h.name}: {h.start} – {h.end} ({h.duration_days} Tage)")

    return upcoming


def extend_with_weekends(holiday: HolidayPeriod) -> tuple[date, date]:
    """
    Erweitert eine Ferienperiode um angrenzende Wochenenden.

    Logik:
    - Wenn Ferien am Montag/Dienstag starten → Freitag davor als frühesten Hinflug nutzen
    - Wenn Ferien am Donnerstag/Freitag enden → Sonntag danach als spätesten Rückflug nutzen

    Das ermöglicht längeren Urlaub wenn ein Wochenende direkt an die Ferien grenzt.

    Args:
        holiday: Die Ferienperiode

    Returns:
        (erweiterter_start, erweitertes_ende) – die erweiterten Reisedaten
    """
    extended_start = holiday.start
    extended_end = holiday.end

    # Wochentag: 0=Montag, 1=Dienstag, ..., 4=Freitag, 5=Samstag, 6=Sonntag
    start_weekday = holiday.start.weekday()
    end_weekday = holiday.end.weekday()

    # Wenn Ferien am Montag starten → Freitag davor dazunehmen (3 Tage zurück)
    if start_weekday == 0:  # Montag
        extended_start = holiday.start - timedelta(days=3)
        logger.debug(f"  Wochenend-Erweiterung: Start Fr {extended_start} (statt Mo {holiday.start})")
    # Wenn Ferien am Dienstag starten → Samstag davor (3 Tage zurück)
    elif start_weekday == 1:  # Dienstag
        extended_start = holiday.start - timedelta(days=3)
        logger.debug(f"  Wochenend-Erweiterung: Start Sa {extended_start} (statt Di {holiday.start})")

    # Wenn Ferien am Donnerstag enden → Sonntag danach (3 Tage vorwärts)
    if end_weekday == 3:  # Donnerstag
        extended_end = holiday.end + timedelta(days=3)
        logger.debug(f"  Wochenend-Erweiterung: Ende So {extended_end} (statt Do {holiday.end})")
    # Wenn Ferien am Freitag enden → Sonntag danach (2 Tage vorwärts)
    elif end_weekday == 4:  # Freitag
        extended_end = holiday.end + timedelta(days=2)
        logger.debug(f"  Wochenend-Erweiterung: Ende So {extended_end} (statt Fr {holiday.end})")

    return extended_start, extended_end


def calculate_travel_dates(
    holiday: HolidayPeriod,
    flexibility_days: int = 2,
    reference_date: date | None = None,
) -> list[tuple[date, date]]:
    """
    Berechnet alle möglichen Reisedaten basierend auf einer Ferienperiode mit Flexibilität.

    Berücksichtigt Wochenend-Erweiterung: Wenn ein Wochenende direkt an die Ferien grenzt,
    wird es in den möglichen Reisezeitraum einbezogen.

    Hinflug: Erweiterter Ferienstart ± flexibility_days (aber nicht in der Vergangenheit)
    Rückflug: Erweitertes Ferienende ± flexibility_days (aber nicht in der Vergangenheit)

    Args:
        holiday: Die Ferienperiode
        flexibility_days: ±Tage Flexibilität
        reference_date: Referenzdatum (default: heute)

    Returns:
        Liste von (Hinflug-Datum, Rückflug-Datum) Kombinationen
    """
    ref = reference_date or date.today()
    # Frühestes mögliches Hinflugdatum ist morgen (kann heute nicht mehr buchen/fliegen)
    earliest_possible = ref + timedelta(days=1)

    # Wochenend-Erweiterung anwenden
    extended_start, extended_end = extend_with_weekends(holiday)

    travel_dates = []

    # Alle möglichen Hinflug-Tage (basierend auf erweitertem Start)
    outbound_dates = [
        extended_start + timedelta(days=d)
        for d in range(-flexibility_days, flexibility_days + 1)
    ]
    # Vergangene Daten rausfiltern
    outbound_dates = [d for d in outbound_dates if d >= earliest_possible]

    # Alle möglichen Rückflug-Tage (basierend auf erweitertem Ende)
    return_dates = [
        extended_end + timedelta(days=d)
        for d in range(-flexibility_days, flexibility_days + 1)
    ]
    # Vergangene Daten rausfiltern
    return_dates = [d for d in return_dates if d >= earliest_possible]

    if not outbound_dates or not return_dates:
        logger.warning(f"Keine gültigen Reisedaten für {holiday.name} (alle in der Vergangenheit)")
        return []

    # Alle gültigen Kombinationen (Rückflug muss nach Hinflug sein, min. 7 Tage)
    for out_date in outbound_dates:
        for ret_date in return_dates:
            if (ret_date - out_date).days >= 7:
                travel_dates.append((out_date, ret_date))

    if extended_start != holiday.start or extended_end != holiday.end:
        logger.info(
            f"Reisedaten berechnet für {holiday.name} (mit WE-Erweiterung): "
            f"{len(travel_dates)} Kombinationen "
            f"(Hin: {outbound_dates[0]} – {outbound_dates[-1]}, "
            f"Rück: {return_dates[0]} – {return_dates[-1]})"
        )
    else:
        logger.info(
            f"Reisedaten berechnet für {holiday.name}: "
            f"{len(travel_dates)} Kombinationen "
            f"(Hin: {outbound_dates[0]} – {outbound_dates[-1]}, "
            f"Rück: {return_dates[0]} – {return_dates[-1]})"
        )

    return travel_dates


def is_weekend_departure(outbound_date: date, return_date: date) -> bool:
    """
    Prüft ob Hinflug am Freitag/Samstag und Rückflug am Sonntag ist.
    weekday(): 0=Montag, 4=Freitag, 5=Samstag, 6=Sonntag
    """
    outbound_is_weekend = outbound_date.weekday() in (4, 5)  # Freitag oder Samstag
    return_is_sunday = return_date.weekday() == 6  # Sonntag
    return outbound_is_weekend and return_is_sunday
