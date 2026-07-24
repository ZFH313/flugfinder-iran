"""
Preis-Vorhersage basierend auf historischen Daten.
Nutzt lineare Regression und einfache Muster-Erkennung
um Buchungsempfehlungen zu geben.
"""

import logging
from datetime import date, timedelta
from statistics import mean, stdev

import numpy as np

from .models import PredictionAdvice, PriceHistoryEntry, PricePrediction

logger = logging.getLogger(__name__)


def predict_prices(
    history: list[PriceHistoryEntry],
    route: str,
    prediction_days_ahead: int = 14,
    min_data_days: int = 14,
) -> PricePrediction | None:
    """
    Erstellt eine Preis-Vorhersage für eine Route.

    Nutzt lineare Regression auf historische Preisdaten um den Trend
    zu extrapolieren und eine Buchungsempfehlung zu geben.

    Args:
        history: Kompletter Preisverlauf
        route: Route z.B. "HAJ-IKA"
        prediction_days_ahead: Für wie viele Tage in die Zukunft vorhersagen
        min_data_days: Mindestanzahl Datenpunkte für Vorhersage

    Returns:
        PricePrediction oder None wenn nicht genug Daten
    """
    # Filtere History für diese Route
    route_history = [
        e for e in history
        if e.route == route and e.price_with_luggage is not None
    ]

    if len(route_history) < min_data_days:
        logger.info(
            f"Nicht genug Daten für Vorhersage auf {route}: "
            f"{len(route_history)}/{min_data_days} Tage"
        )
        return None

    # Sortiere nach Datum
    route_history.sort(key=lambda e: e.search_date)

    # Daten vorbereiten für Regression
    prices = [e.price_with_luggage for e in route_history]
    dates = [e.search_date for e in route_history]

    # Konvertiere Daten in numerische Werte (Tage seit erstem Eintrag)
    base_date = dates[0]
    x = np.array([(d - base_date).days for d in dates], dtype=float)
    y = np.array(prices, dtype=float)

    # Lineare Regression: y = mx + b
    slope, intercept = _linear_regression(x, y)

    # Vorhersage für X Tage in die Zukunft
    today = date.today()
    prediction_date = today + timedelta(days=prediction_days_ahead)
    x_predict = float((prediction_date - base_date).days)
    predicted_price = slope * x_predict + intercept

    # Konfidenz berechnen (basierend auf R² und Datenmenge)
    confidence = _calculate_confidence(x, y, slope, intercept)

    # Buchungsempfehlung
    advice, reason = _generate_advice(
        current_price=prices[-1],
        predicted_price=predicted_price,
        slope=slope,
        confidence=confidence,
        prices=prices,
    )

    prediction = PricePrediction(
        route=route,
        prediction_date=prediction_date,
        predicted_price=round(max(predicted_price, 0), 2),  # Nie negativ
        confidence=round(confidence, 2),
        advice=advice,
        reason=reason,
    )

    logger.info(
        f"Vorhersage {route}: {predicted_price:.0f}€ in {prediction_days_ahead} Tagen "
        f"(Konfidenz: {confidence:.0%}, Empfehlung: {advice.value})"
    )

    return prediction


def predict_all_routes(
    history: list[PriceHistoryEntry],
    routes: list[str],
    min_data_days: int = 14,
) -> list[PricePrediction]:
    """
    Erstellt Vorhersagen für alle angegebenen Routen.

    Args:
        history: Kompletter Preisverlauf
        routes: Liste der Routen z.B. ["HAJ-IKA", "BER-IKA"]
        min_data_days: Mindestanzahl Datenpunkte

    Returns:
        Liste der Vorhersagen (nur für Routen mit genug Daten)
    """
    predictions = []

    for route in routes:
        prediction = predict_prices(
            history=history,
            route=route,
            min_data_days=min_data_days,
        )
        if prediction:
            predictions.append(prediction)

    logger.info(f"Vorhersagen erstellt: {len(predictions)}/{len(routes)} Routen")
    return predictions


def _linear_regression(x: np.ndarray, y: np.ndarray) -> tuple[float, float]:
    """
    Einfache lineare Regression (Least Squares).
    Gibt (slope, intercept) zurück.
    """
    n = len(x)
    if n < 2:
        return 0.0, float(y[0]) if len(y) > 0 else 0.0

    x_mean = np.mean(x)
    y_mean = np.mean(y)

    # Slope = Σ((xi - x̄)(yi - ȳ)) / Σ((xi - x̄)²)
    numerator = np.sum((x - x_mean) * (y - y_mean))
    denominator = np.sum((x - x_mean) ** 2)

    if denominator == 0:
        return 0.0, float(y_mean)

    slope = float(numerator / denominator)
    intercept = float(y_mean - slope * x_mean)

    return slope, intercept


def _calculate_confidence(
    x: np.ndarray,
    y: np.ndarray,
    slope: float,
    intercept: float,
) -> float:
    """
    Berechnet die Konfidenz der Vorhersage (0-1).
    Basiert auf R² (Bestimmtheitsmaß) und Datenmenge.
    """
    n = len(y)
    if n < 3:
        return 0.1  # Sehr wenig Vertrauen

    # R² berechnen
    y_mean = np.mean(y)
    y_predicted = slope * x + intercept

    ss_res = np.sum((y - y_predicted) ** 2)  # Residuenquadratsumme
    ss_tot = np.sum((y - y_mean) ** 2)  # Gesamtquadratsumme

    if ss_tot == 0:
        r_squared = 0.0
    else:
        r_squared = float(1 - (ss_res / ss_tot))

    # R² kann negativ sein bei schlechtem Fit → auf 0 begrenzen
    r_squared = max(r_squared, 0.0)

    # Konfidenz: Kombination aus R² und Datenmenge
    # Mehr Daten = höhere Konfidenz (bis max 1.0)
    data_factor = min(n / 30, 1.0)  # 30 Tage = volle Daten-Konfidenz

    confidence = r_squared * 0.6 + data_factor * 0.4

    return min(confidence, 1.0)


def _generate_advice(
    current_price: float,
    predicted_price: float,
    slope: float,
    confidence: float,
    prices: list[float],
) -> tuple[PredictionAdvice, str]:
    """
    Generiert eine Buchungsempfehlung basierend auf der Vorhersage.

    Returns:
        (Empfehlung, Begründung als Text)
    """
    # Zu wenig Konfidenz → unsicher
    if confidence < 0.3:
        return (
            PredictionAdvice.UNCERTAIN,
            f"Nicht genug zuverlässige Daten für eine Empfehlung (Konfidenz: {confidence:.0%})"
        )

    price_change_percent = ((predicted_price - current_price) / current_price) * 100

    # Aktueller Preis im Vergleich zum historischen Minimum
    min_price = min(prices)
    max_price = max(prices)
    price_range = max_price - min_price

    is_near_minimum = (current_price - min_price) < (price_range * 0.2) if price_range > 0 else False

    # Entscheidungslogik
    if slope > 0 and price_change_percent > 5:
        # Preise steigen → jetzt buchen
        reason = (
            f"Preise steigen voraussichtlich um {price_change_percent:.0f}% "
            f"(von {current_price:.0f}€ auf ~{predicted_price:.0f}€). "
            f"Aktueller Preis ist günstig."
        )
        return (PredictionAdvice.BOOK_NOW, reason)

    elif slope < 0 and price_change_percent < -5:
        # Preise fallen → warten
        reason = (
            f"Preise fallen voraussichtlich um {abs(price_change_percent):.0f}% "
            f"(von {current_price:.0f}€ auf ~{predicted_price:.0f}€). "
            f"In ~2 Wochen könnte es günstiger sein."
        )
        return (PredictionAdvice.WAIT, reason)

    elif is_near_minimum:
        # Preis ist nahe am historischen Minimum → jetzt buchen
        reason = (
            f"Aktueller Preis ({current_price:.0f}€) ist nahe am historischen "
            f"Minimum ({min_price:.0f}€). Günstiger wird es wahrscheinlich nicht."
        )
        return (PredictionAdvice.BOOK_NOW, reason)

    else:
        # Stabile Preise → unsicher
        reason = (
            f"Preise sind relativ stabil (±{abs(price_change_percent):.0f}%). "
            f"Kein klarer Trend erkennbar."
        )
        return (PredictionAdvice.UNCERTAIN, reason)
