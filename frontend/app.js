/**
 * FlugFinder Iran – PWA Frontend App
 */
const DATA_URL = "data.json";
let flightData = null;

document.addEventListener("DOMContentLoaded", () => {
    loadData();
    setupFilters();
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
        document.getElementById("flights-body").innerHTML =
            '<tr><td colspan="6" class="loading">Noch keine Ergebnisse. Starte eine Suche oben ☝️</td></tr>';
    }
}

function renderAll() {
    if (!flightData) return;
    renderSummary();
    renderFlights(flightData.flights);
    renderPredictions();
    renderCombos();
    renderAnalysis();
    renderBanner();
}

// ===================== ZUSAMMENFASSUNG =====================
function renderSummary() {
    const d = flightData;
    const updated = new Date(d.last_updated);
    document.getElementById("last-updated").textContent =
        updated.toLocaleDateString("de-DE", {day:"2-digit", month:"2-digit", year:"numeric", hour:"2-digit", minute:"2-digit"});
    document.getElementById("holiday-period").textContent = d.holiday_period || "–";
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
    } else if (flightData.flights?.length > 0) {
        b.classList.remove("hidden");
        t.textContent = "✅ " + flightData.flights.length + " Flüge gefunden";
    }
}

// ===================== FLUGTABELLE =====================
function renderFlights(flights) {
    const tbody = document.getElementById("flights-body");
    if (!flights || !flights.length) {
        tbody.innerHTML = '<tr><td colspan="6" class="loading">Keine Flüge</td></tr>';
        return;
    }
    tbody.innerHTML = flights.map(f => {
        let badges = "";
        if (f.is_very_cheap) badges += '<span class="badge badge-cheap">GÜNSTIG</span> ';
        if (f.is_weekend_flight) badges += '<span class="badge badge-weekend">WE</span> ';
        if (f.stops_outbound === 0) badges += '<span class="badge badge-direct">Direkt</span> ';
        const lug = f.luggage === "with_luggage" ? "🧳" : "🎒";
        return `<tr class="${f.is_very_cheap ? 'cheap' : ''}">
            <td><strong>${f.departure_airport}</strong>→${f.destination_airport} ${lug}</td>
            <td>${fmtDate(f.outbound_date)}–${fmtDate(f.return_date)}</td>
            <td class="price-cell">${Math.round(f.price_total)}€</td>
            <td>${f.airline}</td>
            <td>${f.stops_outbound === 0 ? '✈️' : f.stops_outbound + 'x'}</td>
            <td>${badges || '–'}</td>
        </tr>`;
    }).join("");
}

// ===================== FILTER =====================
function setupFilters() {
    document.getElementById("filter-airport").addEventListener("change", applyFilters);
    document.getElementById("filter-luggage").addEventListener("change", applyFilters);
    document.getElementById("filter-destination").addEventListener("change", applyFilters);
}
function applyFilters() {
    if (!flightData?.flights) return;
    let f = [...flightData.flights];
    const ap = document.getElementById("filter-airport").value;
    const lg = document.getElementById("filter-luggage").value;
    const ds = document.getElementById("filter-destination").value;
    if (ap !== "all") f = f.filter(x => x.departure_airport === ap);
    if (lg !== "all") f = f.filter(x => x.luggage === lg);
    if (ds !== "all") f = f.filter(x => x.destination_airport === ds);
    renderFlights(f);
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

// ===================== KOMBI =====================
function renderCombos() {
    const s = document.getElementById("combo-section");
    const c = document.getElementById("combo-content");
    if (!flightData.combo_tickets?.length) { s.classList.add("hidden"); return; }
    s.classList.remove("hidden");
    c.innerHTML = flightData.combo_tickets.map(x =>
        `<div class="combo-card"><div class="combo-route">Hin: ${x.departure_airport}→${x.destination_airport} | Rück: →${x.return_airport}</div><div>💰 ${Math.round(x.price_total)}€ – <span class="combo-savings">${Math.round(x.savings)}€ gespart!</span></div></div>`
    ).join("");
}

// ===================== ANALYSE =====================
function renderAnalysis() {
    const s = document.getElementById("analysis-section");
    const c = document.getElementById("analysis-content");
    if (!flightData.price_analyses?.length) { s.classList.add("hidden"); return; }
    s.classList.remove("hidden");
    const icons = {rising:"📈",falling:"📉",stable:"➡️",unknown:"❓"};
    c.innerHTML = flightData.price_analyses.map(a => {
        const diff = a.percent_vs_average < 0 ? Math.abs(a.percent_vs_average)+"% günstiger" : a.percent_vs_average+"% teurer";
        return `<div class="analysis-item"><span class="analysis-route">${a.route}</span><span class="analysis-trend">${icons[a.trend]||"❓"} ${Math.round(a.current_price)}€ (${diff})</span></div>`;
    }).join("");
}

// ===================== HELFER =====================
function fmtDate(d) {
    if (!d) return "–";
    return new Date(d).toLocaleDateString("de-DE",{day:"2-digit",month:"2-digit"});
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
        // Öffne die Details automatisch
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
            showStatus("✅ Suche läuft! " + outbound + " → " + returnDate + ". Ergebnis in 3-5 Min per Telegram.", "success");
        } else if (response.status === 401 || response.status === 403) {
            localStorage.removeItem("github_pat");
            setupTokenUI();
            showStatus("❌ Token ungültig. Bitte neuen Token eingeben.", "error");
        } else if (response.status === 404) {
            showStatus("❌ Workflow nicht gefunden. Wurde daily_search.yml erstellt?", "error");
        } else {
            showStatus("❌ Fehler " + response.status + ". Versuche es auf GitHub → Actions.", "error");
        }
    } catch (err) {
        showStatus("❌ Keine Verbindung: " + err.message, "error");
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
