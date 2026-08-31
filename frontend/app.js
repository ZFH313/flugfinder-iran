/**
 * FlugFinder Iran – PWA Frontend App
 * Zeigt Flüge gruppiert nach Ferienperiode mit Booking-Links.
 */
const DATA_URL = "data.json";
let flightData = null;

document.addEventListener("DOMContentLoaded", () => {
    loadData();
    setupTokenUI();
    if ("serviceWorker" in navigator) {
        navigator.serviceWorker.register("sw.js").catch(() => {});
    }
});

// ===================== DATEN LADEN =====================
async function loadData() {
    try {
        const r = await fetch(DATA_URL);
        if (!r.ok) throw new Error();
        flightData = await r.json();
        renderAll();
    } catch (e) {
        document.getElementById("holiday-cards-container").innerHTML =
            '<div class="card"><p class="loading">Noch keine Ergebnisse. Starte eine Suche oben ☝️</p></div>';
    }
}

function renderAll() {
    if (!flightData) return;
    renderSummary();
    renderHolidayCards();
    renderPredictions();
    renderPriceHistory();
    renderCombos();
    renderBanner();
}

// ===================== ZUSAMMENFASSUNG =====================
function renderSummary() {
    const d = flightData;
    const updated = new Date(d.last_updated);
    document.getElementById("last-updated").textContent =
        updated.toLocaleDateString("de-DE", {day:"2-digit", month:"2-digit", year:"numeric", hour:"2-digit", minute:"2-digit"});

    const holidayCount = d.holidays ? d.holidays.length : (d.holiday_period ? d.holiday_period.split("|").length : 0);
    document.getElementById("holiday-count").textContent = holidayCount + " Ferienzeiten";

    document.getElementById("cheapest-price").textContent =
        d.summary?.cheapest_price ? Math.round(d.summary.cheapest_price) + "€" : "–";
    const ap = d.summary?.cheapest_airport;
    const names = {HAJ:"Hannover",BER:"Berlin",HAM:"Hamburg",FRA:"Frankfurt"};
    document.getElementById("cheapest-airport").textContent = ap ? names[ap] || ap : "–";
}

function renderBanner() {
    const b = document.getElementById("status-banner");
    const t = document.getElementById("status-text");
    if (flightData.summary?.has_alert) {
        b.classList.remove("hidden"); b.classList.add("alert");
        t.textContent = "🚨 GÜNSTIG-ALARM! Besonders günstige Flüge gefunden!";
    } else if (flightData.flights?.length > 0 || flightData.holidays?.length > 0) {
        b.classList.remove("hidden");
        const total = flightData.summary?.total_flights || flightData.flights?.length || 0;
        t.textContent = "✅ " + total + " Flüge gefunden";
    }
}

// ===================== FERIEN-KARTEN =====================
function renderHolidayCards() {
    const container = document.getElementById("holiday-cards-container");

    if (flightData.holidays && flightData.holidays.length > 0) {
        container.innerHTML = flightData.holidays.map((holiday, idx) =>
            renderHolidayCard(holiday, idx)
        ).join("");
    } else if (flightData.flights && flightData.flights.length > 0) {
        container.innerHTML = renderLegacyFlightCard(flightData.flights);
    } else {
        container.innerHTML = '<div class="card"><p class="loading">Keine Flüge gefunden.</p></div>';
    }

    container.querySelectorAll(".holiday-filter").forEach(el => {
        el.addEventListener("change", (e) => {
            const cardIdx = e.target.closest(".holiday-card").dataset.idx;
            applyHolidayFilter(cardIdx);
        });
    });
}

function renderHolidayCard(holiday, idx) {
    const dateRange = fmtDateLong(holiday.start) + " – " + fmtDateLong(holiday.end);
    const flights = holiday.flights || [];
    const cheapest = flights.length > 0 ? Math.round(flights[0].price_total) + "€" : "–";
    const hasAlert = flights.some(f => f.is_very_cheap);
    const emoji = getHolidayEmoji(holiday.name);
    const colorClass = getHolidayColor(holiday.name);

    let extInfo = "";
    if (holiday.extended_start && holiday.extended_end) {
        extInfo = `<div class="ext-badge">📅 Mit Wochenende: ${fmtDate(holiday.extended_start)} – ${fmtDate(holiday.extended_end)}</div>`;
    }

    return `
    <section class="card holiday-card ${colorClass} ${hasAlert ? 'holiday-alert' : ''}" data-idx="${idx}">
        <div class="holiday-header">
            <div class="holiday-emoji">${emoji}</div>
            <div class="holiday-info">
                <h2>${holiday.name}</h2>
                <div class="holiday-meta">
                    <span class="holiday-dates">${dateRange}</span>
                    ${extInfo}
                </div>
            </div>
            <div class="holiday-price-badge ${hasAlert ? 'price-alert' : ''}">
                <span class="price-label">ab</span>
                <span class="price-value">${cheapest}</span>
                ${hasAlert ? '<span class="price-tag">DEAL!</span>' : ''}
            </div>
        </div>

        <div class="holiday-filters">
            <select class="holiday-filter" data-filter="airport" aria-label="Flughafen">
                <option value="all">Alle Abflughäfen</option>
                <option value="HAJ">✈️ Hannover</option>
                <option value="BER">✈️ Berlin</option>
                <option value="HAM">✈️ Hamburg</option>
                <option value="FRA">✈️ Frankfurt</option>
            </select>
            <select class="holiday-filter" data-filter="destination" aria-label="Ziel">
                <option value="all">Alle Ziele</option>
                <option value="IKA">🇮🇷 Teheran</option>
                <option value="MHD">🇮🇷 Mashhad</option>
            </select>
            <select class="holiday-filter" data-filter="luggage" aria-label="Gepäck">
                <option value="all">Alle</option>
                <option value="with_luggage">🧳 Mit Gepäck</option>
                <option value="without_luggage">🎒 Handgepäck</option>
            </select>
        </div>

        <div class="sort-bar">
            <span class="sort-label">Sortierung:</span>
            <button class="sort-btn active" data-sort="price" onclick="sortFlights(${idx}, 'price', this)">💰 Günstigste</button>
            <button class="sort-btn" data-sort="duration" onclick="sortFlights(${idx}, 'duration', this)">⏱️ Schnellste</button>
            <button class="sort-btn" data-sort="date" onclick="sortFlights(${idx}, 'date', this)">📅 Früheste</button>
        </div>

        <div class="flight-list" id="flights-${idx}">
            ${renderFlightCards(flights.slice(0, 8))}
        </div>

        ${flights.length > 8 ? `<button class="btn-show-more" onclick="showMoreFlights(${idx})">+ ${flights.length - 8} weitere Flüge anzeigen</button>` : ''}
    </section>`;
}

function renderFlightCards(flights) {
    if (!flights || !flights.length) {
        return '<p class="no-flights">Keine Flüge für diese Ferien gefunden.</p>';
    }
    return flights.map(f => {
        const badges = [];
        if (f.is_very_cheap) badges.push('<span class="badge badge-cheap">🔥 GÜNSTIG</span>');
        if (f.is_weekend_flight) badges.push('<span class="badge badge-weekend">WE-Flug</span>');
        if (f.stops_outbound === 0) badges.push('<span class="badge badge-direct">Direktflug</span>');
        const lug = f.luggage === "with_luggage" ? "🧳" : "🎒";
        const bookingUrl = buildBookingUrl(f);
        const hasDirectBooking = Boolean(f.booking_link);
        const airportNames = {HAJ:"Hannover",BER:"Berlin",HAM:"Hamburg",FRA:"Frankfurt",IKA:"Teheran",MHD:"Mashhad"};
        const durationHrs = f.duration_outbound_min ? Math.floor(f.duration_outbound_min / 60) + "h " + (f.duration_outbound_min % 60) + "m" : "";
        const sourceLabel = getSourceLabel(f.source);
        if (sourceLabel) badges.push(`<span class="badge badge-source">${sourceLabel}</span>`);

        return `
        <a href="${bookingUrl}" target="_blank" rel="noopener noreferrer" class="flight-card-link">
            <div class="flight-card ${f.is_very_cheap ? 'flight-cheap' : ''}">
                <div class="flight-card-top">
                    <div class="flight-route-info">
                        <div class="flight-airports">
                            <span class="airport-from">${f.departure_airport}</span>
                            <span class="flight-arrow">→</span>
                            <span class="airport-to">${f.destination_airport}</span>
                            <span class="luggage-icon">${lug}</span>
                        </div>
                        <div class="flight-airport-names">
                            ${airportNames[f.departure_airport] || f.departure_airport} → ${airportNames[f.destination_airport] || f.destination_airport}
                        </div>
                    </div>
                    <div class="flight-price-box">
                        <span class="flight-price">${Math.round(f.price_total)}€</span>
                        <span class="flight-price-pp">${Math.round(f.price_per_person)}€/Pers.</span>
                    </div>
                </div>
                <div class="flight-card-bottom">
                    <div class="flight-meta">
                        <span class="flight-dates-info">📅 ${fmtDate(f.outbound_date)} – ${fmtDate(f.return_date)}</span>
                        <span class="flight-airline-info">✈️ ${f.airline || 'Diverse'}</span>
                        <span class="flight-stops-info">${f.stops_outbound === 0 ? '🟢 Direkt' : '🔵 ' + f.stops_outbound + ' Stopp'}</span>
                        ${durationHrs ? '<span class="flight-duration">⏱️ ' + durationHrs + '</span>' : ''}
                    </div>
                    <div class="flight-badges">${badges.join(' ')}</div>
                </div>
                <div class="flight-book-hint">${hasDirectBooking ? 'Klicken zum Buchen →' : 'Klicken zum Suchen auf Google Flights →'}</div>
            </div>
        </a>`;
    }).join("");
}

function renderLegacyFlightCard(flights) {
    return `
    <section class="card holiday-card holiday-color-blue" data-idx="0">
        <div class="holiday-header">
            <div class="holiday-emoji">✈️</div>
            <div class="holiday-info">
                <h2>Suchergebnisse</h2>
                <div class="holiday-meta">
                    <span class="holiday-dates">${flightData.holiday_period || ''}</span>
                </div>
            </div>
            <div class="holiday-price-badge">
                <span class="price-label">ab</span>
                <span class="price-value">${flights.length > 0 ? Math.round(flights[0].price_total) + '€' : '–'}</span>
            </div>
        </div>
        <div class="flight-list" id="flights-0">
            ${renderFlightCards(flights.slice(0, 15))}
        </div>
    </section>`;
}

// ===================== BUCHUNGS-LINK =====================

// Anzeigenamen der Suchdienste
const SOURCE_LABELS = {
    serpapi: "Google Flights",
    skyscrapper: "Skyscanner",
};

function getSourceLabel(source) {
    if (!source) return "";
    return SOURCE_LABELS[source] || source;
}

function buildBookingUrl(flight) {
    // Liefert der Provider einen direkten Buchungslink, diesen nutzen
    if (flight.booking_link) {
        return flight.booking_link;
    }

    // Sonst: Google-Flights-Suche mit den passenden Reisenden vorbelegen
    const passengers = flightData?.summary?.passengers || {};
    const adults = passengers.adults || 2;
    const childrenAges = (passengers.children_ages || [5, 8]).join(",");

    const params = new URLSearchParams({
        hl: "de",
        gl: "de",
        curr: "EUR",
        type: "1",
        d: flight.departure_airport,
        a: flight.destination_airport,
        dd: flight.outbound_date,
        rd: flight.return_date,
        px: String(adults),
        cy: childrenAges,
        bags: flight.luggage === "with_luggage" ? "1" : "0",
    });

    return `https://www.google.com/travel/flights?${params.toString()}`;
}

// ===================== FILTER PRO KARTE =====================
function applyHolidayFilter(cardIdx) {
    const card = document.querySelector(`.holiday-card[data-idx="${cardIdx}"]`);
    if (!card) return;

    const apFilter = card.querySelector('[data-filter="airport"]').value;
    const destFilter = card.querySelector('[data-filter="destination"]').value;
    const lugFilter = card.querySelector('[data-filter="luggage"]').value;

    let flights = [];
    if (flightData.holidays && flightData.holidays[cardIdx]) {
        flights = [...flightData.holidays[cardIdx].flights];
    } else if (flightData.flights) {
        flights = [...flightData.flights];
    }

    if (apFilter !== "all") flights = flights.filter(f => f.departure_airport === apFilter);
    if (destFilter !== "all") flights = flights.filter(f => f.destination_airport === destFilter);
    if (lugFilter !== "all") flights = flights.filter(f => f.luggage === lugFilter);

    document.getElementById(`flights-${cardIdx}`).innerHTML = renderFlightCards(flights.slice(0, 8));
}

function showMoreFlights(idx) {
    if (!flightData.holidays || !flightData.holidays[idx]) return;
    const flights = flightData.holidays[idx].flights;
    document.getElementById(`flights-${idx}`).innerHTML = renderFlightCards(flights);
    const card = document.querySelector(`.holiday-card[data-idx="${idx}"]`);
    const btn = card.querySelector('.btn-show-more');
    if (btn) btn.remove();
}

// ===================== VORHERSAGE =====================
function renderPredictions() {
    const s = document.getElementById("prediction-section");
    const c = document.getElementById("prediction-content");
    if (!flightData.predictions?.length) { s.classList.add("hidden"); return; }
    s.classList.remove("hidden");
    c.innerHTML = flightData.predictions.map(p => {
        let css="uncertain",icon="❓",txt="Unsicher";
        if (p.advice==="book_now"){css="book-now";icon="✅";txt="Jetzt buchen!";}
        else if (p.advice==="wait"){css="wait";icon="⏳";txt="Noch warten";}
        return `<div class="prediction-card ${css}"><div class="prediction-advice">${icon} ${p.route}: ${txt}</div><div class="prediction-reason">${p.reason}</div></div>`;
    }).join("");
}

// ===================== PREIS-VERLAUF =====================
function renderPriceHistory() {
    const s = document.getElementById("price-history-section");
    const c = document.getElementById("price-history-content");
    if (!flightData.price_analyses?.length) { s.classList.add("hidden"); return; }
    s.classList.remove("hidden");

    // Finde min/max für Skalierung
    const prices = flightData.price_analyses.map(a => a.current_price);
    const avgPrices = flightData.price_analyses.map(a => a.average_price);
    const allPrices = [...prices, ...avgPrices];
    const maxPrice = Math.max(...allPrices);
    const minPrice = Math.min(...allPrices) * 0.8;

    const trendIcons = {rising:"📈", falling:"📉", stable:"➡️", unknown:"❓"};

    c.innerHTML = flightData.price_analyses.map(a => {
        const currentPct = ((a.current_price - minPrice) / (maxPrice - minPrice)) * 100;
        const avgPct = ((a.average_price - minPrice) / (maxPrice - minPrice)) * 100;
        const diff = a.percent_vs_average;
        const diffText = diff < 0 ? `${Math.abs(diff).toFixed(0)}% günstiger` : `${diff.toFixed(0)}% teurer`;
        const diffClass = diff < 0 ? "price-cheaper" : diff > 0 ? "price-expensive" : "";
        const icon = trendIcons[a.trend] || "❓";

        return `
        <div class="price-bar-row">
            <div class="price-bar-label">
                <span class="price-bar-route">${a.route}</span>
                <span class="price-bar-trend">${icon} ${diffText}</span>
            </div>
            <div class="price-bar-container">
                <div class="price-bar price-bar-avg" style="width: ${avgPct}%">
                    <span class="price-bar-text">Ø ${Math.round(a.average_price)}€</span>
                </div>
                <div class="price-bar price-bar-current ${diffClass}" style="width: ${currentPct}%">
                    <span class="price-bar-text">Jetzt ${Math.round(a.current_price)}€</span>
                </div>
            </div>
        </div>`;
    }).join("");
}

// ===================== KOMBI =====================
function renderCombos() {
    const s = document.getElementById("combo-section");
    const c = document.getElementById("combo-content");
    if (!flightData.combo_tickets?.length) { s.classList.add("hidden"); return; }
    s.classList.remove("hidden");
    c.innerHTML = flightData.combo_tickets.map(x =>
        `<div class="combo-card"><div class="combo-route">✈️ Hin: ${x.departure_airport} → ${x.destination_airport} | Rück: → ${x.return_airport}</div><div class="combo-price">💰 ${Math.round(x.price_total)}€ – <span class="combo-savings">${Math.round(x.savings)}€ gespart!</span></div></div>`
    ).join("");
}

// ===================== HELFER =====================
function fmtDate(d) {
    if (!d) return "–";
    return new Date(d).toLocaleDateString("de-DE", {day:"2-digit", month:"2-digit"});
}

function fmtDateLong(d) {
    if (!d) return "–";
    return new Date(d).toLocaleDateString("de-DE", {day:"2-digit", month:"long", year:"numeric"});
}

function getHolidayEmoji(name) {
    if (!name) return "📅";
    const n = name.toLowerCase();
    if (n.includes("sommer")) return "☀️";
    if (n.includes("herbst")) return "🍂";
    if (n.includes("weihnacht") || n.includes("winter")) return "❄️";
    if (n.includes("oster")) return "🐣";
    if (n.includes("pfingst")) return "🌸";
    return "📅";
}

function getHolidayColor(name) {
    if (!name) return "holiday-color-blue";
    const n = name.toLowerCase();
    if (n.includes("sommer")) return "holiday-color-orange";
    if (n.includes("herbst")) return "holiday-color-amber";
    if (n.includes("weihnacht") || n.includes("winter")) return "holiday-color-blue";
    if (n.includes("oster")) return "holiday-color-green";
    if (n.includes("pfingst")) return "holiday-color-purple";
    return "holiday-color-blue";
}

// ===================== SORTIERUNG =====================
function sortFlights(idx, sortBy, btnEl) {
    // Active-Button aktualisieren
    const card = btnEl.closest('.holiday-card');
    card.querySelectorAll('.sort-btn').forEach(b => b.classList.remove('active'));
    btnEl.classList.add('active');

    let flights = [];
    if (flightData.holidays && flightData.holidays[idx]) {
        flights = [...flightData.holidays[idx].flights];
    } else if (flightData.flights) {
        flights = [...flightData.flights];
    }

    // Filter anwenden (falls gesetzt)
    const apFilter = card.querySelector('[data-filter="airport"]')?.value || "all";
    const destFilter = card.querySelector('[data-filter="destination"]')?.value || "all";
    const lugFilter = card.querySelector('[data-filter="luggage"]')?.value || "all";
    if (apFilter !== "all") flights = flights.filter(f => f.departure_airport === apFilter);
    if (destFilter !== "all") flights = flights.filter(f => f.destination_airport === destFilter);
    if (lugFilter !== "all") flights = flights.filter(f => f.luggage === lugFilter);

    // Sortieren
    switch (sortBy) {
        case 'price':
            flights.sort((a, b) => a.price_total - b.price_total);
            break;
        case 'duration':
            flights.sort((a, b) => (a.duration_outbound_min || 999) - (b.duration_outbound_min || 999));
            break;
        case 'date':
            flights.sort((a, b) => a.outbound_date.localeCompare(b.outbound_date));
            break;
    }

    document.getElementById(`flights-${idx}`).innerHTML = renderFlightCards(flights.slice(0, 8));
}

// ===================== SUCHE + TOKEN =====================
function setupTokenUI() {
    const token = localStorage.getItem("github_pat");
    if (token) {
        document.getElementById("token-setup").style.display = "none";
        document.getElementById("token-saved").classList.remove("hidden");
    } else {
        document.getElementById("token-setup").style.display = "block";
        document.getElementById("token-saved").classList.add("hidden");
    }
}

function saveToken() {
    const input = document.getElementById("github-token");
    const token = input.value.trim();
    if (!token) { alert("Bitte Token eingeben!"); return; }
    localStorage.setItem("github_pat", token);
    input.value = "";
    setupTokenUI();
    showStatus("✅ Token gespeichert! Du kannst jetzt suchen.", "success");
}

function resetToken() {
    localStorage.removeItem("github_pat");
    setupTokenUI();
}

async function triggerManualSearch() {
    const outbound = document.getElementById("search-outbound").value;
    const returnDate = document.getElementById("search-return").value;
    const btn = document.getElementById("btn-search");

    if (!outbound || !returnDate) { showStatus("Bitte beide Daten wählen!", "error"); return; }
    if (returnDate <= outbound) { showStatus("Rückflug muss nach Hinflug sein!", "error"); return; }

    const pat = localStorage.getItem("github_pat");
    if (!pat) {
        showStatus("⚠️ Bitte erst den GitHub Token eingeben (unten aufklappen).", "error");
        document.querySelector(".token-help").open = true;
        return;
    }

    btn.disabled = true;
    btn.textContent = "⏳ Wird gestartet...";
    showStatus("Suche wird gestartet...", "pending");

    try {
        const owner = window.location.hostname.split(".")[0];
        const pathParts = window.location.pathname.split("/").filter(Boolean);
        const repo = pathParts[0] || "flugfinder-iran";
        const dates = outbound + ":" + returnDate;

        const response = await fetch(
            "https://api.github.com/repos/" + owner + "/" + repo + "/actions/workflows/daily_search.yml/dispatches",
            {
                method: "POST",
                headers: {
                    "Authorization": "token " + pat,
                    "Accept": "application/vnd.github.v3+json",
                    "Content-Type": "application/json"
                },
                body: JSON.stringify({ ref: "main", inputs: { dates: dates } })
            }
        );

        if (response.status === 204) {
            showStatus("✅ Suche läuft! Ergebnis in 3-5 Min.", "success");
        } else if (response.status === 401 || response.status === 403) {
            localStorage.removeItem("github_pat");
            setupTokenUI();
            showStatus("❌ Token ungültig.", "error");
        } else {
            showStatus("❌ Fehler " + response.status, "error");
        }
    } catch (err) {
        showStatus("❌ " + err.message, "error");
    }

    btn.disabled = false;
    btn.textContent = "✈️ Suche starten";
}

function showStatus(msg, type) {
    const el = document.getElementById("search-status");
    el.textContent = msg;
    el.className = "search-status " + type;
    el.classList.remove("hidden");
}
