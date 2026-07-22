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
    setupTokenUI();
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
        document.getElementById("flights-body").innerHTML =
            '<tr><td colspan="7" class="loading">Noch keine Ergebnisse. Starte eine Suche oben!</td></tr>';
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
    const lastUpdated = new Date(flightData.last_updated);
    document.getElementById("last-updated").textContent =
        lastUpdated.toLocaleDateString("de-DE", { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" });
    document.getElementById("holiday-period").textContent = flightData.holiday_period || "–";

    const cheapest = flightData.summary?.cheapest_price;
    document.getElementById("cheapest-price").textContent = cheapest ? `${Math.round(cheapest)}€` : "–";

    const airport = flightData.summary?.cheapest_airport;
    const names = { HAJ: "Hannover", BER: "Berlin", HAM: "Hamburg", FRA: "Frankfurt" };
    document.getElementById("cheapest-airport").textContent = airport ? `${names[airport] || airport}` : "–";
}

function renderStatusBanner() {
    const banner = document.getElementById("status-banner");
    const text = document.getElementById("status-text");
    if (flightData.summary?.has_alert) {
        banner.classList.remove("hidden");
        banner.classList.add("alert");
        text.textContent = "🚨 GÜNSTIG-ALARM! Besonders günstige Flüge gefunden!";
    } else if (flightData.flights?.length > 0) {
        banner.classList.remove("hidden");
        text.textContent = `✅ ${flightData.flights.length} Flüge gefunden`;
    }
}

// --- Flug-Tabelle ---
function renderFlights(flights) {
    const tbody = document.getElementById("flights-body");
    if (!flights || flights.length === 0) {
        tbody.innerHTML = '<tr><td colspan="7" class="loading">Keine Flüge gefunden</td></tr>';
        return;
    }
    tbody.innerHTML = flights.map(f => {
        const isCheap = f.is_very_cheap;
        let badges = "";
        if (isCheap) badges += '<span class="badge badge-cheap">GÜNSTIG</span> ';
        if (f.is_weekend_flight) badges += '<span class="badge badge-weekend">WE</span> ';
        if (f.stops_outbound === 0) badges += '<span class="badge badge-direct">Direkt</span> ';
        const luggage = f.luggage === "with_luggage" ? "🧳" : "🎒";
        return `<tr class="${isCheap ? 'cheap' : ''}">
            <td><strong>${f.departure_airport}</strong>→${f.destination_airport}</td>
            <td>${formatDate(f.outbound_date)}–${formatDate(f.return_date)}</td>
            <td class="price-cell">${Math.round(f.price_total)}€</td>
            <td>${f.airline}</td>
            <td>${f.stops_outbound === 0 ? 'Direkt' : f.stops_outbound + 'x'}</td>
            <td>${luggage}</td>
            <td>${badges || '–'}</td>
        </tr>`;
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
    let filtered = [...flightData.flights];
    const airport = document.getElementById("filter-airport").value;
    const luggage = document.getElementById("filter-luggage").value;
    const dest = document.getElementById("filter-destination").value;
    if (airport !== "all") filtered = filtered.filter(f => f.departure_airport === airport);
    if (luggage !== "all") filtered = filtered.filter(f => f.luggage === luggage);
    if (dest !== "all") filtered = filtered.filter(f => f.destination_airport === dest);
    renderFlights(filtered);
}

// --- Vorhersagen ---
function renderPredictions() {
    const section = document.getElementById("prediction-section");
    const content = document.getElementById("prediction-content");
    if (!flightData.predictions || flightData.predictions.length === 0) { section.classList.add("hidden"); return; }
    section.classList.remove("hidden");
    content.innerHTML = flightData.predictions.map(p => {
        let css = "uncertain", icon = "❓";
        if (p.advice === "book_now") { css = "book-now"; icon = "✅"; }
        else if (p.advice === "wait") { css = "wait"; icon = "⏳"; }
        return `<div class="prediction-card ${css}"><div class="prediction-advice">${icon} ${p.route}: ${p.advice === "book_now" ? "Jetzt buchen!" : p.advice === "wait" ? "Noch warten" : "Unsicher"}</div><div class="prediction-reason">${p.reason}</div></div>`;
    }).join("");
}

// --- Kombi-Tickets ---
function renderCombos() {
    const section = document.getElementById("combo-section");
    const content = document.getElementById("combo-content");
    if (!flightData.combo_tickets || flightData.combo_tickets.length === 0) { section.classList.add("hidden"); return; }
    section.classList.remove("hidden");
    content.innerHTML = flightData.combo_tickets.map(c => `<div class="combo-card"><div class="combo-route">Hin: ${c.departure_airport}→${c.destination_airport} | Rück: →${c.return_airport}</div><div>💰 ${Math.round(c.price_total)}€ – <span class="combo-savings">${Math.round(c.savings)}€ gespart!</span></div></div>`).join("");
}

// --- Preis-Analyse ---
function renderAnalysis() {
    const section = document.getElementById("analysis-section");
    const content = document.getElementById("analysis-content");
    if (!flightData.price_analyses || flightData.price_analyses.length === 0) { section.classList.add("hidden"); return; }
    section.classList.remove("hidden");
    const icons = { rising: "📈", falling: "📉", stable: "➡️", unknown: "❓" };
    content.innerHTML = flightData.price_analyses.map(a => {
        const diff = a.percent_vs_average < 0 ? `${Math.abs(a.percent_vs_average)}% günstiger` : `${a.percent_vs_average}% teurer`;
        return `<div class="analysis-item"><span class="analysis-route">${a.route}</span><span class="analysis-trend">${icons[a.trend] || "❓"} ${Math.round(a.current_price)}€ (Ø ${Math.round(a.average_price)}€, ${diff})</span></div>`;
    }).join("");
}

// --- Hilfsfunktionen ---
function formatDate(d) { if (!d) return "–"; return new Date(d).toLocaleDateString("de-DE", { day: "2-digit", month: "2-digit" }); }

// --- Service Worker ---
function registerServiceWorker() {
    if ("serviceWorker" in navigator) {
        navigator.serviceWorker.register("sw.js").catch(() => {});
    }
}


// ============================================================
// MANUELLE SUCHE – Token-Verwaltung und GitHub Actions Trigger
// ============================================================

function setupTokenUI() {
    // Prüfe ob Token schon gespeichert ist
    const token = localStorage.getItem("github_pat");
    if (token) {
        document.getElementById("token-saved").classList.remove("hidden");
        document.getElementById("token-setup").classList.add("hidden");
    } else {
        document.getElementById("token-setup").classList.remove("hidden");
        document.getElementById("token-saved").classList.add("hidden");
    }
}

function saveToken() {
    const input = document.getElementById("github-token");
    const token = input.value.trim();

    if (!token) {
        alert("Bitte Token eingeben!");
        return;
    }

    if (!token.startsWith("ghp_") && !token.startsWith("github_pat_")) {
        alert("Das sieht nicht wie ein GitHub Token aus. Er beginnt normalerweise mit 'ghp_' oder 'github_pat_'");
        return;
    }

    localStorage.setItem("github_pat", token);
    input.value = "";

    // UI aktualisieren
    document.getElementById("token-setup").classList.add("hidden");
    document.getElementById("token-saved").classList.remove("hidden");

    showSearchStatus("✅ Token gespeichert! Du kannst jetzt Suchen starten.", "success");
}

function resetToken() {
    localStorage.removeItem("github_pat");
    document.getElementById("token-setup").classList.remove("hidden");
    document.getElementById("token-saved").classList.add("hidden");
}

async function triggerManualSearch() {
    const outbound = document.getElementById("search-outbound").value;
    const returnDate = document.getElementById("search-return").value;
    const btn = document.getElementById("btn-search");

    // Validierung
    if (!outbound || !returnDate) {
        showSearchStatus("❌ Bitte beide Daten auswählen!", "error");
        return;
    }
    if (returnDate <= outbound) {
        showSearchStatus("❌ Rückflug muss nach dem Hinflug sein!", "error");
        return;
    }
    const diffDays = (new Date(returnDate) - new Date(outbound)) / (1000 * 60 * 60 * 24);
    if (diffDays < 3) {
        showSearchStatus("❌ Mindestens 3 Tage Reisedauer!", "error");
        return;
    }

    // Token prüfen
    const pat = localStorage.getItem("github_pat");
    if (!pat) {
        showSearchStatus("⚠️ Bitte erst unten den GitHub Token eingeben.", "error");
        document.getElementById("token-setup").classList.remove("hidden");
        return;
    }

    // Suche starten
    const dates = `${outbound}:${returnDate}`;
    btn.disabled = true;
    btn.textContent = "⏳ Wird gestartet...";
    showSearchStatus("Suche wird auf dem Server gestartet...", "pending");

    try {
        const owner = window.location.hostname.split(".")[0];
        const repo = window.location.pathname.split("/").filter(Boolean)[0] || "flugfinder-iran";

        const response = await fetch(
            `https://api.github.com/repos/${owner}/${repo}/actions/workflows/daily_search.yml/dispatches`,
            {
                method: "POST",
                headers: {
                    "Authorization": `token ${pat}`,
                    "Accept": "application/vnd.github.v3+json",
                    "Content-Type": "application/json",
                },
                body: JSON.stringify({ ref: "main", inputs: { dates: dates } }),
            }
        );

        if (response.status === 204) {
            showSearchStatus(
                `✅ Suche gestartet! ${outbound} → ${returnDate}. Ergebnisse kommen in 3-5 Minuten per Telegram + hier in der App.`,
                "success"
            );
        } else if (response.status === 401 || response.status === 403) {
            localStorage.removeItem("github_pat");
            setupTokenUI();
            showSearchStatus("❌ Token ungültig oder abgelaufen. Bitte neuen Token eingeben.", "error");
        } else if (response.status === 404) {
            showSearchStatus("❌ Workflow nicht gefunden. Ist die Datei .github/workflows/daily_search.yml vorhanden?", "error");
        } else {
            showSearchStatus("❌ Unbekannter Fehler. Versuche es auf GitHub → Actions manuell.", "error");
        }
    } catch (error) {
        showSearchStatus("❌ Keine Verbindung: " + error.message, "error");
    }

    btn.disabled = false;
    btn.textContent = "✈️ Suche starten";
}

function showSearchStatus(message, type) {
    const el = document.getElementById("search-status");
    el.textContent = message;
    el.className = `search-status ${type}`;
    el.classList.remove("hidden");
}
