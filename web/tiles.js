// Pure helpers to read the vector tiles of the PMTiles archive (no DOM, no map):
// a minimal Mapbox Vector Tile decoder, tile math, and the merging of the
// pieces of a segment cut by tile borders. Tested with `node --test`.
// Coordinates are [lon, lat] in WGS84; tiles follow the Web Mercator scheme.

/** List properties, written as JSON strings in the tiles (vector tiles have no lists). */
export const LIST_FIELDS = Object.freeze(["highways", "osm_way_ids", "quality_flags", "fits_targets_m"]);

// --- protocol buffers ---------------------------------------------------------

class Reader {
  constructor(bytes) {
    this.bytes = bytes;
    this.view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
    this.pos = 0;
  }

  varint() {
    // Up to 64 bits; values above 2^53 lose precision (never the case here).
    let result = 0;
    let shift = 1;
    for (;;) {
      const byte = this.bytes[this.pos++];
      result += (byte & 0x7f) * shift;
      if (byte < 0x80) return result;
      shift *= 128;
    }
  }

  zigzag() {
    const n = this.varint();
    return n % 2 === 0 ? n / 2 : -(n + 1) / 2;
  }

  /** A length-delimited field, as a sub-reader. */
  message() {
    const length = this.varint();
    const sub = new Reader(this.bytes.subarray(this.pos, this.pos + length));
    this.pos += length;
    return sub;
  }

  string() {
    const { bytes } = this.message();
    return new TextDecoder().decode(bytes);
  }

  packed() {
    const sub = this.message();
    const values = [];
    while (sub.pos < sub.bytes.length) values.push(sub.varint());
    return values;
  }

  skip(wireType) {
    if (wireType === 0) this.varint();
    else if (wireType === 1) this.pos += 8;
    else if (wireType === 2) this.pos += this.varint();
    else if (wireType === 5) this.pos += 4;
    else throw new Error(`unsupported wire type ${wireType}`);
  }

  /** Iterate over the fields: callback(fieldNumber, wireType). */
  fields(callback) {
    while (this.pos < this.bytes.length) {
      const key = this.varint();
      callback(Math.floor(key / 8), key % 8);
    }
  }
}

function readValue(reader) {
  let value = null;
  reader.fields((field, wireType) => {
    if (field === 1) value = reader.string();
    else if (field === 2) {
      value = reader.view.getFloat32(reader.pos, true);
      reader.pos += 4;
    } else if (field === 3) {
      value = reader.view.getFloat64(reader.pos, true);
      reader.pos += 8;
    } else if (field === 4 || field === 5) value = reader.varint();
    else if (field === 6) value = reader.zigzag();
    else if (field === 7) value = reader.varint() !== 0;
    else reader.skip(wireType);
  });
  return value;
}

/** Decode the geometry commands into lines of [x, y] tile coordinates. */
function readGeometry(commands) {
  const lines = [];
  let line = null;
  let x = 0;
  let y = 0;
  let i = 0;
  while (i < commands.length) {
    const command = commands[i] & 0x7;
    const count = commands[i] >> 3;
    i += 1;
    if (command === 7) {
      if (line) line.push([...line[0]]); // ClosePath
      continue;
    }
    for (let k = 0; k < count; k += 1) {
      const dx = commands[i];
      const dy = commands[i + 1];
      i += 2;
      x += dx % 2 === 0 ? dx / 2 : -(dx + 1) / 2;
      y += dy % 2 === 0 ? dy / 2 : -(dy + 1) / 2;
      if (command === 1) {
        line = [[x, y]];
        lines.push(line);
      } else {
        line.push([x, y]);
      }
    }
  }
  return lines;
}

function readFeature(reader, keys, values) {
  const feature = { id: null, type: 0, properties: {}, lines: [] };
  let tags = [];
  let commands = [];
  reader.fields((field, wireType) => {
    if (field === 1) feature.id = reader.varint();
    else if (field === 2) tags = reader.packed();
    else if (field === 3) feature.type = reader.varint();
    else if (field === 4) commands = reader.packed();
    else reader.skip(wireType);
  });
  for (let i = 0; i + 1 < tags.length; i += 2) feature.properties[keys[tags[i]]] = values[tags[i + 1]];
  feature.lines = readGeometry(commands);
  return feature;
}

function readLayer(reader) {
  const layer = { name: "", extent: 4096, features: [] };
  const keys = [];
  const values = [];
  const rawFeatures = [];
  reader.fields((field, wireType) => {
    if (field === 1) layer.name = reader.string();
    else if (field === 2) rawFeatures.push(reader.message());
    else if (field === 3) keys.push(reader.string());
    else if (field === 4) values.push(readValue(reader.message()));
    else if (field === 5) layer.extent = reader.varint();
    else reader.skip(wireType);
  });
  // Keys and values may come after the features: decode features last.
  layer.features = rawFeatures.map((sub) => readFeature(sub, keys, values));
  return layer;
}

/**
 * Decode a (decompressed) Mapbox Vector Tile.
 * @param {Uint8Array} bytes
 * @returns {Record<string, {name: string, extent: number, features: object[]}>} layers by name;
 *   each feature has `id`, `type`, `properties` and `lines` (tile coordinates).
 */
export function decodeTile(bytes) {
  const reader = new Reader(bytes);
  const layers = {};
  reader.fields((field, wireType) => {
    if (field === 3) {
      const layer = readLayer(reader.message());
      layers[layer.name] = layer;
    } else {
      reader.skip(wireType);
    }
  });
  return layers;
}

// --- tile math ----------------------------------------------------------------

/** [lon, lat] of a point given in tile coordinates. */
export function tilePointToLonLat(z, x, y, extent, [px, py]) {
  const n = 2 ** z;
  const lon = ((x + px / extent) / n) * 360 - 180;
  const merc = Math.PI * (1 - (2 * (y + py / extent)) / n);
  const lat = (Math.atan(Math.sinh(merc)) * 180) / Math.PI;
  return [lon, lat];
}

/** Tile [x, y] holding a [lon, lat] point at zoom z. */
export function lonLatToTile([lon, lat], z) {
  const n = 2 ** z;
  const rad = (lat * Math.PI) / 180;
  const x = Math.floor(((lon + 180) / 360) * n);
  const y = Math.floor(((1 - Math.log(Math.tan(rad) + 1 / Math.cos(rad)) / Math.PI) / 2) * n);
  return [Math.min(n - 1, Math.max(0, x)), Math.min(n - 1, Math.max(0, y))];
}

/** Tiles [x, y] at zoom z covering a circle of `radiusM` metres around [lon, lat]. */
export function tilesCoveringCircle([lon, lat], radiusM, z) {
  const dLat = radiusM / 111_320;
  const dLon = radiusM / (111_320 * Math.cos((lat * Math.PI) / 180));
  const [x0, y0] = lonLatToTile([lon - dLon, lat + dLat], z); // north-west corner
  const [x1, y1] = lonLatToTile([lon + dLon, lat - dLat], z); // south-east corner
  const tiles = [];
  for (let x = x0; x <= x1; x += 1) for (let y = y0; y <= y1; y += 1) tiles.push([x, y]);
  return tiles;
}

// --- segments -----------------------------------------------------------------

/** A list property written as JSON, or [] if it cannot be read (a damaged tile). */
function parseList(value) {
  try {
    const list = JSON.parse(value);
    return Array.isArray(list) ? list : [];
  } catch {
    return [];
  }
}

/** Segment properties as the page uses them: lists decoded, missing values null. */
export function normalizeProperties(properties) {
  const props = { name: null, sinuosity: null, ...properties };
  for (const field of LIST_FIELDS) {
    const value = props[field];
    if (typeof value === "string") props[field] = parseList(value);
    else if (!Array.isArray(value)) props[field] = [];
  }
  return props;
}

/**
 * Merge the pieces of segments found in several tiles into GeoJSON features.
 * @param {{z: number, x: number, y: number, layer: {extent: number, features: object[]}}[]} tiles
 * @returns {object[]} one Feature (MultiLineString) per segment id
 */
export function segmentsFromTiles(tiles) {
  const byId = new Map();
  for (const { z, x, y, layer } of tiles) {
    for (const feature of layer.features) {
      const id = feature.properties.id;
      if (id === undefined) continue;
      let merged = byId.get(id);
      if (!merged) {
        merged = {
          type: "Feature",
          id,
          properties: normalizeProperties(feature.properties),
          geometry: { type: "MultiLineString", coordinates: [] },
        };
        byId.set(id, merged);
      }
      for (const line of feature.lines) {
        merged.geometry.coordinates.push(
          line.map((point) => tilePointToLonLat(z, x, y, layer.extent, point)),
        );
      }
    }
  }
  return [...byId.values()];
}

/**
 * Read an entry of the id index (see tiles.py and lineage.py).
 * @returns {{status: "live" | "moved" | "retired", id: string | null, position: [number, number]} | null}
 *   `id` is the segment to open (null when it is gone); null for no entry.
 */
export function resolveIndexEntry(id, entry) {
  if (!Array.isArray(entry) || entry.length < 2) return null;
  const position = [Number(entry[0]), Number(entry[1])];
  if (entry.length < 3) return { status: "live", id, position };
  const target = entry[2];
  return target ? { status: "moved", id: target, position } : { status: "retired", id: null, position };
}

/** Name of the index file giving the position of a segment id (see tiles.py). */
export function indexKey(id, prefixLength = 2) {
  return String(id).split("-")[1]?.slice(0, prefixLength) ?? "";
}
