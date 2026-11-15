# Groundsignal — farm boundary selection

Iteration 1 of a groundwater-risk application for farmers. This repository contains only the reusable location-search and farm-boundary confirmation workflow. It does **not** retrieve NISAR data, calculate groundwater risk, predict groundwater conditions, or make pumping recommendations.

## What is included

- React, TypeScript, and Vite frontend
- MapLibre GL JS map with a configurable imagery provider
- MapTiler place/address geocoding plus direct coordinate search
- Browser geolocation with a permission prompt and rural demo locations
- Satellite-first map with a familiar Map/Satellite switch and floating location control
- Terra Draw polygon, freehand trace, and rectangle drawing, editing, undo, and clearing
- Geodesic area display in acres and hectares
- FastAPI endpoint accepting GeoJSON `Polygon` and `MultiPolygon` geometry in EPSG:4326 longitude-latitude order
- Coordinate, ring closure, validity, nonzero-area, and maximum-area validation
- Named, persistent selections with normalized geometry, bounding box, centroid, interior reference point, area, and reusable selection ID
- Frontend geometry tests, backend validation tests, and a drawing-to-API integration test

Selections are stored in `backend/data/selections.sqlite3`. The database keeps the canonical GeoJSON record and an SQLite R-tree bounding-box index for later candidate-scene and environmental-record queries. The repository interface can be replaced with PostGIS for a multi-user production deployment without changing the service layer.

## Prerequisites

- Node.js 22.13 or newer and pnpm 11
- Python 3.11 or newer
- A browser-safe, domain-restricted MapTiler key for address/place search and the default satellite style

The application still works without a MapTiler key: it uses an EOxCloudless Sentinel-2 satellite demo with an OpenStreetMap reference overlay, an OpenStreetMap map view, Photon search-as-you-type suggestions, submitted Nominatim searches, coordinates, geolocation, and explicitly labeled demo locations. The 2025 EOxCloudless layer is CC BY-NC-SA and therefore for non-commercial prototype use only. Configure licensed production imagery and geocoding providers before deployment.

## Configuration

```bash
cp .env.example .env
cp backend/.env.example backend/.env
```

Set `VITE_MAPTILER_API_KEY` in `.env`. It must be a browser-safe public key restricted to the application's domains, never a private service credential.

When that key is blank, type-ahead suggestions use `VITE_AUTOCOMPLETE_GEOCODER_URL`, which defaults to Photon’s public demo. Submitted fallback searches use `VITE_FALLBACK_GEOCODER_URL`. The Nominatim fallback is deliberately submit-only, cached for the session, rate-limited, and attributed; it is never used for autocomplete. Point both settings to services you operate or configure MapTiler before production use.

To use another licensed imagery provider, set either:

- `VITE_MAP_STYLE_URL` to a MapLibre style URL (use `{key}` as the API-key placeholder), or
- `VITE_SATELLITE_TILE_URL`, `VITE_BASEMAP_ATTRIBUTION`, and optionally `VITE_BASEMAP_NAME` for raster XYZ tiles.

The map always displays provider attribution. Confirm that the configured provider's terms permit this use.

Backend limits can be changed with `MAX_SELECTION_AREA_HECTARES`, `MIN_SELECTION_AREA_SQUARE_METERS`, and `CORS_ORIGINS`. `SELECTION_DATABASE_PATH` controls the persistent SQLite database location. Defaults are documented in the example environment files.

## Start locally

Install dependencies once:

```bash
pnpm install
python3 -m venv backend/.venv
backend/.venv/bin/pip install -r backend/requirements.txt
```

Start the backend from the repository root:

```bash
backend/.venv/bin/uvicorn backend.app.main:app --reload --host 127.0.0.1 --port 8000 --env-file backend/.env
```

In a second terminal, start the frontend:

```bash
pnpm dev
```

Open `http://127.0.0.1:5173`. Vite proxies `/api` and `/health` to the backend. Interactive API documentation is at `http://127.0.0.1:8000/docs`.

## Tests and build

```bash
pnpm test:all
pnpm lint
pnpm build
```

## API example

Request:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/selections \
  -H 'Content-Type: application/json' \
  -d '{"label":"South pivot field","source":"drawn","geometry":{"type":"Polygon","coordinates":[[[-112.15,49.79],[-112.14,49.79],[-112.14,49.78],[-112.15,49.78],[-112.15,49.79]]]}}'
```

Representative response (the ID and timestamp vary):

```json
{
  "selection_id": "sel_…",
  "label": "South pivot field",
  "geometry": {
    "type": "Polygon",
    "coordinates": [[[-112.15, 49.79], [-112.15, 49.78], [-112.14, 49.78], [-112.14, 49.79], [-112.15, 49.79]]]
  },
  "bbox": [-112.15, 49.78, -112.14, 49.79],
  "centroid": {"type": "Feature", "geometry": {"type": "Point", "coordinates": [-112.145, 49.785]}, "properties": {"method": "geometric centroid"}},
  "reference_point": {"type": "Feature", "geometry": {"type": "Point", "coordinates": [-112.145, 49.785]}, "properties": {"method": "point guaranteed to lie within the selection"}},
  "area": {"square_meters": 800985.986, "hectares": 80.098599, "acres": 197.927948},
  "crs": "EPSG:4326",
  "coordinate_order": "longitude, latitude",
  "created_at": "2026-11-15T00:00:00Z"
}
```

Search results only reposition the map and place a reference marker. They are never submitted as the farm boundary; the farmer must draw and explicitly confirm the land selection.
