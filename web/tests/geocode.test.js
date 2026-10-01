import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import { GEOCODE_URL, geocodeUrl, MAX_SUGGESTIONS, parseGeocodeResults } from "../geocode.js";

// Answer of the geocoder to "12 chemin de la plaine lab" near Labège (01/10/2026).
const answer = JSON.parse(
  readFileSync(new URL("./fixtures/geocode-12-chemin-de-la-plaine.json", import.meta.url), "utf8"),
);

test("geocodeUrl searches with autocompletion near a point", () => {
  const url = new URL(geocodeUrl("  12 chemin de la plaine ", [1.533, 43.531]));
  assert.equal(`${url.origin}${url.pathname}`, GEOCODE_URL);
  assert.equal(url.searchParams.get("q"), "12 chemin de la plaine");
  assert.equal(url.searchParams.get("limit"), String(MAX_SUGGESTIONS));
  assert.equal(url.searchParams.get("autocomplete"), "1");
  assert.equal(url.searchParams.get("lat"), "43.53100");
  assert.equal(url.searchParams.get("lon"), "1.53300");
  assert.equal(new URL(geocodeUrl("Labège")).searchParams.has("lat"), false);
});

test("geocodeUrl refuses texts too short for the geocoder", () => {
  assert.equal(geocodeUrl(""), null);
  assert.equal(geocodeUrl(" ab "), null);
});

test("parseGeocodeResults reads labels and [lon, lat] positions", () => {
  const results = parseGeocodeResults(answer);
  assert.equal(results.length, 3);
  assert.equal(results[0].label, "12 Chemin de la Plaine 31670 Labège");
  const [lon, lat] = results[0].position;
  assert.ok(Math.abs(lon - 1.545) < 0.01 && Math.abs(lat - 43.533) < 0.01, String(results[0].position));
});

test("parseGeocodeResults skips malformed answers", () => {
  assert.deepEqual(parseGeocodeResults(null), []);
  assert.deepEqual(parseGeocodeResults({ code: 400, message: "q: must contain between 3 and 200 chars" }), []);
  const features = [
    { geometry: { coordinates: [1, 43] }, properties: {} },
    { geometry: null, properties: { label: "Sans point" } },
    { geometry: { coordinates: ["x", 43] }, properties: { label: "Mauvais point" } },
    { geometry: { coordinates: [1.5, 43.5] }, properties: { label: "Labège" } },
  ];
  assert.deepEqual(parseGeocodeResults({ features }), [{ label: "Labège", position: [1.5, 43.5] }]);
});
