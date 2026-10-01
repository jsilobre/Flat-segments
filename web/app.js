// Map page: reads precomputed segments from vector tiles (PMTiles), filters
// them on the map (MapLibre expressions) and builds the result list from the
// tiles around the search point (filters.js, tiles.js). No build step.
import * as maplibregl from "maplibre-gl";
import { PMTiles, Protocol } from "pmtiles";

import {
  buildUrlSearch,
  DEFAULT_CRITERIA,
  featuresBounds,
  filterSegments,
  isLoop,
  lineParts,
  mapFilter,
  overviewFilter,
  parseLatLon,
  parseUrlState,
  sortResults,
} from "./filters.js";
import { decodeTile, indexKey, normalizeProperties, segmentsFromTiles, tilesCoveringCircle } from "./tiles.js";

// Published tileset, or the fictitious sample when there is none.
const DATA_DIRS = ["data/", "data/sample/"];
const BASEMAP_STYLE = "https://tiles.openfreemap.org/styles/liberty";
const FALLBACK_STYLE = {
  version: 8,
  sources: {},
  layers: [{ id: "background", type: "background", paint: { "background-color": "#eef0ea" } }],
};
const INITIAL_VIEW = { center: [1.535, 43.53], zoom: 13 };
const MAX_RESULTS = 50;
const COLORS = { flat: "#1f6fb2", climb: "#d4570f" };
// Radius of the tiles read to open a linked segment around its indexed position.
const LINK_RADIUS_M = 1500;

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
  metadata: null, // segments.json of the tileset
  dataDir: null,
  archive: null, // PMTiles
  tiles: new Map(), // "z/x/y" -> Promise of a decoded tile (or null)
  results: [],
  query: 0, // id of the latest result query (older answers are ignored)
  missingTiles: 0, // tiles of the latest query that could not be read
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

const protocol = new Protocol();
maplibregl.addProtocol("pmtiles", protocol.tile);

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
const SEGMENT_LAYERS = ["segments", "overview"];

function addDataLayers() {
  styleReady = true;
  map.addSource("position", { type: "geojson", data: emptyCollection() });
  if (state.archive) addSegmentLayers();
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

/** Segment layers: full detail from zoom 12, a light overview below. */
function addSegmentLayers() {
  if (map.getSource("segments")) return;
  const tiles = state.metadata.tiles;
  map.addSource("segments", {
    type: "vector",
    url: `pmtiles://${state.archive.source.getKey()}`,
    promoteId: { [tiles.layer]: "id", [tiles.overview_layer]: "id" },
  });
  const color = ["match", ["get", "kind"], "flat", COLORS.flat, COLORS.climb];
  const selected = ["boolean", ["feature-state", "selected"], false];
  // Zoom may only appear at the top level of an interpolate expression.
  const width = (low, high, factor) => [
    "interpolate",
    ["linear"],
    ["zoom"],
    8,
    ["case", selected, low * factor * 0.4, low * 0.4],
    11,
    ["case", selected, low * factor, low],
    16,
    ["case", selected, high * factor, high],
  ];
  const before = map.getLayer("position") ? "position" : undefined;
  const layer = (id, sourceLayer, paint, zooms) =>
    map.addLayer(
      {
        id,
        type: "line",
        source: "segments",
        "source-layer": sourceLayer,
        layout: { "line-cap": "round", "line-join": "round" },
        paint,
        ...zooms,
      },
      before,
    );
  const detail = { minzoom: tiles.minzoom };
  const overview = { minzoom: tiles.overview_minzoom, maxzoom: tiles.minzoom };
  layer("overview", tiles.overview_layer, { "line-color": color, "line-width": width(3, 7, 1), "line-opacity": 0.8 }, overview);
  layer("segments-casing", tiles.layer, { "line-color": "#ffffff", "line-width": width(6, 10, 1.6) }, detail);
  layer("segments", tiles.layer, { "line-color": color, "line-width": width(3, 7, 1.8) }, detail);
  updateMapFilters();
}

map.on("style.load", addDataLayers);

map.on("click", (event) => {
  const layers = SEGMENT_LAYERS.filter((id) => map.getLayer(id));
  const [hit] = layers.length ? map.queryRenderedFeatures(event.point, { layers }) : [];
  if (hit?.layer.id === "segments") {
    const feature = { type: "Feature", geometry: hit.geometry, properties: normalizeProperties(hit.properties) };
    selectSegment(hit.properties.id, event.lngLat, feature);
  } else if (hit) {
    // Overview: zoom in where the details (and the popup) are.
    map.flyTo({ center: event.lngLat, zoom: state.metadata.tiles.minzoom + 1 });
  } else {
    setPosition([event.lngLat.lng, event.lngLat.lat], "point choisi sur la carte");
  }
});
for (const id of SEGMENT_LAYERS) {
  map.on("mouseenter", id, () => (map.getCanvas().style.cursor = "pointer"));
  map.on("mouseleave", id, () => (map.getCanvas().style.cursor = ""));
}
// Without a position, the results follow the map.
map.on("moveend", () => {
  if (!state.position && state.archive) refreshResults();
});

function emptyCollection() {
  return { type: "FeatureCollection", features: [] };
}

// --- tiles --------------------------------------------------------------------

/** Decoded segment layer of a tile at the query zoom (cached), or null if empty. */
function loadTile(z, x, y) {
  const key = `${z}/${x}/${y}`;
  if (!state.tiles.has(key)) {
    const fetchTile = () => state.archive.getZxy(z, x, y);
    const promise = fetchTile()
      .catch(fetchTile) // one more try: mobile networks drop requests
      .then((response) => {
        if (!response) return null;
        const layer = decodeTile(new Uint8Array(response.data))[state.metadata.tiles.layer];
        return layer ? { z, x, y, layer } : null;
      });
    // A failure is not cached: the next query asks again.
    promise.catch(() => state.tiles.delete(key));
    state.tiles.set(key, promise);
  }
  return state.tiles.get(key);
}

/**
 * Segments (GeoJSON features) of the tiles covering a circle, and the number
 * of tiles that could not be read (their segments are missing).
 */
async function segmentsAround(center, radiusM) {
  const z = state.metadata.tiles.minzoom;
  const settled = await Promise.allSettled(
    tilesCoveringCircle(center, radiusM, z).map(([x, y]) => loadTile(z, x, y)),
  );
  const tiles = settled.filter((s) => s.status === "fulfilled").map((s) => s.value);
  const failed = settled.length - tiles.length;
  if (failed) console.warn(`${failed} tile(s) could not be read`, settled.find((s) => s.reason)?.reason);
  return { features: segmentsFromTiles(tiles.filter(Boolean)), failed };
}

function searchCenter() {
  if (state.position) return state.position;
  const { lng, lat } = map.getCenter();
  return [lng, lat];
}

// --- state updates ------------------------------------------------------------

function updateMapFilters() {
  if (!map.getLayer("segments")) return;
  const filter = mapFilter(state.criteria, state.pinnedId);
  map.setFilter("segments", filter);
  map.setFilter("segments-casing", filter);
  map.setFilter("overview", overviewFilter(state.criteria));
}

function applyFilters() {
  updateMapFilters();
  refreshResults();
}

/** Recompute the result list from the tiles around the search center. */
async function refreshResults() {
  if (!state.archive) return;
  const query = ++state.query;
  const center = searchCenter();
  const { features, failed } = await segmentsAround(center, state.criteria.maxDistanceM);
  if (query !== state.query) return; // a newer query was started meanwhile
  state.results = sortResults(
    filterSegments(features, state.criteria, center, state.pinnedId),
    state.sortBy,
  );
  state.missingTiles = failed;
  render();
}

function clearSelection() {
  const id = state.selectedId;
  state.selectedId = null; // before popup.remove(), which fires "close"
  if (id !== null && map.getSource("segments")) {
    map.setFeatureState({ source: "segments", sourceLayer: state.metadata.tiles.layer, id }, { selected: false });
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
  if (state.missingTiles) {
    const warning = document.createElement("li");
    warning.className = "hint warning";
    warning.textContent =
      "Une partie de la zone n'a pas pu être chargée (réseau) : la liste est incomplète. " +
      "Elle se complètera à la prochaine recherche.";
    list.prepend(warning);
  } else if (!state.results.length) {
    const empty = document.createElement("li");
    empty.className = "hint";
    empty.textContent = "Aucun segment ne correspond : élargissez les critères ou déplacez la carte.";
    list.append(empty);
  }
}

/**
 * Select a segment: highlight, popup, URL. `feature` is given when the
 * segment comes from the map or a link rather than from the result list.
 */
function selectSegment(id, lngLat = null, feature = null) {
  if (state.pinnedId !== null && id !== state.pinnedId) unpin();
  const result = state.results.find((r) => r.feature.properties.id === id);
  const selected = feature ?? result?.feature;
  if (!selected) return;
  clearSelection();
  state.selectedId = id;
  map.setFeatureState({ source: "segments", sourceLayer: state.metadata.tiles.layer, id }, { selected: true });
  const lines = lineParts(selected.geometry);
  const longest = lines.reduce((a, b) => (b.length > a.length ? b : a));
  const anchor = lngLat ?? longest[Math.floor(longest.length / 2)];
  if (!lngLat) map.fitBounds(featuresBounds([selected]), { padding: 80, maxZoom: 16 });
  popup
    .setLngLat(anchor)
    .setHTML(popupHtml(selected.properties, result?.distanceM ?? null))
    .addTo(map);
  updateUrl();
}

/** Show a segment from a link, even if the current filters hide it. */
async function focusSegment(id) {
  const notFound = () => ($("position-status").textContent = `Segment introuvable : ${id}.`);
  const { index, index_prefix_length: prefix } = state.metadata.tiles;
  const response = await fetch(`${state.dataDir}${index}/${indexKey(id, prefix)}.json`);
  const where = response.ok ? (await response.json())[id] : undefined;
  if (!where) return notFound();
  const { features } = await segmentsAround(where, LINK_RADIUS_M);
  const feature = features.find((f) => f.id === id);
  if (!feature) return notFound();
  $(`kind-${feature.properties.kind}`).checked = true;
  readControls();
  state.pinnedId = id;
  updateMapFilters();
  whenLayersReady(() => selectSegment(id, null, feature));
  if (state.position) refreshResults(); // otherwise moveend (fitBounds) does it
  return undefined;
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

/** The published tileset, or the sample one: its segments.json and folder. */
async function fetchMetadata() {
  for (const dir of DATA_DIRS) {
    const response = await fetch(`${dir}segments.json`);
    if (response.ok) return { dir, metadata: await response.json() };
  }
  throw new Error("no segments.json");
}

async function loadData() {
  const { dir, metadata } = await fetchMetadata();
  state.metadata = metadata;
  state.dataDir = dir;
  const url = new URL(`${dir}${metadata.tiles.url}`, location.href).href;
  state.archive = new PMTiles(url);
  protocol.add(state.archive);
  $("sample-banner").hidden = !metadata.sample;
  addAttribution(metadata.attribution ?? []);
  if (styleReady) addSegmentLayers();
  const [west, south, east, north] = metadata.bounds ?? [];
  if (metadata.bounds && !initial.position && !initial.id) {
    map.fitBounds([[west, south], [east, north]], { padding: 40, duration: 0 });
  }
  if (initial.position) {
    setPosition(initial.position, "lien");
    if (!initial.id) map.jumpTo({ center: initial.position, zoom: 14 });
  } else {
    $("position-status").textContent = "Aucune position : résultats autour du centre de la carte.";
    refreshResults();
  }
  if (initial.id) await focusSegment(initial.id);
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
