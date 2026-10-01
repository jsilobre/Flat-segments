// Map page: loads precomputed segments, filters them in the browser (filters.js)
// and displays them with MapLibre. No build step, no framework.
import * as maplibregl from "maplibre-gl";

import {
  buildUrlSearch,
  DEFAULT_CRITERIA,
  featuresBounds,
  filterSegments,
  isLoop,
  parseLatLon,
  parseUrlState,
  sortResults,
} from "./filters.js";

const DATA_URL = "data/segments.geojson";
const SAMPLE_URL = "data/sample-segments.geojson";
const BASEMAP_STYLE = "https://tiles.openfreemap.org/styles/liberty";
const FALLBACK_STYLE = {
  version: 8,
  sources: {},
  layers: [{ id: "background", type: "background", paint: { "background-color": "#eef0ea" } }],
};
const INITIAL_VIEW = { center: [1.535, 43.53], zoom: 13 };
const MAX_RESULTS = 50;
const COLORS = { flat: "#1f6fb2", climb: "#d4570f" };

const SURFACE_LABELS = {
  paved: "revêtu (asphalte, béton…)",
  compacted: "stabilisé",
  gravel: "gravier",
  cobbles: "pavés",
  unpaved: "terre, herbe",
  unknown: "inconnu",
};
const LIT_LABELS = { yes: "oui", partial: "en partie", no: "non", unknown: "inconnu" };
const FLAG_LABELS = {
  bridge_interpolated: "altitude interpolée sur un pont",
  tunnel_interpolated: "altitude interpolée dans un tunnel",
  gap_filled: "trou du MNT comblé",
  dem_coarse: "MNT grossier (30 m)",
};

const $ = (id) => document.getElementById(id);

const state = {
  features: [],
  results: [],
  position: null,
  criteria: { ...DEFAULT_CRITERIA },
  sortBy: "distance",
  selectedId: null,
  pinnedId: null, // segment opened by a link: shown even if the filters exclude it
};

// --- formatting ---------------------------------------------------------------

const fmt = (value, digits = 0) =>
  value === null || value === undefined
    ? "—"
    : Number(value).toLocaleString("fr-FR", { maximumFractionDigits: digits });

const formatLength = (m) => (m >= 1000 ? `${fmt(m / 1000, 2)} km` : `${fmt(m)} m`);

const kindLabel = (kind) => (kind === "flat" ? "Plat" : "Côte");

function titleOf(properties) {
  return properties.name ?? `${kindLabel(properties.kind)} de ${formatLength(properties.length_m)}`;
}

function escapeHtml(text) {
  return String(text).replace(
    /[&<>"']/g,
    (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c],
  );
}

function popupHtml(properties, distanceM) {
  const p = properties;
  const rows = [
    ["Longueur", formatLength(p.length_m)],
    ["Pente moyenne", `${fmt(p.grade_mean_pct, 1)} %`],
    ["Pente locale max", `${fmt(p.grade_max_pct, 1)} %`],
    ["D+ / D-", `${fmt(p.elev_gain_m, 1)} / ${fmt(p.elev_loss_m, 1)} m`],
    ["Traversées de route", fmt(p.n_crossings)],
    ["Carrefours", fmt(p.n_junctions)],
    ["Sinuosité", isLoop(p) ? "boucle" : fmt(p.sinuosity, 2)],
    ["Revêtement", SURFACE_LABELS[p.surface] ?? p.surface],
    ["Éclairage", LIT_LABELS[p.lit] ?? p.lit],
    ["Longueurs cibles", p.fits_targets_m.length ? p.fits_targets_m.map(formatLength).join(", ") : "—"],
    ["Score", `${fmt(p.score)} / 100`],
  ];
  if (distanceM !== null && distanceM !== undefined) rows.push(["Distance", formatLength(distanceM)]);
  const flags = p.quality_flags.map((f) => FLAG_LABELS[f] ?? f);
  const osmLinks = p.osm_way_ids
    .slice(0, 5)
    .map((id) => `<a href="https://www.openstreetmap.org/way/${id}" target="_blank" rel="noopener">${id}</a>`)
    .join(", ");
  const link = buildUrlSearch({ id: p.id }) || "?";
  return `<div class="popup">
    <h3>${escapeHtml(titleOf(p))}</h3>
    <dl>${rows.map(([k, v]) => `<dt>${k}</dt><dd>${escapeHtml(v)}</dd>`).join("")}</dl>
    ${flags.length ? `<p class="flags">⚠ ${escapeHtml(flags.join(" ; "))}</p>` : ""}
    ${p.elevation_source !== "synthetic" && osmLinks ? `<p class="hint">Voies OSM : ${osmLinks}</p>` : ""}
    <p class="hint"><a href="${escapeHtml(link)}">Lien direct vers ce segment</a></p>
  </div>`;
}

// --- map ----------------------------------------------------------------------

const map = new maplibregl.Map({
  container: "map",
  style: BASEMAP_STYLE,
  ...INITIAL_VIEW,
  attributionControl: false, // added once the data attribution is known
});
globalThis.flatSegmentsMap = map; // handy for debugging from the browser console
map.addControl(new maplibregl.NavigationControl(), "top-right");
map.addControl(new maplibregl.ScaleControl({ unit: "metric" }), "bottom-right");

let usingFallback = false;
let styleReady = false;
map.on("error", (event) => {
  // The basemap is optional: if its style cannot be loaded, keep a plain background.
  if (!styleReady && !usingFallback) {
    usingFallback = true;
    console.warn("Basemap unavailable, using a plain background.", event.error);
    map.setStyle(FALLBACK_STYLE);
  } else {
    console.error(event.error);
  }
});

const popup = new maplibregl.Popup({ maxWidth: "300px" });

function addDataLayers() {
  styleReady = true;
  map.addSource("segments", { type: "geojson", data: emptyCollection(), promoteId: "id" });
  map.addSource("position", { type: "geojson", data: emptyCollection() });
  const color = ["match", ["get", "kind"], "flat", COLORS.flat, COLORS.climb];
  const selected = ["boolean", ["feature-state", "selected"], false];
  // Zoom may only appear at the top level of an interpolate expression.
  const width = (low, high, factor) => [
    "interpolate",
    ["linear"],
    ["zoom"],
    11,
    ["case", selected, low * factor, low],
    16,
    ["case", selected, high * factor, high],
  ];
  map.addLayer({
    id: "segments-casing",
    type: "line",
    source: "segments",
    layout: { "line-cap": "round", "line-join": "round" },
    paint: { "line-color": "#ffffff", "line-width": width(6, 10, 1.6) },
  });
  map.addLayer({
    id: "segments",
    type: "line",
    source: "segments",
    layout: { "line-cap": "round", "line-join": "round" },
    paint: { "line-color": color, "line-width": width(3, 7, 1.8) },
  });
  map.addLayer({
    id: "position",
    type: "circle",
    source: "position",
    paint: {
      "circle-radius": 7,
      "circle-color": "#e0245e",
      "circle-stroke-color": "#ffffff",
      "circle-stroke-width": 2,
    },
  });
  // A style change (basemap fallback) removes our layers: redraw everything.
  render();
}

map.on("style.load", addDataLayers);

map.on("click", (event) => {
  const [hit] = map.queryRenderedFeatures(event.point, { layers: ["segments"] });
  if (hit) {
    selectSegment(hit.properties.id, event.lngLat);
  } else {
    setPosition([event.lngLat.lng, event.lngLat.lat], "point choisi sur la carte");
  }
});
map.on("mouseenter", "segments", () => (map.getCanvas().style.cursor = "pointer"));
map.on("mouseleave", "segments", () => (map.getCanvas().style.cursor = ""));

function emptyCollection() {
  return { type: "FeatureCollection", features: [] };
}

// --- state updates ------------------------------------------------------------

function applyFilters() {
  state.results = sortResults(
    filterSegments(state.features, state.criteria, state.position, state.pinnedId),
    state.sortBy,
  );
  if (state.selectedId !== null && !state.results.some((r) => r.feature.properties.id === state.selectedId)) {
    clearSelection();
  }
  render();
}

function clearSelection() {
  const id = state.selectedId;
  state.selectedId = null; // before popup.remove(), which fires "close"
  if (id !== null && map.getSource("segments")) {
    map.setFeatureState({ source: "segments", id }, { selected: false });
  }
  popup.remove();
  updateUrl();
}

/** The linked segment follows the filters again. */
function unpin() {
  state.pinnedId = null;
  applyFilters();
}

popup.on("close", () => {
  // Closed by the user (clearSelection resets selectedId before closing it).
  if (state.selectedId === null) return;
  const wasPinned = state.selectedId === state.pinnedId;
  clearSelection();
  if (wasPinned) unpin();
});

function updateUrl() {
  const search = buildUrlSearch({
    id: state.selectedId,
    kind: state.criteria.kind,
    position: state.position,
  });
  history.replaceState(null, "", search || location.pathname);
}

/** Run `callback` once our map layers exist (the style may still be loading). */
function whenLayersReady(callback) {
  if (map.getSource("segments")) callback();
  else map.once("style.load", callback); // registered after addDataLayers, so runs after it
}

function render() {
  const segments = map.getSource("segments");
  if (segments) {
    segments.setData({ type: "FeatureCollection", features: state.results.map((r) => r.feature) });
  }
  const position = map.getSource("position");
  if (position) {
    position.setData(
      state.position
        ? { type: "Feature", geometry: { type: "Point", coordinates: state.position }, properties: {} }
        : emptyCollection(),
    );
  }
  renderResults();
}

function renderResults() {
  const list = $("results");
  list.replaceChildren();
  $("result-count").textContent = `(${state.results.length})`;
  for (const { feature, distanceM } of state.results.slice(0, MAX_RESULTS)) {
    const p = feature.properties;
    const item = document.createElement("li");
    const button = document.createElement("button");
    button.type = "button";
    button.className = p.kind;
    const grade = p.kind === "flat" ? `max ${fmt(p.grade_max_pct, 1)} %` : `${fmt(p.grade_mean_pct, 1)} %`;
    const meta = [
      formatLength(p.length_m),
      grade,
      `${fmt(p.n_crossings)} traversée${p.n_crossings > 1 ? "s" : ""}`,
      `score ${fmt(p.score)}`,
    ];
    if (distanceM !== null) meta.unshift(`à ${formatLength(distanceM)}`);
    button.innerHTML = `<span class="result-title">${escapeHtml(titleOf(p))}</span>
      <span class="result-meta">${escapeHtml(meta.join(" · "))}</span>`;
    button.addEventListener("click", () => selectSegment(p.id));
    item.append(button);
    list.append(item);
  }
  if (!state.results.length) {
    const empty = document.createElement("li");
    empty.className = "hint";
    empty.textContent = "Aucun segment ne correspond : élargissez les critères.";
    list.append(empty);
  }
}

function selectSegment(id, lngLat = null) {
  if (state.pinnedId !== null && id !== state.pinnedId) unpin();
  const result = state.results.find((r) => r.feature.properties.id === id);
  if (!result) return;
  clearSelection();
  state.selectedId = id;
  map.setFeatureState({ source: "segments", id }, { selected: true });
  const coords = result.feature.geometry.coordinates;
  const anchor = lngLat ?? coords[Math.floor(coords.length / 2)];
  if (!lngLat) map.fitBounds(featuresBounds([result.feature]), { padding: 80, maxZoom: 16 });
  popup.setLngLat(anchor).setHTML(popupHtml(result.feature.properties, result.distanceM)).addTo(map);
  updateUrl();
}

/** Show a segment from a link, even if the current filters hide it. */
function focusSegment(id) {
  const feature = state.features.find((f) => f.properties.id === id);
  if (!feature) {
    $("position-status").textContent = `Segment introuvable : ${id}.`;
    return;
  }
  $(`kind-${feature.properties.kind}`).checked = true;
  readControls();
  state.pinnedId = id;
  applyFilters();
  whenLayersReady(() => selectSegment(id));
}

function setPosition(position, label) {
  state.position = position;
  const [lon, lat] = position;
  $("position-status").textContent = `Position : ${lat.toFixed(5)}, ${lon.toFixed(5)} (${label}).`;
  applyFilters();
  updateUrl();
}

// --- controls -----------------------------------------------------------------

function readControls() {
  const c = state.criteria;
  c.kind = document.querySelector('input[name="kind"]:checked').value;
  c.minLengthM = Number($("min-length").value);
  c.maxLocalGradePct = Number($("max-local-grade").value);
  let lo = Number($("min-mean-grade").value);
  let hi = Number($("max-mean-grade").value);
  if (lo > hi) [lo, hi] = [hi, lo];
  c.minMeanGradePct = lo;
  c.maxMeanGradePct = hi;
  c.maxDistanceM = Number($("max-distance").value) * 1000;
  c.noCrossing = $("no-crossing").checked;
  c.pavedOnly = $("paved-only").checked;
  state.sortBy = $("sort-by").value;

  $("max-local-grade-value").textContent = `${fmt(c.maxLocalGradePct, 1)} %`;
  $("mean-grade-value").textContent = `${fmt(lo, 1)} à ${fmt(hi, 1)} %`;
  $("max-distance-value").textContent = `${fmt(c.maxDistanceM / 1000, 1)} km`;
  for (const element of document.querySelectorAll("[data-kind]")) {
    element.hidden = element.dataset.kind !== c.kind;
  }
}

function onControlsChange() {
  readControls();
  applyFilters();
  updateUrl();
}

for (const element of document.querySelectorAll(".panel input, .panel select")) {
  if (element.id !== "latlon") element.addEventListener("input", onControlsChange);
}

$("locate").addEventListener("click", () => {
  if (!navigator.geolocation) {
    $("position-status").textContent = "Géolocalisation indisponible dans ce navigateur.";
    return;
  }
  $("position-status").textContent = "Localisation en cours…";
  navigator.geolocation.getCurrentPosition(
    ({ coords }) => {
      setPosition([coords.longitude, coords.latitude], `précision ${Math.round(coords.accuracy)} m`);
      map.flyTo({ center: state.position, zoom: 14 });
    },
    (error) => {
      $("position-status").textContent = `Localisation refusée ou impossible (${error.message}).`;
    },
    { enableHighAccuracy: true, timeout: 10000 },
  );
});

$("latlon-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const position = parseLatLon($("latlon").value);
  if (!position) {
    $("position-status").textContent = "Format attendu : latitude, longitude (ex. 43.531, 1.533).";
    return;
  }
  setPosition(position, "saisie");
  map.flyTo({ center: position, zoom: 14 });
});

// --- data loading -------------------------------------------------------------

async function fetchCollection(url) {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`${url}: HTTP ${response.status}`);
  return response.json();
}

async function loadData() {
  let collection;
  try {
    collection = await fetchCollection(DATA_URL);
  } catch {
    collection = await fetchCollection(SAMPLE_URL);
  }
  const metadata = collection.metadata ?? {};
  $("sample-banner").hidden = !metadata.sample;
  addAttribution(metadata.attribution ?? []);
  state.features = collection.features;
  const bounds = featuresBounds(state.features);
  if (bounds && !initial.position && !initial.id) map.fitBounds(bounds, { padding: 40, duration: 0 });
  applyFilters();
  if (initial.position) {
    setPosition(initial.position, "lien");
    if (!initial.id) map.jumpTo({ center: initial.position, zoom: 14 });
  }
  if (initial.id) focusSegment(initial.id);
}

function addAttribution(dataAttribution) {
  // Basemap attributions come from the style sources; segments derive from OSM.
  // Same wording as the pipeline export (export.OSM_ATTRIBUTION), so that the
  // Set drops the duplicate.
  const custom = [...new Set(["© les contributeurs d'OpenStreetMap (ODbL)", ...dataAttribution])];
  map.addControl(new maplibregl.AttributionControl({ compact: true, customAttribution: custom }));
}

const initial = parseUrlState(location.search);
if (initial.kind) $(`kind-${initial.kind}`).checked = true;
readControls();
loadData().catch((error) => {
  console.error(error);
  addAttribution([]);
  const banner = $("error-banner");
  banner.textContent = `Impossible de charger les segments (${error.message}).`;
  banner.hidden = false;
});
