# Groundsignal — farm monitoring intake

Groundsignal lets a farmer save one or more farm plots, run the integrated NASA ASF GUNW/SBAS workflow, and view a geographically aligned land-movement concern map with plain-language guidance. It keeps land movement separate from groundwater causation: a result is only described as groundwater-related when independent evidence meets explicit eligibility requirements.

## What is included

- React, TypeScript, and Vite frontend
- MapLibre GL JS map with a configurable imagery provider
- MapTiler place/address geocoding plus direct coordinate search
- Browser geolocation with a permission prompt and rural demo locations
- Satellite-first map with a familiar Map/Satellite switch and floating location control
- Guided farmer intake for contact, crop/land use, and water source
- Terra Draw multi-plot polygon and freehand trace drawing, editing, undo, and clearing
- Combined and per-plot geodesic area display in acres and hectares
- FastAPI endpoint accepting GeoJSON `Polygon` and `MultiPolygon` geometry in EPSG:4326 longitude-latitude order
- Coordinate, ring closure, validity, nonzero-area, and maximum-area validation
- Named, persistent farm selections with normalized MultiPolygon geometry, combined spatial metadata, reusable selection ID, and stable per-plot IDs and measurements
- Automatic per-plot checks for NISAR Provisional, Beta, Validated, and Urgent Response GUNW, ARIA Sentinel-1 GUNW, and Sentinel-1 SLC source scenes through the public NASA ASF Search API
- Saved GUNW catalog status, exact match counts, and a bounded sample of product metadata and download URLs
- Integrated GUNW download/screening and SBAS processing with durable run status, pixel CSV output, cloud-optimized GeoTIFF layers, a time-series cube, quality metrics, and a machine-readable run manifest
- Persistent, versioned assessments and analysis history
- Transparent exploratory movement classification with green, yellow, red, and grey states
- Farm-clipped clickable GeoJSON zones and a source-resolution classification GeoTIFF
- Modular public-groundwater context using the modern USGS Water Data API where covered, with explicit unavailable/insufficient states elsewhere
- Plain-language explanations, qualitative urgency, evidence limitations, recommendations, plot switching, refresh, and saved-farm reopening
- Farmer-first interactive action checklist and guarded future threshold-model interface
- Frontend geometry tests, backend validation/science/geospatial tests, catalog parsing tests, and drawing-to-API integration tests

Selections and processing-run status are stored in `backend/data/selections.sqlite3`. The database keeps the canonical GeoJSON record and an SQLite R-tree bounding-box index for later candidate-scene and environmental-record queries. Generated raster/cube outputs are stored under `backend/data/processing`. The repository interface can be replaced with PostGIS plus object storage for a multi-user production deployment without changing the selection service layer.

## Prerequisites

- Node.js 22.13 or newer and pnpm 11
- Python 3.11 or newer
- A browser-safe, domain-restricted MapTiler key for address/place search and the default satellite style

For local development without a MapTiler key, the application can use an EOxCloudless Sentinel-2 layer with an OpenStreetMap reference overlay, Photon suggestions, submitted Nominatim searches, coordinates, and geolocation. The EOxCloudless layer is CC BY-NC-SA and is not suitable for a commercial deployment. Configure licensed production imagery and geocoding providers before client deployment.

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

Backend limits can be changed with `MAX_SELECTION_AREA_HECTARES`, `MIN_SELECTION_AREA_SQUARE_METERS`, and `CORS_ORIGINS`. `SELECTION_DATABASE_PATH` controls the persistent SQLite database location. `GUNW_CATALOG_ENABLED`, `ASF_SEARCH_API_URL`, `GUNW_CATALOG_TIMEOUT_SECONDS`, and `GUNW_PRODUCT_SAMPLE_LIMIT` configure the catalog check. `PROCESSING_OUTPUT_ROOT` controls generated analysis storage. Configure `EARTHDATA_TOKEN` or `EARTHDATA_USER` and `EARTHDATA_PASS` on the backend to download protected inputs; never expose them through browser variables or Git. Defaults are documented in the example environment files.

For deployment, set `APP_ENV=production` and generate a long, random `TECHNICAL_API_KEY`. Production startup fails closed when this key is missing. The key protects saved-record retrieval and catalog-refresh endpoints and must only be used by trusted server-side tools; never put it in a `VITE_` variable or browser code.

Archived GUNW products have limited geographic coverage. A `source_available` result means no archived GUNW was found but Sentinel-1 SLC source scenes intersect the plot, so on-demand interferogram processing may be possible. It is not a guarantee that the plot is eligible for a particular processing service. A `not_available` result means neither a checked GUNW product nor a Sentinel-1 SLC source scene was found at check time. A `check_failed` result means the catalog was temporarily unavailable and must not be interpreted as no coverage.

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

## Recheck a saved farm

The operational checker reads the stored plot geometries, queries ASF, updates the persistent farm record, and prints the normalized result:

```bash
backend/.venv/bin/python -m backend.scripts.check_gunw sel_your_selection_id
```

The saved record at `/api/v1/selections/{selection_id}` is the handoff package for downstream analysis. It contains each `plot_id`, exact Polygon geometry, bounding box, area, farmer/farm context, availability status, match counts, and a sample of product download URLs. When `TECHNICAL_API_KEY` is configured, request it with the `X-Technical-API-Key` header. An Earthdata Login is required to download protected NASA products.

When archived GUNW imagery is found, the farmer interface offers **Analyze my land**. The frontend creates a durable processing run and polls its progress. The backend passes the saved selection directly into the integrated GUNW screening and SBAS engine, then creates a persistent assessment, clickable concern zones, and `concern_classification.tif`. A farmer can reopen a saved result using `/?selection={selection_id}` or the same browser's saved pointer, and can request a refresh without deleting prior assessments.

See [Product architecture and scientific method](docs/PRODUCT_AND_SCIENCE.md) for the processing flow, API, classifier criteria, data sources, limitations, live-data acceptance evidence, and deployment prerequisites.

### Signal-preserving GUNW processing

The processing engine fits the spatial phase ramp only on coherent pixels in the exterior reference annulus, not on the selected farm. This prevents the screening step from accidentally fitting away a broad deformation gradient across the land. If the exterior reference area cannot support the fit, that pair is left missing instead of silently using the farm as its reference.

Each exported pair stack records its phase-processing method and sign convention. The heat-map CSV and run manifest also report the actual first and last observed epochs plus the LOS displacement change between them. This value is the last observed epoch minus the first observed epoch; it is not an annual extrapolation. Existing cached raw clips can be reprocessed without another download, but pair stacks made by the older global-ramp implementation must be regenerated.

The numerical regression suite covers signed motion, broad gradients, weak reference support, disconnected networks, and end-to-end phase-to-SBAS recovery. It verifies the implementation with synthetic truth; it does not establish accuracy for a real farm. Real-world conclusions still require independent measurements and confirmation that the exterior reference area is stable.

Run the focused checks with:

```bash
backend/.venv/bin/python backend/tests/test_los_signal_preservation.py
backend/.venv/bin/python backend/tests/test_los_signal_preservation.py --benchmark
```

## API example

Request:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/selections \
  -H 'Content-Type: application/json' \
  -d '{"label":"Miller Family Farm","source":"drawn","farmer":{"operator_name":"Taylor Miller","contact_email":"taylor@example.com"},"farm_profile":{"primary_crop_or_land_use":"Alfalfa","water_source":"groundwater_well","monitoring_goal":"groundwater_risk","location_label":"Southern Alberta"},"data_processing_consent":true,"geometry":{"type":"Polygon","coordinates":[[[-112.15,49.79],[-112.14,49.79],[-112.14,49.78],[-112.15,49.78],[-112.15,49.79]]]}}'
```

Representative response (the ID and timestamp vary):

```json
{
  "selection_id": "sel_…",
  "label": "Miller Family Farm",
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
  "farmer": {"operator_name": "Taylor Miller", "contact_email": "taylor@example.com", "contact_phone": null},
  "farm_profile": {"primary_crop_or_land_use": "Alfalfa", "water_source": "groundwater_well", "monitoring_goal": "groundwater_risk", "location_label": "Southern Alberta", "location_context": null},
  "data_processing_consent": true,
  "consent_recorded_at": "2026-11-15T00:00:00Z",
  "gunw_availability": {
    "status": "source_available",
    "provider": "NASA Alaska Satellite Facility DAAC",
    "collection": "multiple ASF GUNW collections",
    "collections_checked": ["NISAR_L2_GUNW_PROVISIONAL_V1", "ARIA_S1_GUNW", "NISAR_L2_GUNW_BETA_V1", "NISAR_L2_GUNW_V1", "NISAR_UR_L2_GUNW", "SENTINEL1_SLC"],
    "matched_product_count": 0,
    "archived_gunw_product_count": 0,
    "sentinel1_source_scene_count": 214,
    "on_demand_processing_may_be_possible": true,
    "message": "No archived GUNW product was found, but Sentinel-1 source scenes are available. On-demand interferogram processing may be possible."
  },
  "crs": "EPSG:4326",
  "coordinate_order": "longitude, latitude",
  "created_at": "2026-11-15T00:00:00Z"
}
```

Search results only reposition the map and place a reference marker. They are never submitted as the farm boundary; the farmer must draw and explicitly confirm the land selection.

## Deployment and privacy

The farmer interface deliberately does not expose internal geometry, coordinate-system, catalog, product-count, or download details. Those details remain in the protected technical record for the data pipeline.

SQLite is appropriate for a single-machine pilot. `TECHNICAL_API_KEY` prevents anonymous access to saved technical records, but it is not a farmer account system. Before a public multi-user launch, choose an identity provider, enforce per-user farm ownership on every endpoint, move records to managed PostgreSQL/PostGIS, encrypt backups and network traffic, publish privacy/retention and deletion policies, and configure licensed production map/search providers. Do not commit `.env` files, credentials, or the local SQLite database to Git.
