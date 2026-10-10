/* BurnWatch Environmental Operations Console. Dependency-free by design. */

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

class ApiError extends Error {
  constructor(message, status = 0) {
    super(message);
    this.status = status;
  }
}

const api = {
  async request(path, options = {}) {
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 12000);
    try {
      const response = await fetch(path, {
        ...options,
        headers: { Accept: "application/json", ...(options.body ? { "Content-Type": "application/json" } : {}), ...(options.headers || {}) },
        signal: controller.signal,
      });
      const body = await response.json().catch(() => null);
      if (!response.ok) {
        const detail = Array.isArray(body?.detail)
          ? body.detail.map((item) => `${item.loc?.at(-1) || "field"}: ${item.msg}`).join("; ")
          : body?.detail;
        throw new ApiError(detail || `Request failed (${response.status})`, response.status);
      }
      return body;
    } catch (error) {
      if (error.name === "AbortError") throw new ApiError("The request timed out. Check the local API connection.");
      if (error instanceof ApiError) throw error;
      throw new ApiError("Cannot reach the BurnWatch API. It may be stopped or unavailable.");
    } finally {
      window.clearTimeout(timeout);
    }
  },
  health: () => api.request("/health"),
  observations: (deviceId = "") => api.request(`/observations?${new URLSearchParams({ limit: "500", ...(deviceId ? { device_id: deviceId } : {}) })}`),
  incidents: () => api.request("/incidents?limit=100"),
  incident: (id) => api.request(`/incidents/${encodeURIComponent(id)}`),
  submitObservation: (payload) => api.request("/observations", { method: "POST", body: JSON.stringify(payload) }),
  submitReport: (payload) => api.request("/reports", { method: "POST", body: JSON.stringify(payload) }),
  reviewIncident: (id, payload) => api.request(`/incidents/${encodeURIComponent(id)}/review`, { method: "POST", body: JSON.stringify(payload) }),
  updateIncident: (id, payload) => api.request(`/incidents/${encodeURIComponent(id)}/status`, { method: "POST", body: JSON.stringify(payload) }),
  serialPorts: () => api.request("/serial/ports"),
  serialStatus: () => api.request("/serial/status"),
  connectSerial: (payload) => api.request("/serial/connect", { method: "POST", body: JSON.stringify(payload) }),
  disconnectSerial: () => api.request("/serial/disconnect", { method: "POST" }),
};

const routes = {
  map: { title: "Incident Map", kicker: "GEOSPATIAL OVERVIEW" },
  evidence: { title: "Event Evidence", kicker: "SENSOR EVIDENCE" },
  reports: { title: "Community Reports", kicker: "PUBLIC INTAKE" },
  workflow: { title: "Investigation Workflow", kicker: "CASE REVIEW" },
  impact: { title: "Impact Report", kicker: "OPERATIONAL SUMMARY" },
  operations: { title: "Operations", kicker: "AUTHORIZED UTILITY" },
};

const state = {
  session: null,
  health: null,
  serialStatus: null,
  detectedPorts: [],
  internalObservations: [],
  internalIncidents: [],
  observations: [],
  incidents: [],
  sessionReports: [],
  reportFingerprints: new Set(),
  selectedIncidentId: null,
  selectedDeviceId: null,
  selectedMapEventId: null,
  dataError: null,
  lastUpdated: null,
  loading: false,
  leafletMap: null,
  map: { filters: { from: "", to: "", status: "all", source: "all", quality: "all", verification: "all" } },
  workflow: { query: "", status: "all", source: "all", sort: "newest" },
};

function escapeHtml(value) {
  return String(value ?? "—")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function label(value) {
  return String(value ?? "Unavailable").replaceAll("_", " ");
}

function formatDate(value, withTime = true) {
  if (!value) return "Unavailable";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.valueOf())) return "Unavailable";
  return withTime ? parsed.toLocaleString() : parsed.toLocaleDateString();
}

function formatNumber(value) {
  return Number.isFinite(Number(value)) ? new Intl.NumberFormat().format(Number(value)) : "Unavailable";
}

function numericOrNull(value) {
  return value === "" || value === null ? null : Number(value);
}

function isOperationalRole() {
  return state.session?.role === "admin";
}

function isInvestigator() {
  return state.session?.role === "admin";
}

function validCoordinates(item, requireGps = false) {
  const lat = Number(item?.latitude);
  const lon = Number(item?.longitude);
  if (!Number.isFinite(lat) || !Number.isFinite(lon) || lat < -90 || lat > 90 || lon < -180 || lon > 180 || (lat === 0 && lon === 0)) return false;
  return !requireGps || item.gps_fix === true;
}

function statusClass(value) {
  return String(value || "").replaceAll("_", "-").replaceAll(/[^a-z-]/g, "");
}

function badge(value, extra = "") {
  return `<span class="badge ${statusClass(value)} ${escapeHtml(extra)}">${escapeHtml(label(value))}</span>`;
}

function provenanceBadge(sourceMode, isSimulated) {
  const source = isSimulated || sourceMode === "simulated" ? "simulated" : sourceMode === "cansat" ? "cansat" : "unavailable";
  return badge(source, source === "cansat" ? "live" : "");
}

function showToast(message, type = "") {
  const toast = document.createElement("p");
  toast.className = `toast ${type}`;
  toast.textContent = message;
  $("#toast-region").append(toast);
  window.setTimeout(() => toast.remove(), 6000);
}

function errorCopy(error) {
  if (error?.status === 401) return "Your session is not authenticated. Production authentication is not implemented by this backend.";
  if (error?.status === 403) return "You do not have permission for that action.";
  if (error?.status === 409) return `The server rejected the state transition: ${error.message}`;
  return error?.message || "An unexpected error occurred.";
}

function setHeader() {
  const route = currentRoute();
  const definition = routes[route] || routes.map;
  $("#page-title").textContent = definition.title;
  $("#crumb").textContent = definition.kicker;
  const source = state.health?.data_source;
  const sourceChip = $("#source-chip");
  sourceChip.textContent = `SOURCE: ${source ? source.toUpperCase() : "UNAVAILABLE"}`;
  sourceChip.classList.toggle("chip-live", source === "cansat");
  $("#sidebar-source").textContent = `SOURCE: ${source ? source.toUpperCase() : "UNAVAILABLE"}`;
  const connection = $("#sidebar-connection");
  connection.className = `connection-state ${state.dataError ? "disconnected" : state.health ? "connected" : ""}`;
  connection.innerHTML = `<span></span>${state.dataError ? "API unavailable" : state.health ? "API connected" : "Checking API"}`;
  $$(".primary-nav a").forEach((link) => link.classList.toggle("active", link.dataset.route === route));
}

function currentRoute() {
  const raw = window.location.hash.replace(/^#/, "").split("?")[0];
  return Object.hasOwn(routes, raw) ? raw : "map";
}

function navigate(route) {
  window.location.hash = route;
}

function pageHeader(title, description, actions = "") {
  return `<header class="page-header"><div><h2>${escapeHtml(title)}</h2><p>${escapeHtml(description)}</p></div>${actions ? `<div class="page-header-actions">${actions}</div>` : ""}</header>`;
}

function dataErrorPanel() {
  return `<section class="error-state" role="alert"><strong>Connection unavailable.</strong><br>${escapeHtml(state.dataError || "The local API did not respond.")}<div class="inline" style="margin-top:.7rem"><button id="retry-load" class="button button-secondary" type="button">Retry connection</button></div></section>`;
}

function freshness() {
  return state.lastUpdated ? `<p class="freshness">LAST SUCCESSFUL UPDATE: ${escapeHtml(formatDate(state.lastUpdated))}</p>` : "";
}

async function loadCoreData() {
  state.loading = true;
  renderRoute();
  try {
    const [health, observations, incidents, serial] = await Promise.all([
      api.health(),
      api.observations(),
      api.incidents(),
      api.serialStatus().catch(() => null),
    ]);
    state.health = health;
    state.serialStatus = serial;
    state.internalObservations = observations.items || [];
    state.internalIncidents = incidents.items || [];
    state.observations = state.internalObservations.filter((item) => item.source_mode === "cansat" && !item.is_simulated);
    state.incidents = state.internalIncidents.filter((item) => item.source_mode === "cansat" && !item.is_simulated);
    state.dataError = null;
    state.lastUpdated = new Date().toISOString();
  } catch (error) {
    state.dataError = errorCopy(error);
  } finally {
    state.loading = false;
    setHeader();
    renderRoute();
  }
}

function setupSession(session) {
  state.session = session;
  $("#login-view").classList.add("hidden");
  $("#account-name").textContent = session.identity;
  $("#account-initial").textContent = session.identity.slice(0, 1).toUpperCase();
  $("#account-role").textContent = "ADMINISTRATOR / PROTOTYPE";
  $("#operations-link").classList.toggle("hidden", !isOperationalRole());
  $("#account-admin-login").classList.add("hidden");
  $("#sidebar-admin-login").textContent = "Administrator signed in";
  $("#prototype-banner").innerHTML = "<strong>Administrator prototype:</strong> UI controls do not secure the unauthenticated development API.";
  if (!window.location.hash) window.location.hash = "map";
  setHeader();
  renderRoute();
}

function clearSession() {
  state.session = null;
  $("#login-view").classList.add("hidden");
  $("#account-menu").classList.add("hidden");
  $("#login-form").reset();
  $("#account-name").textContent = "Public view";
  $("#account-initial").textContent = "B";
  $("#account-role").textContent = "PUBLIC DASHBOARDS";
  $("#operations-link").classList.add("hidden");
  $("#account-admin-login").classList.remove("hidden");
  $("#sidebar-admin-login").textContent = "Administrator sign in";
  $("#prototype-banner").innerHTML = "<strong>CanSat operational view:</strong> simulated records are excluded from all five public dashboards.";
  if (currentRoute() === "operations") navigate("map");
  else renderRoute();
  showToast("Administrator prototype session cleared.");
}

function showAdminLogin() {
  if (state.session) {
    navigate("operations");
    return;
  }
  $("#account-menu").classList.add("hidden");
  $("#login-view").classList.remove("hidden");
  $("#login-identity").focus();
}

function applyTheme(isLight) {
  document.body.classList.toggle("light-theme", isLight);
  const toggle = $("#theme-toggle");
  toggle.textContent = isLight ? "Dark mode" : "Light mode";
  toggle.setAttribute("aria-pressed", String(isLight));
  try { window.localStorage.setItem("burnwatch-theme", isLight ? "light" : "dark"); } catch (_) { /* Storage can be unavailable in private browser contexts. */ }
}

function initialiseTheme() {
  let preference = "dark";
  try { preference = window.localStorage.getItem("burnwatch-theme") || preference; } catch (_) { /* Use the accessible dark default. */ }
  applyTheme(preference === "light");
}

function routeAllowed(route) {
  return route !== "operations" || isOperationalRole();
}

function accessDenied() {
  return `<section class="panel pad"><div class="empty-state"><strong>Administrator access required</strong><span>Operations is an internal utility view. Sign in through the sidebar to open the non-production administrator prototype.</span><button id="open-admin-login" class="button button-primary" type="button">Administrator sign in</button></div></section>`;
}

function cansatOnlyNotice() {
  const count = state.observations.length;
  return `<section class="notice info"><strong>CanSat-only dashboard data:</strong> ${escapeHtml(count)} CanSat observation${count === 1 ? "" : "s"} are currently available. Simulated records are intentionally excluded from these five dashboards.</section>`;
}

function metric(labelText, value, detail = "") {
  return `<article class="metric"><span class="metric-label">${escapeHtml(labelText)}</span><strong>${escapeHtml(value)}</strong>${detail ? `<span class="metric-detail">${escapeHtml(detail)}</span>` : ""}</article>`;
}

function chartFromObservations(items) {
  const readings = [...items].sort((a, b) => new Date(a.received_at) - new Date(b.received_at));
  if (!readings.length) return `<div class="empty-state"><strong>No observation series available</strong><span>Select an incident with saved observations for this device.</span></div>`;
  const values = readings.map((item) => Number(item.mq135_raw));
  const minimum = Math.min(...values);
  const maximum = Math.max(...values);
  const span = Math.max(maximum - minimum, 1);
  const points = readings.map((item, index) => {
    const x = 38 + (index / Math.max(readings.length - 1, 1)) * 540;
    const y = 210 - ((Number(item.mq135_raw) - minimum) / span) * 160;
    return { x, y, item };
  });
  const polyline = points.map((point) => `${point.x},${point.y}`).join(" ");
  return `<div class="chart-wrap"><svg class="line-chart" viewBox="0 0 620 245" role="img" aria-label="MQ135 raw readings plotted over the selected observation period">
    <line class="axis" x1="38" x2="580" y1="210" y2="210"/><line class="axis" x1="38" x2="38" y1="25" y2="210"/>
    <line class="chart-grid" x1="38" x2="580" y1="50" y2="50"/><line class="chart-grid" x1="38" x2="580" y1="130" y2="130"/>
    <text x="5" y="31">${escapeHtml(maximum)}</text><text x="5" y="215">${escapeHtml(minimum)}</text>
    <text x="38" y="235">${escapeHtml(formatDate(readings[0].received_at, false))}</text><text x="450" y="235">${escapeHtml(formatDate(readings.at(-1).received_at, false))}</text>
    <polyline class="series" points="${polyline}"/>
    ${points.map((point) => `<circle class="${point.item.anomaly_detected ? "anomaly-point" : "point"}" cx="${point.x}" cy="${point.y}" r="4"><title>${escapeHtml(`Seq ${point.item.sequence}: ${point.item.mq135_raw}; score ${point.item.anomaly_score ?? "not calculated"}`)}</title></circle>`).join("")}
  </svg></div>`;
}

function getMapEvents() {
  const events = [];
  state.observations.filter((item) => item.anomaly_detected && validCoordinates(item, true)).forEach((item) => events.push({
    key: `observation-${item.observation_id}`, kind: "candidate", timestamp: item.received_at, latitude: item.latitude, longitude: item.longitude, source: item.source_mode, quality: item.quality_flags || [], observation: item,
  }));
  state.incidents.filter((item) => item.status === "confirmed" && validCoordinates(item)).forEach((item) => events.push({
    key: `incident-${item.incident_id}`, kind: "verified", timestamp: item.created_at, latitude: item.latitude, longitude: item.longitude, source: item.source_mode, quality: [], incident: item,
  }));
  return events;
}

function filterMapEvents(events) {
  const filters = state.map.filters;
  return events.filter((event) => {
    const day = event.timestamp ? new Date(event.timestamp).toISOString().slice(0, 10) : "";
    if (filters.from && day < filters.from) return false;
    if (filters.to && day > filters.to) return false;
    if (filters.source !== "all" && event.source !== filters.source) return false;
    if (filters.status === "candidate" && event.kind !== "candidate") return false;
    if (filters.status === "confirmed" && event.kind !== "verified") return false;
    if (filters.quality === "quality" && !event.quality.length) return false;
    if (filters.quality === "clean" && event.quality.length) return false;
    if (filters.verification === "verified" && event.kind !== "verified") return false;
    if (filters.verification === "unverified" && event.kind === "verified") return false;
    return true;
  });
}

function mapDonut(events) {
  const candidate = events.filter((event) => event.kind === "candidate").length;
  const confirmed = events.filter((event) => event.kind === "verified").length;
  const total = Math.max(candidate + confirmed, 1);
  const candidatePercent = (candidate / total) * 100;
  const confirmedPercent = (confirmed / total) * 100;
  return `<div class="donut-wrap"><div class="donut-chart"><svg viewBox="0 0 100 100" aria-label="Visible CanSat event categories: ${candidate} candidates and ${confirmed} verified incidents"><circle class="donut-track" cx="50" cy="50" r="40"/><circle class="donut-candidate" cx="50" cy="50" r="40" pathLength="100" stroke-dasharray="${candidatePercent} ${100 - candidatePercent}" stroke-dashoffset="0"/><circle class="donut-confirmed" cx="50" cy="50" r="40" pathLength="100" stroke-dasharray="${confirmedPercent} ${100 - confirmedPercent}" stroke-dashoffset="${-candidatePercent}"/></svg></div><strong class="donut-center">${candidate + confirmed}</strong></div>`;
}

function leafletMapWidget(events) {
  const candidates = events.filter((event) => event.kind === "candidate").length;
  const confirmed = events.filter((event) => event.kind === "verified").length;
  const max = Math.max(candidates, confirmed, 1);
  return `<div class="map-layout"><div><div id="incident-map" class="leaflet-map" role="region" aria-label="OpenStreetMap incident map with CanSat candidate and verified-incident markers"></div><p class="field-help">OpenStreetMap base map. The translucent red/orange circles are a relative signal-density heat overlay from visible CanSat anomalies; they are not pollutant concentration or AQI.</p></div><aside class="panel pad map-chart"><div><p class="eyebrow">VISIBLE CANSAT EVENTS</p><h2>Map composition</h2></div>${mapDonut(events)}<div class="map-legend"><span><i></i> Candidate sensor anomaly · ${candidates}</span><span><i class="confirmed"></i> Verified incident · ${confirmed}</span><span><i class="heat"></i> Relative signal heat overlay</span></div><div class="bar-list"><div class="bar-row"><span>Candidate</span><div class="bar-track"><div class="bar-fill warning" style="width:${(candidates / max) * 100}%"></div></div><strong>${candidates}</strong></div><div class="bar-row"><span>Verified</span><div class="bar-track"><div class="bar-fill danger" style="width:${(confirmed / max) * 100}%"></div></div><strong>${confirmed}</strong></div></div></aside></div>`;
}

function initialiseLeafletMap(events) {
  if (state.leafletMap) {
    state.leafletMap.remove();
    state.leafletMap = null;
  }
  const target = $("#incident-map");
  if (!target) return;
  if (!window.L) {
    target.innerHTML = `<div class="empty-state"><strong>Map library unavailable</strong><span>OpenStreetMap/Leaflet could not be loaded. Check your network connection and retry.</span></div>`;
    return;
  }
  const map = window.L.map(target, { scrollWheelZoom: true }).setView([28.6139, 77.209], 11);
  state.leafletMap = map;
  window.L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution: "&copy; <a href=\"https://www.openstreetmap.org/copyright\">OpenStreetMap</a> contributors",
  }).addTo(map);
  const heatGroups = new Map();
  events.filter((event) => event.kind === "candidate").forEach((event) => {
    const key = `${Number(event.latitude).toFixed(3)},${Number(event.longitude).toFixed(3)}`;
    const group = heatGroups.get(key) || { latitude: Number(event.latitude), longitude: Number(event.longitude), count: 0, score: 0 };
    group.count += 1;
    group.score += Number(event.observation?.anomaly_score || 0);
    heatGroups.set(key, group);
  });
  heatGroups.forEach((group) => {
    const relative = Math.min(1, (group.score / Math.max(group.count, 1)) / 12);
    window.L.circle([group.latitude, group.longitude], { radius: 600 + relative * 1500, stroke: false, fillColor: "#d45b4f", fillOpacity: .11 + relative * .18, interactive: false }).addTo(map);
  });
  const bounds = [];
  events.forEach((event) => {
    const type = event.kind === "verified" ? "confirmed" : event.kind;
    const title = event.kind === "verified" ? "Verified incident" : event.kind === "report" ? "Community report" : "Candidate sensor anomaly";
    const icon = window.L.divIcon({ className: "", html: `<span class="map-marker ${type}" aria-hidden="true"></span>`, iconSize: [16, 16], iconAnchor: [8, 8] });
    const marker = window.L.marker([event.latitude, event.longitude], { icon, keyboard: true, title }).addTo(map);
    marker.bindPopup(`<strong>${escapeHtml(title)}</strong><br><span>${escapeHtml(formatDate(event.timestamp))}</span><br><span>${escapeHtml(`${event.latitude}, ${event.longitude}`)}</span><br><span>${escapeHtml(event.source === "community" ? "Unverified community report" : `Source: ${event.source}`)}</span>`);
    marker.on("click", () => { state.selectedMapEventId = event.key; renderMap(); });
    bounds.push([event.latitude, event.longitude]);
  });
  if (bounds.length) map.fitBounds(bounds, { padding: [34, 34], maxZoom: 13 });
  window.setTimeout(() => map.invalidateSize(), 0);
}

function mapDetail(event) {
  if (!event) return "";
  const sourceData = event.observation || event.incident || event.report;
  const typeLabel = event.kind === "verified" ? "Verified incident" : event.kind === "report" ? "Community report" : "Candidate sensor anomaly";
  const id = sourceData.incident_id || sourceData.observation_id || sourceData.report_id;
  const incidentLink = event.incident ? `<button data-open-workflow="${escapeHtml(event.incident.incident_id)}" class="button button-primary" type="button">Open investigation</button>` : "";
  const evidenceLink = event.observation ? `<button data-open-evidence="${escapeHtml(event.observation.device_id)}" class="button button-secondary" type="button">Open device evidence</button>` : "";
  return `<aside class="drawer" aria-label="Selected map event"><header class="drawer-header"><div><p class="eyebrow">${escapeHtml(typeLabel.toUpperCase())}</p><h2>${escapeHtml(String(id).slice(0, 18))}</h2></div><button id="close-map-drawer" class="icon-button" type="button" aria-label="Close event detail">×</button></header><div class="drawer-content stack"><div class="status-row">${event.incident ? badge(event.incident.status) : event.kind === "candidate" ? badge("candidate") : badge("unverified")} ${event.source !== "community" ? provenanceBadge(event.source, event.source === "simulated") : badge("unverified")}</div><dl class="definition-grid"><div><dt>Timestamp</dt><dd>${escapeHtml(formatDate(event.timestamp))}</dd></div><div><dt>Coordinates</dt><dd class="mono">${escapeHtml(`${event.latitude}, ${event.longitude}`)}</dd></div><div><dt>Data source</dt><dd>${escapeHtml(event.source)}</dd></div><div><dt>Quality</dt><dd>${escapeHtml(event.quality.length ? event.quality.map(label).join(", ") : "No map-level flags")}</dd></div></dl>${event.observation ? `<section class="notice info"><strong>Sensor signal:</strong> MQ135 ${escapeHtml(event.observation.mq135_raw)}; anomaly score ${escapeHtml(event.observation.anomaly_score ?? "Unavailable")}. This is a relative response, not a pollutant concentration or proof of burning.</section>` : ""}${event.report ? `<section class="notice"><strong>Allegation:</strong> ${escapeHtml(event.report.description)}<br><small>Available only in this browser session because the API has no report-list endpoint.</small></section>` : ""}<div class="inline">${incidentLink}${evidenceLink}</div></div></aside>`;
}

function renderMap() {
  const allEvents = getMapEvents();
  const events = filterMapEvents(allEvents);
  const selected = events.find((event) => event.key === state.selectedMapEventId);
  const filters = state.map.filters;
  const body = state.dataError ? dataErrorPanel() : `
    ${cansatOnlyNotice()}
    <section class="metric-grid">${metric("Visible map events", events.length, `${allEvents.length} CanSat events with valid coordinates`)}${metric("Candidate anomalies", events.filter((event) => event.kind === "candidate").length, "Sensor-derived signals")}${metric("Verified incidents", events.filter((event) => event.kind === "verified").length, "Explicit backend confirmation only")}${metric("Source", "CanSat only", "Simulated records are excluded")}</section>
    <section class="panel pad" style="margin-top:1rem"><div class="panel-heading"><div><h2>Event geography</h2><p>OpenStreetMap view with pan and zoom. Records without valid coordinates remain unplotted.</p></div>${freshness()}</div><div class="filter-grid"><label>From date<input id="map-from" type="date" value="${escapeHtml(filters.from)}" /></label><label>To date<input id="map-to" type="date" value="${escapeHtml(filters.to)}" /></label><label>Event type<select id="map-status"><option value="all">All types</option><option value="candidate" ${filters.status === "candidate" ? "selected" : ""}>Candidate anomaly</option><option value="confirmed" ${filters.status === "confirmed" ? "selected" : ""}>Verified incident</option></select></label><label>Data source<select id="map-source"><option value="all">All CanSat records</option><option value="cansat" ${filters.source === "cansat" ? "selected" : ""}>CanSat</option></select></label><label>Data quality<select id="map-quality"><option value="all">All</option><option value="clean" ${filters.quality === "clean" ? "selected" : ""}>No flags</option><option value="quality" ${filters.quality === "quality" ? "selected" : ""}>Has flags</option></select></label><label>Verification<select id="map-verification"><option value="all">All states</option><option value="verified" ${filters.verification === "verified" ? "selected" : ""}>Verified only</option><option value="unverified" ${filters.verification === "unverified" ? "selected" : ""}>Not verified</option></select></label></div>${leafletMapWidget(events)}</section>
    <section class="panel pad" style="margin-top:1rem"><div class="panel-heading"><div><h2>Visible CanSat event list</h2><p>Use this list when a record cannot be located visually.</p></div></div><div class="queue">${events.slice(0, 8).map((event) => `<button class="queue-item" type="button" data-map-list="${escapeHtml(event.key)}"><span><strong>${escapeHtml(event.kind === "verified" ? "Verified incident" : "Candidate sensor anomaly")}</strong><small class="mono">${escapeHtml(`${event.latitude}, ${event.longitude}`)} · ${escapeHtml(formatDate(event.timestamp))}</small></span>${provenanceBadge(event.source, false)}</button>`).join("") || `<div class="empty-state"><strong>No visible events match these filters.</strong><span>Clear filters or process CanSat records with valid GPS coordinates.</span></div>`}</div></section>${mapDetail(selected)}`;
  $("#main-content").innerHTML = pageHeader("Incident Map", "Geographic overview of CanSat sensor anomalies and explicit backend-confirmed incidents.") + body;
  bindMap(events);
}

function bindMap(events) {
  initialiseLeafletMap(events);
  $("#retry-load")?.addEventListener("click", loadCoreData);
  const mapFilterFields = [["#map-from", "from"], ["#map-to", "to"], ["#map-status", "status"], ["#map-source", "source"], ["#map-quality", "quality"], ["#map-verification", "verification"]];
  mapFilterFields.forEach(([selector, key]) => $(selector)?.addEventListener("change", (event) => { state.map.filters[key] = event.target.value; state.selectedMapEventId = null; renderMap(); }));
  $$('[data-map-event], [data-map-list]').forEach((element) => {
    const select = () => { state.selectedMapEventId = element.dataset.mapEvent || element.dataset.mapList; renderMap(); };
    element.addEventListener("click", select);
    element.addEventListener("keydown", (event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); select(); } });
  });
  $("#close-map-drawer")?.addEventListener("click", () => { state.selectedMapEventId = null; renderMap(); });
  $$('[data-open-evidence]').forEach((button) => button.addEventListener("click", () => { state.selectedDeviceId = button.dataset.openEvidence; navigate("evidence"); }));
  $$('[data-open-workflow]').forEach((button) => button.addEventListener("click", () => { state.selectedIncidentId = button.dataset.openWorkflow; navigate("workflow"); }));
}

function selectedEvidenceIncident() {
  return state.incidents.find((item) => item.incident_id === state.selectedIncidentId) || state.incidents[0] || null;
}

function renderEvidence() {
  const incident = selectedEvidenceIncident();
  if (incident) state.selectedDeviceId = state.selectedDeviceId || incident.device_id;
  const device = state.selectedDeviceId || incident?.device_id;
  const observations = state.observations.filter((item) => item.device_id === device).sort((a, b) => new Date(a.received_at) - new Date(b.received_at));
  const flags = [...new Set(observations.flatMap((item) => item.quality_flags || []))];
  const earliest = observations[0]; const latest = observations.at(-1);
  const body = state.dataError ? dataErrorPanel() : `
    ${cansatOnlyNotice()}
    <section class="notice danger"><strong>Scientific interpretation:</strong> Relative gas-sensor response — not a pollutant concentration or official AQI measurement. Sensor observations are evidence for review, not proof of open burning.</section>
    <section class="panel pad" style="margin-top:1rem"><div class="panel-heading"><div><h2>Evidence selection</h2><p>Observation series are filtered by the selected device. The current API does not expose an exact incident-to-observation query.</p></div>${freshness()}</div><label>Case / device<select id="evidence-select">${state.incidents.map((item) => `<option value="${escapeHtml(item.incident_id)}" ${item.incident_id === incident?.incident_id ? "selected" : ""}>${escapeHtml(`${item.device_id} · ${label(item.status)} · ${item.incident_id.slice(0, 8)}`)}</option>`).join("") || `<option value="">No incidents available</option>`}</select></label>${incident ? `<div class="inline" style="margin-top:.8rem"><button id="evidence-workflow-link" type="button" class="button button-secondary">Open associated case</button></div>` : ""}</section>
    ${incident ? `<section class="metric-grid" style="margin-top:1rem">${metric("Backend status", label(incident.status), `${incident.is_simulated ? "SIMULATED" : "CANSAT"} provenance`)}${metric("Observation count", observations.length, `Device ${incident.device_id}`)}${metric("Peak MQ135", incident.peak_mq135, "Raw ADC response")}${metric("Peak anomaly score", incident.peak_anomaly_score, "Relative deviation")}</section><section class="section-grid" style="margin-top:1rem"><article class="panel pad"><div class="panel-heading"><div><h2>MQ135 response over time</h2><p>Raw readings, with anomalous points shown in amber.</p></div></div>${chartFromObservations(observations)}<p class="field-help">Relative baseline: <strong>Unavailable</strong> — the current API returns anomaly scores but not baseline values.</p></article><aside class="panel pad"><h2>Evidence context</h2><dl class="definition-grid"><div><dt>Event start</dt><dd>${escapeHtml(formatDate(earliest?.received_at))}</dd></div><div><dt>Event end</dt><dd>${escapeHtml(formatDate(latest?.received_at))}</dd></div><div><dt>Coordinates</dt><dd class="mono">${escapeHtml(incident.latitude != null ? `${incident.latitude}, ${incident.longitude}` : "Unavailable")}</dd></div><div><dt>GPS quality</dt><dd>${escapeHtml(latest ? `${latest.gps_fix ? "Fix" : "No fix"}; ${latest.satellites} satellites` : "Unavailable")}</dd></div><div><dt>Environmental context</dt><dd>${escapeHtml(latest ? `${latest.temperature_c ?? "—"} °C / ${latest.humidity_pct ?? "—"}% / ${latest.pressure_hpa ?? "—"} hPa` : "Unavailable")}</dd></div><div><dt>Quality flags</dt><dd>${escapeHtml(flags.length ? flags.map(label).join(", ") : "None returned")}</dd></div></dl><p class="field-help">Reviewer notes: ${escapeHtml(incident.notes || "No reviewer note recorded.")}</p></aside></section><section class="panel pad" style="margin-top:1rem"><div class="panel-heading"><div><h2>Observation table</h2><p>Accessible text equivalent for the plotted readings.</p></div></div><div class="table-wrap"><table><thead><tr><th>Received</th><th>Sequence</th><th>MQ135 raw</th><th>Score</th><th>Environment</th><th>GPS / quality</th></tr></thead><tbody>${observations.map((item) => `<tr><td>${escapeHtml(formatDate(item.received_at))}</td><td class="mono">${escapeHtml(item.sequence)}</td><td>${escapeHtml(item.mq135_raw)} ${item.anomaly_detected ? badge("warning") : ""}</td><td>${escapeHtml(item.anomaly_score ?? "Not calculated")}</td><td>${escapeHtml(`${item.temperature_c ?? "—"} °C / ${item.humidity_pct ?? "—"}% / ${item.pressure_hpa ?? "—"} hPa`)}</td><td>${escapeHtml(`${item.gps_fix ? "Fix" : "No fix"}; ${item.satellites} sat. ${item.quality_flags?.length ? `· ${item.quality_flags.map(label).join(", ")}` : ""}`)}</td></tr>`).join("") || `<tr><td colspan="6">No observations were returned for this device.</td></tr>`}</tbody></table></div></section>` : `<section class="panel pad"><div class="empty-state"><strong>No case selected</strong><span>Process telemetry that produces a candidate incident, then select it here.</span></div></section>`}`;
  $("#main-content").innerHTML = pageHeader("Event Evidence", "Inspect what the backend measured while preserving uncertainty, provenance, and data-quality context.") + body;
  $("#retry-load")?.addEventListener("click", loadCoreData);
  $("#evidence-select")?.addEventListener("change", (event) => { state.selectedIncidentId = event.target.value; state.selectedDeviceId = null; renderEvidence(); });
  $("#evidence-workflow-link")?.addEventListener("click", () => navigate("workflow"));
}

function renderReports() {
  const recent = state.sessionReports;
  const body = `
    <section class="notice"><strong>Reports are allegations of suspected activity.</strong> Submission does not establish that an environmental violation occurred. Reports require review.</section>
    <section class="two-column" style="margin-top:1rem"><article class="panel pad"><div class="panel-heading"><div><h2>Submit a community report</h2><p>Mobile-friendly public intake using the backend's current supported fields.</p></div></div><form id="community-report-form" class="form-grid" novalidate><label>Reporter name<input name="reporter_name" required autocomplete="name" /></label><label>Contact (optional)<input name="contact" autocomplete="email" /></label><label>Latitude<input name="latitude" type="number" min="-90" max="90" step="any" required aria-describedby="location-help" /></label><label>Longitude<input name="longitude" type="number" min="-180" max="180" step="any" required aria-describedby="location-help" /></label><p id="location-help" class="field-help wide">Coordinates are required by this UI because the current API supports coordinates but not address/geocoding. Do not enter invented coordinates.</p><label class="wide">What did you observe?<textarea name="description" required maxlength="4000" placeholder="Describe what you observed, without stating it as verified fact."></textarea></label><label>Observed date/time <input disabled value="Unavailable — current API does not store event time" /></label><label>Photo <input disabled value="Unavailable — no upload endpoint" /></label><p class="field-help wide">Photo uploads, alleged-event time, report retrieval, moderation, and report-to-case links require backend changes documented in the UI integration log.</p><div id="report-errors" class="field-error wide" role="alert"></div><div class="form-action"><button class="button button-primary" type="submit">Submit report</button></div></form></article><aside class="panel pad"><h2>Privacy and review</h2><p class="field-help">Contact details are sent only when you enter them. The current local API has no authentication or production privacy controls; do not use it for sensitive real-world deployment.</p><p class="field-help">A successful submission returns a reference ID. It is not a case confirmation or a verified incident.</p><h3>Backend boundary</h3><p class="field-help">The API supports report creation only. It cannot currently list submitted reports, record photos, or store the alleged event time.</p></aside></section>
    <section class="panel pad" style="margin-top:1rem"><div class="panel-heading"><div><h2>Reports acknowledged in this browser session</h2><p>Not a complete report queue. The backend has no report-list endpoint.</p></div></div><div class="queue">${recent.map((report) => `<article class="queue-item"><span><strong class="mono">${escapeHtml(report.report_id)}</strong><small>${escapeHtml(formatDate(report.created_at))} · ${escapeHtml(`${report.latitude}, ${report.longitude}`)} · ${escapeHtml(report.description)}</small></span>${badge("unverified")}</article>`).join("") || `<div class="empty-state"><strong>No session reports yet</strong><span>Reports appear here only after this browser receives a successful API acknowledgement.</span></div>`}</div></section>`;
  $("#main-content").innerHTML = pageHeader("Community Reports", "Acknowledge community allegations without presenting them as independently verified incidents.") + body;
  $("#community-report-form").addEventListener("submit", submitCommunityReport);
}

async function submitCommunityReport(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const data = new FormData(form);
  const errors = $("#report-errors");
  errors.textContent = "";
  const payload = { reporter_name: data.get("reporter_name")?.trim(), description: data.get("description")?.trim(), contact: data.get("contact")?.trim() || null, latitude: numericOrNull(data.get("latitude")), longitude: numericOrNull(data.get("longitude")) };
  if (!payload.reporter_name || !payload.description || !validCoordinates(payload)) {
    errors.textContent = "Enter a reporter name, a description, and valid non-zero latitude/longitude coordinates.";
    return;
  }
  const fingerprint = [payload.reporter_name, payload.description, payload.latitude, payload.longitude].join("|");
  if (state.reportFingerprints.has(fingerprint)) {
    errors.textContent = "An identical report was already acknowledged in this browser session. Check its reference below before sending again.";
    return;
  }
  const button = $("button[type=submit]", form);
  button.disabled = true; button.textContent = "Submitting…";
  try {
    const result = await api.submitReport(payload);
    state.reportFingerprints.add(fingerprint);
    state.sessionReports.unshift({ ...payload, ...result, created_at: result.created_at || new Date().toISOString() });
    showToast(`Report acknowledged. Reference: ${result.report_id}`);
    form.reset();
    renderReports();
  } catch (error) {
    errors.textContent = errorCopy(error);
  } finally {
    button.disabled = false; button.textContent = "Submit report";
  }
}

function workflowActions(status) {
  const map = { candidate: [["under_review", "Start review"], ["confirm", "Confirm"], ["dismiss", "Dismiss"]], under_review: [["confirm", "Confirm"], ["dismiss", "Dismiss"]], confirmed: [["resolved", "Mark resolved"]], resolved: [["monitoring", "Start monitoring"]], monitoring: [["resolved", "Mark resolved"], ["candidate", "Reopen candidate"]], dismissed: [] };
  return map[status] || [];
}

function filteredIncidents() {
  const filter = state.workflow;
  const query = filter.query.toLowerCase().trim();
  const items = state.incidents.filter((item) => (!query || [item.incident_id, item.device_id, item.status].some((value) => String(value).toLowerCase().includes(query))) && (filter.status === "all" || item.status === filter.status) && (filter.source === "all" || item.source_mode === filter.source));
  return items.sort((a, b) => filter.sort === "oldest" ? new Date(a.created_at) - new Date(b.created_at) : new Date(b.created_at) - new Date(a.created_at));
}

function incidentDrawer(incident) {
  if (!incident) return "";
  const actions = workflowActions(incident.status);
  const actionOptions = actions.map(([value, text]) => `<option value="${value}">${escapeHtml(text)}</option>`).join("");
  return `<aside class="drawer" aria-label="Case detail"><header class="drawer-header"><div><p class="eyebrow">CASE DETAIL</p><h2 class="mono">${escapeHtml(incident.incident_id.slice(0, 18))}</h2></div><button id="close-incident-drawer" class="icon-button" type="button" aria-label="Close case detail">×</button></header><div class="drawer-content stack"><div class="status-row">${badge(incident.status)}${provenanceBadge(incident.source_mode, incident.is_simulated)}</div><dl class="definition-grid"><div><dt>Device</dt><dd class="mono">${escapeHtml(incident.device_id)}</dd></div><div><dt>Created</dt><dd>${escapeHtml(formatDate(incident.created_at))}</dd></div><div><dt>Peak sensor response</dt><dd>${escapeHtml(incident.peak_mq135)}</dd></div><div><dt>Peak score</dt><dd>${escapeHtml(incident.peak_anomaly_score)}</dd></div><div><dt>Coordinates</dt><dd class="mono">${escapeHtml(incident.latitude != null ? `${incident.latitude}, ${incident.longitude}` : "Unavailable")}</dd></div><div><dt>Assigned personnel</dt><dd>Unavailable in current API</dd></div><div><dt>Next action / due date</dt><dd>Unavailable in current API</dd></div><div><dt>Evidence links</dt><dd>${escapeHtml(`${incident.observation_ids?.length || 0} observation ID(s)`)}; exact retrieval endpoint unavailable</dd></div></dl><section><h3>Reviewer findings</h3><p class="field-help">${escapeHtml(incident.notes || "No reviewer finding recorded.")}</p></section>${isInvestigator() && actions.length ? `<form id="case-action-form" class="stack"><h3>Authorized prototype action</h3><p class="notice">This mock role does not authorize the backend. The server must enforce permission in production.</p><label>Transition<select name="action">${actionOptions}</select></label><label>Reviewer name<input name="reviewer" required value="${escapeHtml(state.session.identity)}" /></label><label>Reason / notes<textarea name="notes" required></textarea></label><button class="button button-primary" type="submit">Review change</button></form>` : `<section class="notice"><strong>Who can act:</strong> an Investigator prototype role may use the current backend transition endpoints. Operational labels such as inspection requested/action taken are not supported by this API.</section>`}<section><h3>Audit history</h3><ol class="audit-list">${(incident.history || []).map((entry) => `<li><strong>${escapeHtml(label(entry.from_status))} → ${escapeHtml(label(entry.to_status))}</strong> · ${escapeHtml(entry.actor)}<time>${escapeHtml(formatDate(entry.timestamp))}</time>${escapeHtml(entry.notes)}</li>`).join("") || "<li>No audit records returned.</li>"}</ol></section></div></aside>`;
}

function renderWorkflow() {
  const incidents = filteredIncidents();
  const selected = state.incidents.find((item) => item.incident_id === state.selectedIncidentId);
  const filters = state.workflow;
  const body = state.dataError ? dataErrorPanel() : `
    ${cansatOnlyNotice()}
    <section class="notice info"><strong>Backend workflow shown as recorded.</strong> This UI does not relabel backend statuses as “inspection requested,” “action taken,” or “closed” because no safe one-to-one mapping exists yet.</section>
    <section class="panel pad" style="margin-top:1rem"><div class="panel-heading"><div><h2>Case queue</h2><p>Search and filter existing CanSat incidents. Case assignment, due dates, inspection records, and report links are unavailable.</p></div>${freshness()}</div><div class="filter-grid"><label>Search<input id="workflow-search" value="${escapeHtml(filters.query)}" placeholder="ID, device, status" /></label><label>Backend status<select id="workflow-status"><option value="all">All statuses</option>${["candidate", "under_review", "confirmed", "dismissed", "resolved", "monitoring"].map((value) => `<option value="${value}" ${filters.status === value ? "selected" : ""}>${escapeHtml(label(value))}</option>`).join("")}</select></label><label>Source<select id="workflow-source"><option value="all">All CanSat records</option><option value="cansat" ${filters.source === "cansat" ? "selected" : ""}>CanSat</option></select></label><label>Sort<select id="workflow-sort"><option value="newest">Newest first</option><option value="oldest" ${filters.sort === "oldest" ? "selected" : ""}>Oldest first</option></select></label></div><div class="table-wrap"><table><thead><tr><th>Case</th><th>Backend status</th><th>Source</th><th>Location</th><th>Created</th><th>Action</th></tr></thead><tbody>${incidents.map((item) => `<tr><td><strong class="mono">${escapeHtml(item.incident_id.slice(0, 12))}</strong><br><small>${escapeHtml(item.device_id)}</small></td><td>${badge(item.status)}</td><td>${provenanceBadge(item.source_mode, item.is_simulated)}</td><td class="mono">${escapeHtml(item.latitude != null ? `${item.latitude}, ${item.longitude}` : "Unavailable")}</td><td>${escapeHtml(formatDate(item.created_at))}</td><td><button class="row-button" type="button" data-open-incident="${escapeHtml(item.incident_id)}">View case</button></td></tr>`).join("") || `<tr><td colspan="6">No incidents match the active filters.</td></tr>`}</tbody></table></div></section>${incidentDrawer(selected)}`;
  $("#main-content").innerHTML = pageHeader("Investigation Workflow", "Review existing cases with backend-governed transitions and a preserved audit trail.") + body;
  bindWorkflow();
}

function bindWorkflow() {
  $("#retry-load")?.addEventListener("click", loadCoreData);
  $("#workflow-search")?.addEventListener("input", (event) => { state.workflow.query = event.target.value; renderWorkflow(); });
  [["#workflow-status", "status"], ["#workflow-source", "source"], ["#workflow-sort", "sort"]].forEach(([selector, property]) => $(selector)?.addEventListener("change", (event) => { state.workflow[property] = event.target.value; renderWorkflow(); }));
  $$('[data-open-incident]').forEach((button) => button.addEventListener("click", () => { state.selectedIncidentId = button.dataset.openIncident; renderWorkflow(); }));
  $("#close-incident-drawer")?.addEventListener("click", () => { state.selectedIncidentId = null; renderWorkflow(); });
  $("#case-action-form")?.addEventListener("submit", (event) => {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    const action = data.get("action");
    const reviewer = data.get("reviewer")?.trim(); const notes = data.get("notes")?.trim();
    if (!reviewer || !notes) { showToast("Reviewer name and notes are required.", "error"); return; }
    openConfirm("Confirm case transition", `The backend will be asked to change this case to “${label(action)}”. This may be consequential and will be recorded in the audit history.`, "Confirm transition", async () => {
      const incident = state.incidents.find((item) => item.incident_id === state.selectedIncidentId);
      try {
        const updated = ["under_review", "confirm", "dismiss"].includes(action)
          ? await api.reviewIncident(incident.incident_id, { action, reviewer, notes })
          : await api.updateIncident(incident.incident_id, { status: action, reviewer, notes });
        state.incidents = state.incidents.map((item) => item.incident_id === updated.incident_id ? updated : item);
        showToast("Server acknowledged the case update.");
        renderWorkflow();
      } catch (error) { showToast(errorCopy(error), "error"); }
    });
  });
}

function renderImpact() {
  const statusCounts = Object.fromEntries(["candidate", "under_review", "confirmed", "dismissed", "resolved", "monitoring"].map((status) => [status, state.incidents.filter((item) => item.status === status).length]));
  const grouped = new Map();
  state.incidents.filter((item) => validCoordinates(item)).forEach((item) => {
    const key = `${(Math.round(item.latitude * 50) / 50).toFixed(2)}, ${(Math.round(item.longitude * 50) / 50).toFixed(2)}`;
    grouped.set(key, (grouped.get(key) || 0) + 1);
  });
  const recurring = [...grouped.entries()].filter(([, count]) => count > 1).sort((a, b) => b[1] - a[1]);
  const dateCounts = new Map();
  state.incidents.forEach((item) => { const key = item.created_at ? new Date(item.created_at).toISOString().slice(0, 10) : "unknown"; dateCounts.set(key, (dateCounts.get(key) || 0) + 1); });
  const trend = [...dateCounts.entries()].sort(([a], [b]) => a.localeCompare(b)).slice(-10);
  const maxStatus = Math.max(...Object.values(statusCounts), 1); const maxTrend = Math.max(...trend.map(([, count]) => count), 1);
  const body = state.dataError ? dataErrorPanel() : `
    ${cansatOnlyNotice()}
    <section class="notice"><strong>Metric integrity:</strong> suspected sensor events, community allegations, and independently confirmed incidents are kept separate. “Inspections completed” is unavailable because the backend does not provide inspections.</section>
    <section class="metric-grid" style="margin-top:1rem">${metric("Candidate events", statusCounts.candidate, "Backend candidate status")}${metric("Verified incidents", statusCounts.confirmed, "Explicit confirmed status only")}${metric("Data scope", "CanSat only", "Simulated records excluded")}${metric("Inspections completed", "Unavailable", "No inspection data in API")}</section>
    <section class="two-column" style="margin-top:1rem"><article class="panel pad"><div class="panel-heading"><div><h2>Cases by backend status</h2><p>Not a substitute for the proposed operational workflow stages.</p></div>${freshness()}</div><div class="bar-list">${Object.entries(statusCounts).map(([status, count]) => `<div class="bar-row"><span>${escapeHtml(label(status))}</span><div class="bar-track"><div class="bar-fill ${status === "confirmed" ? "danger" : status === "candidate" || status === "under_review" ? "warning" : ""}" style="width:${(count / maxStatus) * 100}%"></div></div><strong>${count}</strong></div>`).join("")}</div></article><article class="panel pad"><div class="panel-heading"><div><h2>Case creation trend</h2><p>Counts cases created by date, from returned incident records.</p></div></div><div class="bar-list">${trend.map(([date, count]) => `<div class="bar-row"><span class="mono">${escapeHtml(date)}</span><div class="bar-track"><div class="bar-fill" style="width:${(count / maxTrend) * 100}%"></div></div><strong>${count}</strong></div>`).join("") || `<div class="empty-state"><strong>No trend data available</strong></div>`}</div></article></section>
    <section class="panel pad" style="margin-top:1rem"><div class="panel-heading"><div><h2>Recurring locations</h2><p>Valid incident coordinates grouped into approximate 0.02° local cells. Invalid coordinates are excluded.</p></div></div><div class="queue">${recurring.map(([coordinates, count]) => `<article class="queue-item"><span><strong class="mono">${escapeHtml(coordinates)}</strong><small>Approximate local grouping; not a precise address or causal finding.</small></span><span class="badge warning">${escapeHtml(count)} cases</span></article>`).join("") || `<div class="empty-state"><strong>No recurring valid-coordinate cells found</strong><span>At least two backend incident records in the same local cell are needed.</span></div>`}</div></section>`;
  $("#main-content").innerHTML = pageHeader("Impact Report", "Operational patterns from currently returned backend records; no causal environmental impact is inferred.") + body;
  $("#retry-load")?.addEventListener("click", loadCoreData);
}

function telemetryPayload(form) {
  const data = new FormData(form);
  return { device_id: data.get("device_id")?.trim(), sequence: Number(data.get("sequence")), device_time_ms: Number(data.get("device_time_ms")), mq135_raw: Number(data.get("mq135_raw")), temperature_c: numericOrNull(data.get("temperature_c")), humidity_pct: numericOrNull(data.get("humidity_pct")), pressure_hpa: numericOrNull(data.get("pressure_hpa")), latitude: numericOrNull(data.get("latitude")), longitude: numericOrNull(data.get("longitude")), gps_fix: data.get("gps_fix") === "on", satellites: Number(data.get("satellites")) };
}

async function populateSerialPorts() {
  const select = $("#serial-port-select");
  const feedback = $("#serial-port-feedback");
  const customWrap = $("#serial-custom-container");
  if (!select) return;
  select.innerHTML = `<option value="">Scanning system COM ports…</option>`;
  if (feedback) feedback.textContent = "Scanning Windows COM ports…";

  try {
    const data = await api.serialPorts();
    const ports = data.ports || [];
    state.detectedPorts = ports;

    select.innerHTML = "";
    if (ports.length === 0) {
      select.innerHTML = `<option value="__custom__">No ports detected (specify COM manually)</option>`;
      customWrap?.classList.remove("hidden");
      const customInput = $("#serial-custom-port");
      if (customInput && !customInput.value) customInput.value = "COM5";
      if (feedback) feedback.textContent = "No active serial devices detected on Windows. Connect receiver and click Rescan, or enter COM port manually.";
    } else {
      select.innerHTML = `<option value="">-- Select detected COM port --</option>` +
        ports.map((p) => `<option value="${escapeHtml(p.port)}">${escapeHtml(p.port)}${p.description && p.description !== p.port ? ` — ${escapeHtml(p.description)}` : ""}</option>`).join("") +
        `<option value="__custom__">Other / Specify COM port manually…</option>`;
      customWrap?.classList.add("hidden");
      if (feedback) feedback.textContent = `Found ${ports.length} COM port(s) on Windows.`;
    }
  } catch (error) {
    if (feedback) feedback.textContent = "Failed to query system ports. You can enter COM port manually below.";
    select.innerHTML = `<option value="__custom__">Manual COM port entry</option>`;
    customWrap?.classList.remove("hidden");
  }
}

function openSerialDialog() {
  const dialog = $("#serial-dialog");
  if (!dialog) return;
  $("#serial-custom-container")?.classList.add("hidden");
  const feedback = $("#serial-port-feedback");
  if (feedback) feedback.textContent = "";
  populateSerialPorts();
  dialog.showModal();
}

function renderOperations() {
  if (!isOperationalRole()) { $("#main-content").innerHTML = pageHeader("Operations", "Utility access is shown only in the administrator prototype.") + accessDenied(); $("#open-admin-login")?.addEventListener("click", showAdminLogin); return; }
  const isSimulated = state.health?.data_source === "simulated";
  const serial = state.serialStatus;
  const isSerialConnected = Boolean(serial?.is_connected);

  const body = `
    <section class="notice info"><strong>Serial Ground Station:</strong> Connect your physical CanSat receiver via a Windows COM port (e.g. COM5, COM6). The system detects connected ports, streams framed telemetry in the background, and validates observations directly into the detection pipeline.</section>
    <section class="three-column" style="margin-top:1rem">
      <article class="panel pad">
        <p class="eyebrow">DATA SOURCE</p>
        <h2>${escapeHtml(state.health?.data_source?.toUpperCase() || "UNAVAILABLE")}</h2>
        <p class="field-help">Active provenance reported by <span class="mono">GET /health</span>.</p>
        <div class="inline">
          <button id="source-simulated" class="button ${isSimulated ? "button-primary" : "button-quiet"}" type="button">SIMULATED DATA</button>
          <button id="source-live" class="button ${!isSimulated && state.health ? "button-primary" : "button-quiet"}" type="button">LIVE CANSAT DATA</button>
        </div>
      </article>

      <article class="panel pad">
        <p class="eyebrow">HARDWARE INTERFACE</p>
        <h2>${isSerialConnected ? `<span style="color:var(--status-success)">●</span> ${escapeHtml(serial.port)}` : "Receiver Disconnected"}</h2>
        <p class="field-help">
          ${isSerialConnected
            ? `${escapeHtml(serial.baudrate)} baud · Packets: ${serial.packets_valid || 0} valid, ${serial.packets_corrupt || 0} corrupt`
            : (serial?.last_error ? `Last error: ${escapeHtml(serial.last_error)}` : "Windows serial receiver. Select COM port to connect.")}
        </p>
        <div class="inline" style="margin-top:0.75rem">
          ${isSerialConnected
            ? `<button id="serial-disconnect-btn" class="button button-danger" type="button">Disconnect ${escapeHtml(serial.port)}</button>`
            : `<button id="open-serial-dialog" class="button button-primary" type="button">Connect to Serial</button>`
          }
        </div>
      </article>

      <article class="panel pad">
        <p class="eyebrow">STORAGE</p>
        <h2>${escapeHtml(state.health?.storage || "Unavailable")}</h2>
        <p class="field-help">${state.health ? "Storage backend reported by the API." : "API health is unavailable."}</p>
      </article>
    </section>

    <section class="two-column" style="margin-top:1rem">
      <article class="panel pad">
        <div class="panel-heading">
          <div>
            <h2>Submit telemetry</h2>
            <p>Directly exercises the existing observation endpoint. The server, not this form, determines source provenance.</p>
          </div>
        </div>
        <form id="telemetry-form" class="form-grid">
          <label>Device ID<input name="device_id" value="burnwatch-ui-test" required /></label>
          <label>Sequence<input name="sequence" type="number" min="0" value="1" required /></label>
          <label>Device time (ms)<input name="device_time_ms" type="number" min="0" value="1000" required /></label>
          <label>MQ135 raw (0–1023)<input name="mq135_raw" type="number" min="0" max="1023" value="412" required /></label>
          <label>Temperature °C<input name="temperature_c" type="number" step=".1" value="31.4" /></label>
          <label>Humidity %<input name="humidity_pct" type="number" min="0" max="100" step=".1" value="48.2" /></label>
          <label>Pressure hPa<input name="pressure_hpa" type="number" step=".1" value="1001.3" /></label>
          <label>Latitude<input name="latitude" type="number" min="-90" max="90" step="any" value="28.75" /></label>
          <label>Longitude<input name="longitude" type="number" min="-180" max="180" step="any" value="77.12" /></label>
          <label>Satellites<input name="satellites" type="number" min="0" value="7" required /></label>
          <label class="checkbox-label"><input name="gps_fix" type="checkbox" checked /> GPS fix</label>
          <div class="form-action"><button class="button button-primary" type="submit">Submit observation</button></div>
        </form>
      </article>

      <aside class="panel pad">
        <h2>Simulated test sequence</h2>
        <p class="field-help">Creates 40 baseline records and three high readings to test the detector-to-candidate workflow. It is allowed only while the server reports <span class="mono">simulated</span>.</p>
        <button id="test-sequence" class="button button-secondary" type="button" ${isSimulated ? "" : "disabled"}>Create simulated test incident</button>
        <p class="field-help">${isSimulated ? "The generated data is visibly simulated and cannot be confirmed." : "Disabled: the server is configured for CanSat provenance."}</p>
      </aside>
    </section>

    <section class="panel pad" style="margin-top:1rem">
      <div class="panel-heading">
        <div>
          <h2>Recent internal observations</h2>
          <p>Administrator-only ingestion visibility. The five public dashboards remain CanSat-only.</p>
        </div>
        ${freshness()}
      </div>
      <div class="table-wrap">
        <table>
          <thead>
            <tr><th>Received</th><th>Device / sequence</th><th>MQ135</th><th>Score</th><th>Quality</th><th>Source</th></tr>
          </thead>
          <tbody>
            ${state.internalObservations.slice(0, 20).map((item) => `<tr><td>${escapeHtml(formatDate(item.received_at))}</td><td class="mono">${escapeHtml(`${item.device_id} / ${item.sequence}`)}</td><td>${escapeHtml(item.mq135_raw)}</td><td>${escapeHtml(item.anomaly_score ?? "—")}</td><td>${escapeHtml(item.quality_flags?.length ? item.quality_flags.map(label).join(", ") : "None")}</td><td>${provenanceBadge(item.source_mode, item.is_simulated)}</td></tr>`).join("") || `<tr><td colspan="6">No observations returned.</td></tr>`}
          </tbody>
        </table>
      </div>
    </section>`;

  $("#main-content").innerHTML = pageHeader("Operations", "Authorized utility area for serial receiver connection, hardware detection, API health, and telemetry ingestion.") + body;
  bindOperations();
}

function bindOperations() {
  $("#open-serial-dialog")?.addEventListener("click", openSerialDialog);
  $("#serial-disconnect-btn")?.addEventListener("click", () => {
    const port = state.serialStatus?.port || "serial";
    openConfirm(
      "Disconnect Serial Receiver",
      `Are you sure you want to disconnect from ${port}? Live CanSat telemetry ingestion will stop.`,
      "Disconnect",
      async () => {
        try {
          const res = await api.disconnectSerial();
          state.serialStatus = res;
          showToast(`Disconnected from ${port}.`);
          await loadCoreData();
        } catch (err) {
          showToast(errorCopy(err), "error");
        }
      }
    );
  });
  $("#source-simulated")?.addEventListener("click", () => showToast("Source changes require server configuration and an API restart. The displayed value has not changed.", "warning"));
  $("#source-live")?.addEventListener("click", () => openConfirm("Live CanSat configuration", "The browser cannot switch sources. Confirming will only explain the required server-side configuration; it will not change the active source.", "Show requirement", async () => showToast("Source unchanged. Set BURNWATCH_DATA_SOURCE=cansat in server configuration and restart the API after implementing authorized source control.", "warning")));
  $("#telemetry-form")?.addEventListener("submit", async (event) => {
    event.preventDefault(); const form = event.currentTarget; const button = $("button[type=submit]", form); button.disabled = true;
    try { const result = await api.submitObservation(telemetryPayload(form)); showToast(`Observation ${result.status}. ${result.anomaly_detected ? "Anomaly flagged." : ""}`); await loadCoreData(); } catch (error) { showToast(errorCopy(error), "error"); } finally { button.disabled = false; }
  });
  $("#test-sequence")?.addEventListener("click", createTestSequence);
}

async function createTestSequence(event) {
  const button = event.currentTarget;
  if (state.health?.data_source !== "simulated") { showToast("The test sequence is blocked unless the server reports simulated provenance.", "error"); return; }
  button.disabled = true; button.textContent = "Generating test sequence…";
  try {
    const deviceId = `burnwatch-test-${Date.now()}`;
    const shared = { device_id: deviceId, temperature_c: 29, humidity_pct: 46, pressure_hpa: 1002, latitude: 28.75, longitude: 77.12, gps_fix: true, satellites: 8 };
    for (let sequence = 1; sequence <= 43; sequence += 1) await api.submitObservation({ ...shared, sequence, device_time_ms: sequence * 1000, mq135_raw: sequence <= 40 ? 410 + (sequence % 3) : 720 });
    showToast("Simulated sequence complete. Check the candidate case in Investigation Workflow.");
    await loadCoreData();
  } catch (error) { showToast(errorCopy(error), "error"); } finally { button.disabled = false; button.textContent = "Create simulated test incident"; }
}

function renderRoute() {
  const route = currentRoute();
  if (!routeAllowed(route)) { $("#main-content").innerHTML = pageHeader("Access limited", "The administrator-only Operations utility is separate from the public dashboards.") + accessDenied(); $("#open-admin-login")?.addEventListener("click", showAdminLogin); setHeader(); return; }
  setHeader();
  if (state.loading) { $("#main-content").innerHTML = `<div class="loading">Loading current backend data…</div>`; return; }
  if (route === "map") renderMap();
  if (route === "evidence") renderEvidence();
  if (route === "reports") renderReports();
  if (route === "workflow") renderWorkflow();
  if (route === "impact") renderImpact();
  if (route === "operations") renderOperations();
}

function openConfirm(title, copy, buttonText, onConfirm) {
  const dialog = $("#confirm-dialog");
  $("#confirm-title").textContent = title;
  $("#confirm-copy").textContent = copy;
  $("#confirm-button").textContent = buttonText;
  dialog.onclose = async () => {
    if (dialog.returnValue === "confirm") await onConfirm();
    dialog.onclose = null;
  };
  dialog.showModal();
}

function bindShell() {
  $("#login-form").addEventListener("submit", (event) => {
    event.preventDefault();
    const identity = $("#login-identity").value.trim(); const password = $("#login-password").value;
    $("#identity-error").hidden = true; $("#password-error").hidden = true;
    let valid = true;
    if (!identity) { $("#identity-error").textContent = "Enter an email or username for the prototype session."; $("#identity-error").hidden = false; valid = false; }
    if (!password) { $("#password-error").textContent = "Enter a password to continue in the UI prototype. It is not transmitted or stored."; $("#password-error").hidden = false; valid = false; }
    if (!valid) return;
    setupSession({ identity, role: "admin" });
  });
  window.addEventListener("hashchange", () => { $(".sidebar").classList.remove("open"); $("#menu-toggle").setAttribute("aria-expanded", "false"); renderRoute(); });
  $("#refresh-button").addEventListener("click", loadCoreData);
  $("#account-toggle").addEventListener("click", () => { const menu = $("#account-menu"); menu.classList.toggle("hidden"); $("#account-toggle").setAttribute("aria-expanded", String(!menu.classList.contains("hidden"))); });
  $("#operations-link").addEventListener("click", () => { $("#account-menu").classList.add("hidden"); navigate("operations"); });
  ["#sidebar-admin-login", "#account-admin-login"].forEach((selector) => $(selector).addEventListener("click", showAdminLogin));
  $("#close-admin-login").addEventListener("click", () => $("#login-view").classList.add("hidden"));
  $("#logout-button").addEventListener("click", clearSession);
  $("#sidebar-collapse").addEventListener("click", () => {
    const consoleElement = $("#console");
    const collapsed = consoleElement.classList.toggle("sidebar-collapsed");
    const button = $("#sidebar-collapse");
    button.setAttribute("aria-pressed", String(collapsed));
    button.setAttribute("aria-label", collapsed ? "Expand sidebar" : "Collapse sidebar");
  });
  $("#theme-toggle").addEventListener("click", () => applyTheme(!document.body.classList.contains("light-theme")));
  $("#menu-toggle").addEventListener("click", () => { const sidebar = $(".sidebar"); sidebar.classList.toggle("open"); $("#menu-toggle").setAttribute("aria-expanded", String(sidebar.classList.contains("open"))); });
  $$(".primary-nav a").forEach((link) => link.addEventListener("click", (event) => { if (!routeAllowed(link.dataset.route)) { event.preventDefault(); showToast("Administrator access is required for Operations. This visual gate is not backend authorization.", "warning"); } }));
  document.addEventListener("click", (event) => { if (!event.target.closest(".account-wrap")) $("#account-menu").classList.add("hidden"); });

  // Serial connection dialog event handlers
  $("#serial-rescan")?.addEventListener("click", populateSerialPorts);
  $("#serial-dialog-cancel")?.addEventListener("click", () => $("#serial-dialog").close());
  $("#serial-port-select")?.addEventListener("change", (e) => {
    const isCustom = e.target.value === "__custom__";
    $("#serial-custom-container")?.classList.toggle("hidden", !isCustom);
    if (isCustom) $("#serial-custom-port")?.focus();
  });
  $("#serial-dialog-form")?.addEventListener("submit", async (e) => {
    e.preventDefault();
    const select = $("#serial-port-select");
    let port = select.value === "__custom__" ? $("#serial-custom-port")?.value.trim() : select.value;
    if (!port && select.value !== "__custom__" && $("#serial-custom-port")?.value.trim()) {
      port = $("#serial-custom-port").value.trim();
    }
    if (!port) {
      $("#serial-port-feedback").textContent = "Please select or enter a COM port (e.g. COM5).";
      return;
    }
    const baudrate = Number($("#serial-baudrate-select")?.value) || 9600;
    const submitBtn = $("#serial-dialog-submit");
    if (submitBtn) {
      submitBtn.disabled = true;
      submitBtn.textContent = "Connecting…";
    }
    try {
      const res = await api.connectSerial({ port, baudrate });
      state.serialStatus = res;
      showToast(`Connected to ${port} at ${baudrate} baud. Telemetry streaming active.`);
      $("#serial-dialog").close();
      await loadCoreData();
    } catch (err) {
      $("#serial-port-feedback").textContent = errorCopy(err);
      showToast(errorCopy(err), "error");
    } finally {
      if (submitBtn) {
        submitBtn.disabled = false;
        submitBtn.textContent = "Connect to Receiver";
      }
    }
  });
}

bindShell();
initialiseTheme();
renderRoute();
loadCoreData();
