// Address search with the IGN Géoplateforme geocoder (Base Adresse Nationale),
// see docs/adr/0010-geocodage-ign.md. Pure helpers (no DOM, no fetch): tested
// with `node --test`. Coordinates are [lon, lat] in WGS84.

export const GEOCODE_URL = "https://data.geopf.fr/geocodage/search";
/** The geocoder needs at least 3 characters. */
export const MIN_QUERY_LENGTH = 3;
export const MAX_SUGGESTIONS = 5;

/**
 * URL of an address search.
 * @param near [lon, lat] that ranks the nearby answers first (e.g. the map center), or null.
 * @returns {string | null} null when the text is too short to search.
 */
export function geocodeUrl(text, near = null, limit = MAX_SUGGESTIONS) {
  const q = String(text).trim();
  if (q.length < MIN_QUERY_LENGTH) return null;
  const params = new URLSearchParams({ q, limit: String(limit), autocomplete: "1" });
  if (near) {
    params.set("lon", near[0].toFixed(5));
    params.set("lat", near[1].toFixed(5));
  }
  return `${GEOCODE_URL}?${params}`;
}

/**
 * Addresses of a geocoder answer (GeoJSON).
 * @returns {{label: string, position: [number, number]}[]}
 */
export function parseGeocodeResults(json) {
  const results = [];
  for (const feature of json?.features ?? []) {
    const coordinates = feature?.geometry?.coordinates;
    const label = feature?.properties?.label;
    if (!Array.isArray(coordinates) || !label) continue;
    const [lon, lat] = coordinates.map(Number);
    if (!Number.isFinite(lon) || !Number.isFinite(lat)) continue;
    results.push({ label: String(label), position: [lon, lat] });
  }
  return results;
}
