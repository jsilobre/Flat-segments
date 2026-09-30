// Pure filtering logic of the web page (no DOM, no map): tested with `node --test`.
// Coordinates are [lon, lat] in WGS84, as in GeoJSON.

export const EARTH_RADIUS_M = 6371008.8;

/** Default filter values, shown when the page opens. */
export const DEFAULT_CRITERIA = Object.freeze({
  kind: "flat",
  minLengthM: 200,
  maxLocalGradePct: 2,
  minMeanGradePct: 3,
  maxMeanGradePct: 15,
  maxDistanceM: 5000,
  noCrossing: false,
  pavedOnly: false,
});

const toRad = (deg) => (deg * Math.PI) / 180;

/** Great-circle distance in metres between two [lon, lat] points. */
export function haversineMeters([lon1, lat1], [lon2, lat2]) {
  const dLat = toRad(lat2 - lat1);
  const dLon = toRad(lon2 - lon1);
  const a =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) * Math.sin(dLon / 2) ** 2;
  return 2 * EARTH_RADIUS_M * Math.asin(Math.min(1, Math.sqrt(a)));
}

/**
 * Shortest distance in metres from a point to a polyline.
 * Uses a local equirectangular projection centred on the point, accurate to
 * well under 1 % within a few tens of kilometres.
 */
export function distanceToLineMeters(point, coords) {
  const [lon0, lat0] = point;
  const kx = toRad(1) * EARTH_RADIUS_M * Math.cos(toRad(lat0));
  const ky = toRad(1) * EARTH_RADIUS_M;
  const xy = coords.map(([lon, lat]) => [(lon - lon0) * kx, (lat - lat0) * ky]);
  if (xy.length === 1) return Math.hypot(xy[0][0], xy[0][1]);
  let best = Infinity;
  for (let i = 0; i < xy.length - 1; i += 1) {
    const [ax, ay] = xy[i];
    const [bx, by] = xy[i + 1];
    const dx = bx - ax;
    const dy = by - ay;
    const len2 = dx * dx + dy * dy;
    const t = len2 > 0 ? Math.max(0, Math.min(1, -(ax * dx + ay * dy) / len2)) : 0;
    best = Math.min(best, Math.hypot(ax + t * dx, ay + t * dy));
  }
  return best;
}

/** Whether a segment's properties satisfy the criteria (distance excluded). */
export function matches(properties, criteria) {
  const p = properties;
  if (p.kind !== criteria.kind) return false;
  if (p.length_m < criteria.minLengthM) return false;
  if (criteria.noCrossing && p.n_crossings > 0) return false;
  if (criteria.pavedOnly && p.surface !== "paved") return false;
  if (p.kind === "flat") return p.grade_max_pct <= criteria.maxLocalGradePct;
  return (
    p.grade_mean_pct >= criteria.minMeanGradePct && p.grade_mean_pct <= criteria.maxMeanGradePct
  );
}

/**
 * Filter GeoJSON features.
 * @returns {{feature: object, distanceM: number | null}[]} matching features with
 *   their distance to `position` ([lon, lat] or null: no distance filter).
 */
export function filterSegments(features, criteria, position = null) {
  const results = [];
  for (const feature of features) {
    if (!matches(feature.properties, criteria)) continue;
    let distanceM = null;
    if (position) {
      distanceM = distanceToLineMeters(position, feature.geometry.coordinates);
      if (distanceM > criteria.maxDistanceM) continue;
    }
    results.push({ feature, distanceM });
  }
  return results;
}

/** Sort results in place by "distance" (nearest first) or "score" (best first). */
export function sortResults(results, sortBy) {
  const byScore = (a, b) => b.feature.properties.score - a.feature.properties.score;
  if (sortBy === "distance") {
    return results.sort((a, b) => (a.distanceM ?? Infinity) - (b.distanceM ?? Infinity) || byScore(a, b));
  }
  return results.sort(byScore);
}

/**
 * Parse a "lat, lon" string (decimal degrees, comma or space separated).
 * @returns {[number, number] | null} [lon, lat], or null if invalid.
 */
export function parseLatLon(text) {
  const match = String(text)
    .trim()
    .match(/^(-?\d+(?:\.\d+)?)\s*[,;\s]\s*(-?\d+(?:\.\d+)?)$/);
  if (!match) return null;
  const lat = Number(match[1]);
  const lon = Number(match[2]);
  if (Math.abs(lat) > 90 || Math.abs(lon) > 180) return null;
  return [lon, lat];
}

/** Bounding box [[minLon, minLat], [maxLon, maxLat]] of features, or null if empty. */
export function featuresBounds(features) {
  let minLon = Infinity;
  let minLat = Infinity;
  let maxLon = -Infinity;
  let maxLat = -Infinity;
  for (const feature of features) {
    for (const [lon, lat] of feature.geometry.coordinates) {
      minLon = Math.min(minLon, lon);
      minLat = Math.min(minLat, lat);
      maxLon = Math.max(maxLon, lon);
      maxLat = Math.max(maxLat, lat);
    }
  }
  return Number.isFinite(minLon) ? [[minLon, minLat], [maxLon, maxLat]] : null;
}
