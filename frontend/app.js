/**
 * FlugFinder Iran – PWA Frontend
 * Lädt Suchergebnisse aus data.json und zeigt sie an.
 */

const DATA_URL = "data.json";
let flightData = null;

// --- App Start ---
document.addEventListener("DOMContentLoaded", () => {
    loadData();
    setupFilters();
    registerServiceWorker();
});

// --- Daten laden ---
async function loadData() {
    try {
        const response = await fetch(DATA_URL);
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        flightData = await response.json();
        renderAll();
    } catch (error) {
        console.error("Fehler beim Laden:", error);
        document.getElementById("flights-body").innerHTML =
            '<tr><td colspan="7" class="loading">Noch keine Daten vorhanden. Die erste Suche läuft automatisch um 8:00 Uhr.</td></tr>';
    }
}

// --- Alles rendern ---
function renderAll() {
    if (!flightData) return;
    renderSummary();
    renderFlights(flightData.flights);
    renderPredictions();
    renderCombos();
    renderAnalysis();
    renderStatusBanner();
}

// --- Zusammenfassung ---
function renderSummary() {
    const data = flightData;

    // Letzte Suche
    const lastUpdated = new Date(data.last_updated);
    document.getElementById("last-updated").textContent =
        lastUpdated.toLocaleDateString("de-DE", { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" });

    // Ferien
    document.getElementById("holiday-period").textContent = data.holiday_period || "–";

    // Günstigster Preis
    const cheapest = data.summary?.cheapest_price;
    document.getElementById("cheapest-price").textContent =
        cheapest ? `${Math.round(cheapest)}€` : "–";

    // Bester Flughafen
    const airport = data.summary?.cheapest_airport;
    const airportNames = { HAJ: "Hannover", BER: "Berlin", HAM: "Hamburg", FRA: "Frankfurt" };
    document.getElementById("cheapest-airport").textContent =
        airport ? `${airportNames[airport] || airport} (${airport})` : "–";
}

// --- Status Banner ---
function renderStatusBanner() {
    const banner = document.getElementById("status-banner");
    const text = document.getElementById("status-text");

    if (flightData.summary?.has_alert) {
        banner.classList.remove("hidden");
        banner.classList.add("alert");
        text.textContent = "🚨 GÜNSTIG-ALARM! Es gibt besonders günstige Flüge!";
    } else if (flightData.flights?.length > 0) {
        banner.classList.remove("hidden");
        banner.classList.remove("alert");
        text.textContent = `✅ ${flightData.flights.length} Flüge gefunden – Daten aktuell`;
    }
}

// --- Flug-Tabelle ---
function renderFlights(flights) {
    const tbody = document.getElementById("flights-body");

    if (!flights || flights.length === 0) {
        tbody.innerHTML = '<tr><td colspan="7" class="loading">Keine Flüge gefunden</td></tr>';
        return;
    }

    tbody.innerHTML = flights.map(flight => {
        const isCheap = flight.is_very_cheap;
        const isWeekend = flight.is_weekend_flight;
        const isDirect = flight.stops_outbound === 0;

        // Badges
        let badges = "";
        if (isCheap) badges += '<span class="badge badge-cheap">GÜNSTIG</span> ';
        if (isWeekend) badges += '<span class="badge badge-weekend">Wochenende</span> ';
        if (isDirect) badges += '<span class="badge badge-direct">Direkt</span> ';

        // Gepäck
        const luggage = flight.luggage === "with_luggage" ? "🧳" : "🎒";

        // Dauer
        const durationH = Math.floor(flight.duration_outbound_min / 60);
        const durationM = flight.duration_outbound_min % 60;

        return `
            <tr class="${isCheap ? 'cheap' : ''}">
                <td><strong>${flight.departure_airport}</strong> → ${flight.destination_airport}</td>
                <td>${formatDate(flight.outbound_date)} – ${formatDate(flight.return_date)}</td>
                <td class="price-cell">${Math.round(flight.price_total)}€</td>
                <td>${flight.airline}</td>
                <td>${flight.stops_outbound === 0 ? 'Direkt' : flight.stops_outbound + ' Stopp'}</td>
                <td>${luggage}</td>
                <td>${badges || '–'}</td>
            </tr>
        `;
    }).join("");
}

// --- Filter ---
function setupFilters() {
    document.getElementById("filter-airport").addEventListener("change", applyFilters);
    document.getElementById("filter-luggage").addEventListener("change", applyFilters);
    document.getElementById("filter-destination").addEventListener("change", applyFilters);
}

function applyFilters() {
    if (!flightData?.flights) return;

    const airport = document.getElementById("filter-airport").value;
    const luggage = document.getElementById("filter-luggage").value;
    const destination = document.getElementById("filter-destination").value;

    let filtered = [...flightData.flights];

    if (airport !== "all") {
        filtered = filtered.filter(f => f.departure_airport === airport);
    }
    if (luggage !== "all") {
        filtered = filtered.filter(f => f.luggage === luggage);
    }
    if (destination !== "all") {
        filtered = filtered.filter(f => f.destination_airport === destination);
    }

    renderFlights(filtered);
}

// --- Vorhersagen ---
function renderPredictions() {
    const section = document.getElementById("prediction-section");
    const content = document.getElementById("prediction-content");

    if (!flightData.predictions || flightData.predictions.length === 0) {
        section.classList.add("hidden");
        return;
    }

    section.classList.remove("hidden");

    content.innerHTML = flightData.predictions.map(pred => {
        let cssClass = "uncertain";
        let icon = "❓";

        if (pred.advice === "book_now") {
            cssClass = "book-now";
            icon = "✅";
        } else if (pred.advice === "wait") {
            cssClass = "wait";
            icon = "⏳";
        }

        return `
            <div class="prediction-card ${cssClass}">
                <div class="prediction-advice">${icon} ${pred.route}: ${adviceText(pred.advice)}</div>
                <div class="prediction-reason">${pred.reason}</div>
            </div>
        `;
    }).join("");
}

function adviceText(advice) {
    const texts = {
        book_now: "Jetzt buchen!",
        wait: "Noch warten",
        uncertain: "Unsicher",
    };
    return texts[advice] || advice;
}

// --- Kombi-Tickets ---
function renderCombos() {
    const section = document.getElementById("combo-section");
    const content = document.getElementById("combo-content");

    if (!flightData.combo_tickets || flightData.combo_tickets.length === 0) {
        section.classList.add("hidden");
        return;
    }

    section.classList.remove("hidden");

    content.innerHTML = flightData.combo_tickets.map(combo => `
        <div class="combo-card">
            <div class="combo-route">
                Hin: ${combo.departure_airport} → ${combo.destination_airport} |
                Rück: ${combo.destination_airport} → ${combo.return_airport}
            </div>
            <div>
                💰 ${Math.round(combo.price_total)}€ –
                <span class="combo-savings">${Math.round(combo.savings)}€ gespart!</span>
            </div>
            <div class="info-text">
                ${formatDate(combo.outbound_date)} – ${formatDate(combo.return_date)}
            </div>
        </div>
    `).join("");
}

// --- Preis-Analyse ---
function renderAnalysis() {
    const section = document.getElementById("analysis-section");
    const content = document.getElementById("analysis-content");

    if (!flightData.price_analyses || flightData.price_analyses.length === 0) {
        section.classList.add("hidden");
        return;
    }

    section.classList.remove("hidden");

    content.innerHTML = flightData.price_analyses.map(analysis => {
        const trendIcon = {
            rising: "📈",
            falling: "📉",
            stable: "➡️",
            unknown: "❓",
        }[analysis.trend] || "❓";

        const diffText = analysis.percent_vs_average < 0
            ? `${Math.abs(analysis.percent_vs_average)}% günstiger`
            : `${analysis.percent_vs_average}% teurer`;

        return `
            <div class="analysis-item">
                <span class="analysis-route">${analysis.route}</span>
                <span class="analysis-trend">
                    ${trendIcon} ${Math.round(analysis.current_price)}€
                    (Ø ${Math.round(analysis.average_price)}€, ${diffText})
                </span>
            </div>
        `;
    }).join("");
}

// --- Hilfsfunktionen ---
function formatDate(dateStr) {
    if (!dateStr) return "–";
    const d = new Date(dateStr);
    return d.toLocaleDateString("de-DE", { day: "2-digit", month: "2-digit" });
}

// --- Service Worker registrieren ---
function registerServiceWorker() {
    if ("serviceWorker" in navigator) {
        navigator.serviceWorker.register("sw.js")
            .then(() => console.log("Service Worker registriert"))
            .catch(err => console.log("SW Registrierung fehlgeschlagen:", err));
    }
}

// --- Install Prompt (PWA) ---
let deferredPrompt;

window.addEventListener("beforeinstallprompt", (e) => {
    e.preventDefault();
    deferredPrompt = e;
    showInstallPrompt();
});

function showInstallPrompt() {
    // Nur anzeigen wenn noch nicht installiert
    if (window.matchMedia("(display-mode: standalone)").matches) return;

    const prompt = document.createElement("div");
    prompt.className = "install-prompt";
    prompt.innerHTML = `
        <span>📱 App installieren für schnellen Zugriff</span>
        <div>
            <button onclick="installApp()">Installieren</button>
            <button class="dismiss" onclick="this.parentElement.parentElement.remove()">Später</button>
        </div>
    `;
    document.body.appendChild(prompt);
}

async function installApp() {
    if (!deferredPrompt) return;
    deferredPrompt.prompt();
    const result = await deferredPrompt.userChoice;
    console.log("Install:", result.outcome);
    deferredPrompt = null;
    document.querySelector(".install-prompt")?.remove();
}
