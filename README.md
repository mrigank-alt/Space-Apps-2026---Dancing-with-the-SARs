# Groundsignal - Rafsanjan simulation demo

Based on `main`. Heatmap values, the 4.2 cm peak, time progression, and alert bands
are explicitly simulated. No satellite observations or measured groundwater data
are loaded. This demo does not run the SBAS engine.

## Run without installing dependencies

From the repository root:

```powershell
python -m http.server 5173 --bind 127.0.0.1 --directory public
```

Open http://127.0.0.1:5173/rafsanjan-demo.html, or run `./start-demo.ps1`.
The regular `pnpm install` and `pnpm dev` workflow also shows this experience
through the React entry. The demo and downloads do not require FastAPI.

Choose **Draw a polygon**, click corners, and press Enter or **Finish polygon**.
Undo removes the last corner; Escape cancels. **Try sample field** loads an
illustrative boundary. Every corner must lie inside the approximate study window:
55.65-56.35 E, 30.10-30.70 N. This is not a verified city, farmland or aquifer
boundary. The actual drawn geometry can be exported as GeoJSON. A separate CSV
exports synthetic sample values. Both exports carry simulation metadata.

## What the numbers mean

The deterministic synthetic surface is normalized to a chosen **4.2 cm maximum
inside each selection**. It is not a spatial measurement model. The June 23 to
October 21, 2026 slider shows linear illustrative progression. Alert cutoffs at
1.4 and 2.8 cm are arbitrary demo bands, not validated hazard or pumping limits.
Farmer actions prioritize checking wells, irrigation infrastructure, metered
extraction and local water-manager guidance rather than automatic pumping bans.

The optional water-budget scenario divides assumed usable storage by annual
pumping minus recharge. Inputs and outputs are hypothetical and unrelated to the
selected polygon or Rafsanjan measurements. It does not predict actual aquifer
depletion, well failure, a safe operating date, or when land will finish sinking.
There is no calibrated compaction model or defined 'full depression' threshold.

Basemaps use MapLibre from a pinned CDN and OpenStreetMap / EOX tiles. EOX 2025
imagery is CC BY-NC-SA and for non-commercial prototype use. Basemap imagery is
not the source of displacement values. If external resources fail, drawing and
exports remain available on a labeled coordinate grid. No API keys are embedded;
the demo itself does not send selected polygons to a server or persist them.

## Tests

```powershell
node --test tests/demo-model.test.mjs
```

Eight geometry, simulation, export-provenance, timeline and water-budget tests
passed. Browser checks covered manual polygon drawing, synthetic heatmap and
alerts, time slider, and scenario input validation. Full Vite build validation
was unavailable because dependency installation was blocked.

## Original boundary workflow and backend reference

Iteration 1 of a groundwater-risk application for farmers. This repository contains only the reusable location-search and farm-boundary confirmation workflow. It does **not** retrieve NISAR data, calculate groundwater risk, predict groundwater conditions, or make pumping recommendations.

## What is included

- React, TypeScript, and Vite frontend
- MapLibre GL JS map with a configurable imagery provider
- MapTiler place/address geocoding plus direct coordinate search
- Browser geolocation with a permission prompt and rural demo locations
- Satellite-first map with a familiar Map/Satellite switch and floating location control
- Terra Draw multi-plot polygon, freehand trace, and rectangle drawing, editing, undo, and clearing
- Combined and per-plot geodesic area display in acres and hectares
- FastAPI endpoint accepting GeoJSON `Polygon` and `MultiPolygon` geometry in EPSG:4326 longitude-latitude order
- Coordinate, ring closure, validity, nonzero-area, and maximum-area validation
- Named, persistent farm selections with normalized MultiPolygon geometry, combined spatial metadata, reusable selection ID, and stable per-plot IDs and measurements
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
  "plot_count": 1,
  "plots": [
    {
      "plot_id": "sel_…_plot_001",
      "plot_index": 1,
      "geometry": {"type": "Polygon", "coordinates": ["…"]},
      "bbox": [-112.15, 49.78, -112.14, 49.79],
      "centroid": {"type": "Feature", "geometry": {"type": "Point", "coordinates": [-112.145, 49.785]}, "properties": {"method": "geometric centroid"}},
      "reference_point": {"type": "Feature", "geometry": {"type": "Point", "coordinates": [-112.145, 49.785]}, "properties": {"method": "point guaranteed to lie within the selection"}},
      "area": {"square_meters": 800985.986, "hectares": 80.098599, "acres": 197.927948}
    }
  ],
  "crs": "EPSG:4326",
  "coordinate_order": "longitude, latitude",
  "created_at": "2026-11-15T00:00:00Z"
}
```

Search results only reposition the map and place a reference marker. They are never submitted as the farm boundary; the farmer must draw and explicitly confirm the land selection.
