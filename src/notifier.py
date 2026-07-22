"""
Telegram Bot Benachrichtigungen.
Sendet tägliche Zusammenfassungen und Günstig-Alarme.
"""

import logging
from pathlib import Path

import requests

from .config import TelegramConfig
from .models import (
    ComboTicket,
    FlightOffer,
    LuggageType,
    PriceAnalysis,
    PricePrediction,
    PriceTrend,
    PredictionAdvice,
    SearchResult,
)

logger = logging.getLogger(__name__)

TELEGRAM_API_URL = "https://api.telegram.org/bot{token}"


class TelegramNotifier:
    """Sendet Benachrichtigungen über Telegram Bot API."""

    def __init__(self, config: TelegramConfig):
        self.config = config
        self.base_url = TELEGRAM_API_URL.format(token=config.bot_token)

    def send_message(self, text: str, parse_mode: str = "HTML") -> bool:
        """
        Sendet eine Textnachricht an den konfigurierten Chat.

        Args:
            text: Nachrichtentext (HTML oder Markdown)
            parse_mode: "HTML" oder "Markdown"

        Returns:
            True bei Erfolg, False bei Fehler
        """
        if not self.config.is_configured():
            logger.warning("Telegram nicht konfiguriert – Nachricht übersprungen")
            return False

        url = f"{self.base_url}/sendMessage"
        payload = {
            "chat_id": self.config.chat_id,
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": True,
        }

        try:
            response = requests.post(url, json=payload, timeout=30)
            response.raise_for_status()
            logger.info("Telegram Nachricht gesendet")
            return True
        except requests.RequestException as e:
            logger.error(f"Telegram Nachricht fehlgeschlagen: {e}")
            return False

    def send_photo(self, photo_path: str, caption: str = "") -> bool:
        """
        Sendet ein Bild (z.B. Preis-Trend-Graph) an den Chat.

        Args:
            photo_path: Pfad zum Bild
            caption: Bildunterschrift

        Returns:
            True bei Erfolg
        """
        if not self.config.is_configured():
            logger.warning("Telegram nicht konfiguriert – Bild übersprungen")
            return False

        file_path = Path(photo_path)
        if not file_path.exists():
            logger.error(f"Bild nicht gefunden: {photo_path}")
            return False

        url = f"{self.base_url}/sendPhoto"

        try:
            with open(file_path, "rb") as photo:
                files = {"photo": photo}
                data = {
                    "chat_id": self.config.chat_id,
                    "caption": caption,
                    "parse_mode": "HTML",
                }
                response = requests.post(url, data=data, files=files, timeout=60)
                response.raise_for_status()

            logger.info(f"Telegram Bild gesendet: {photo_path}")
            return True
        except requests.RequestException as e:
            logger.error(f"Telegram Bild senden fehlgeschlagen: {e}")
            return False


def send_daily_summary(notifier: TelegramNotifier, result: SearchResult) -> bool:
    """
    Sendet die tägliche Zusammenfassung mit dem günstigsten Flug.
    """
    cheapest = result.cheapest_flight
    if not cheapest:
        text = (
            "🔍 <b>FlugFinder Tagesreport</b>\n"
            f"📅 {result.search_date.strftime('%d.%m.%Y')}\n\n"
            "❌ Keine Flüge gefunden heute."
        )
        return notifier.send_message(text)

    # Günstigster mit/ohne Gepäck
    cheapest_with = result.cheapest_with_luggage
    cheapest_without = result.cheapest_without_luggage

    # Trend-Info
    trend_emoji = _trend_emoji(result.price_analyses)
    trend_text = _trend_text(result.price_analyses)

    # Vorhersage-Info
    prediction_text = _prediction_text(result.predictions)

    # Hauptnachricht
    text = (
        f"🔍 <b>FlugFinder Tagesreport</b>\n"
        f"📅 {result.search_date.strftime('%d.%m.%Y')}\n"
    )

    if result.holiday_period:
        text += f"🏖 Ferien: {result.holiday_period}\n"

    text += "\n"

    # Günstigster Flug
    text += (
        f"✈️ <b>Günstigster Flug:</b>\n"
        f"   {cheapest.departure_airport} → {cheapest.destination_airport}\n"
        f"   📅 {cheapest.outbound_date.strftime('%d.%m')} – {cheapest.return_date.strftime('%d.%m.%Y')}\n"
        f"   🏢 {cheapest.airline}\n"
        f"   💰 <b>{cheapest.price_total:.0f}€</b> (4 Personen)\n"
    )

    if cheapest.stops_outbound == 0:
        text += "   ✅ Direktflug (Hin)\n"
    else:
        text += f"   🔄 {cheapest.stops_outbound} Stopp(s) (Hin)\n"

    text += "\n"

    # Mit/Ohne Gepäck Vergleich
    if cheapest_with and cheapest_without:
        text += (
            f"🧳 Mit Gepäck: <b>{cheapest_with.price_total:.0f}€</b> "
            f"({cheapest_with.departure_airport}→{cheapest_with.destination_airport})\n"
            f"🎒 Ohne Gepäck: <b>{cheapest_without.price_total:.0f}€</b> "
            f"({cheapest_without.departure_airport}→{cheapest_without.destination_airport})\n\n"
        )

    # Trend
    if trend_text:
        text += f"{trend_emoji} Trend: {trend_text}\n"

    # Vorhersage
    if prediction_text:
        text += f"🔮 {prediction_text}\n"

    # Wochenend-Option
    weekend_flights = [f for f in result.flights if f.is_weekend_flight]
    if weekend_flights:
        best_weekend = min(weekend_flights, key=lambda f: f.price_total)
        text += (
            f"\n🗓 <b>Wochenend-Option:</b>\n"
            f"   {best_weekend.departure_airport}→{best_weekend.destination_airport} "
            f"am {best_weekend.outbound_date.strftime('%d.%m')} (Fr/Sa) – "
            f"{best_weekend.return_date.strftime('%d.%m')} (So)\n"
            f"   💰 {best_weekend.price_total:.0f}€\n"
        )

    # Kombi-Tickets
    if result.combo_tickets:
        best_combo = result.combo_tickets[0]
        text += (
            f"\n🔀 <b>Kombi-Ticket Tipp:</b>\n"
            f"   Hin: {best_combo.departure_airport}→{best_combo.destination_airport}\n"
            f"   Rück: {best_combo.destination_airport}→{best_combo.return_airport}\n"
            f"   💰 {best_combo.price_total:.0f}€ "
            f"(💚 {best_combo.savings:.0f}€ gespart!)\n"
        )

    # Statistik
    text += (
        f"\n📊 {len(result.flights)} Flüge durchsucht | "
        f"{result.duration_seconds:.0f}s Suchzeit"
    )

    return notifier.send_message(text)


def send_cheap_alert(notifier: TelegramNotifier, flight: FlightOffer) -> bool:
    """
    Sendet einen Günstig-Alarm für einen besonders günstigen Flug.
    """
    luggage_text = "mit Gepäck" if flight.luggage_type == LuggageType.WITH_LUGGAGE else "ohne Gepäck"

    text = (
        f"🚨 <b>GÜNSTIG-ALARM!</b> 🚨\n\n"
        f"✈️ {flight.departure_airport} → {flight.destination_airport}\n"
        f"📅 {flight.outbound_date.strftime('%d.%m.%Y')} – {flight.return_date.strftime('%d.%m.%Y')}\n"
        f"🏢 {flight.airline}\n"
        f"💰 <b>{flight.price_total:.0f}€</b> für 4 Personen ({luggage_text})\n"
        f"📉 <b>{flight.savings_percent:.0f}%</b> unter Durchschnitt!\n"
    )

    if flight.stops_outbound == 0:
        text += "✅ Direktflug (Hin)\n"

    if flight.is_weekend_flight:
        text += "🗓 Wochenend-Flug (Fr/Sa → So)\n"

    if flight.booking_link:
        text += f"\n🔗 <a href='{flight.booking_link}'>Jetzt buchen</a>"

    return notifier.send_message(text)


def send_price_graph(notifier: TelegramNotifier, graph_path: str) -> bool:
    """Sendet den Preis-Trend-Graphen als Bild."""
    caption = "📈 <b>Preisverlauf der letzten Wochen</b>\nRote Linie = Preislimit (1.500€)"
    return notifier.send_photo(graph_path, caption)


def _trend_emoji(analyses: list[PriceAnalysis]) -> str:
    """Gibt ein Trend-Emoji zurück basierend auf den Analysen."""
    if not analyses:
        return "❓"

    trends = [a.trend for a in analyses if a.trend != PriceTrend.UNKNOWN]
    if not trends:
        return "❓"

    # Mehrheitstrend
    rising = sum(1 for t in trends if t == PriceTrend.RISING)
    falling = sum(1 for t in trends if t == PriceTrend.FALLING)

    if falling > rising:
        return "📉"
    elif rising > falling:
        return "📈"
    else:
        return "➡️"


def _trend_text(analyses: list[PriceAnalysis]) -> str:
    """Generiert einen kurzen Trend-Text."""
    if not analyses:
        return ""

    trends = [a.trend for a in analyses if a.trend != PriceTrend.UNKNOWN]
    if not trends:
        return "Nicht genug Daten für Trend"

    rising = sum(1 for t in trends if t == PriceTrend.RISING)
    falling = sum(1 for t in trends if t == PriceTrend.FALLING)
    stable = sum(1 for t in trends if t == PriceTrend.STABLE)

    if falling > rising and falling > stable:
        return "Preise fallen auf den meisten Routen"
    elif rising > falling and rising > stable:
        return "Preise steigen auf den meisten Routen"
    else:
        return "Preise relativ stabil"


def _prediction_text(predictions: list[PricePrediction]) -> str:
    """Generiert einen kurzen Vorhersage-Text."""
    if not predictions:
        return ""

    # Nimm die Vorhersage mit der höchsten Konfidenz
    best = max(predictions, key=lambda p: p.confidence)

    if best.advice == PredictionAdvice.BOOK_NOW:
        return f"Empfehlung: <b>Jetzt buchen!</b> ({best.reason[:80]})"
    elif best.advice == PredictionAdvice.WAIT:
        return f"Empfehlung: <b>Noch warten</b> ({best.reason[:80]})"
    else:
        return f"Vorhersage unsicher ({best.reason[:60]})"
