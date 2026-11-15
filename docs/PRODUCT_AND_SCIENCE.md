# Groundsignal product architecture and scientific method

## System architecture

Groundsignal extends the existing React/TypeScript/Vite, MapLibre, Terra Draw, FastAPI, SQLite, and Python GUNW/SBAS application. It does not replace the working farm-selection or satellite processor.

1. The browser geocodes a general location but only a farmer-drawn polygon becomes a plot.
2. FastAPI validates and normalizes the EPSG:4326 GeoJSON and stores the farm, stable plot IDs, metadata, and consent in SQLite. An R-tree indexes selection bounds.
3. The ASF catalog service checks archived GUNW collections and source coverage per plot.
4. `POST /api/v1/selections/{id}/processing-runs` creates a durable run and starts the existing background pipeline.
5. `subsidence_engine.run_pipeline(PipelineConfig(selection_id=...))` screens/downloads real observations, preserves the exterior reference context, solves the compatible pair network, and writes its manifest, numerical pixel CSV, GeoTIFFs, and Zarr time-series cube.
6. `AssessmentService` reads the numerical pixels, never a rendered image. It quality-screens and classifies each source cell, clips its real cell footprint to the saved farm, writes clickable GeoJSON plus a georeferenced classification GeoTIFF, checks public groundwater context, and stores the assessment.
7. The frontend polls progress, retrieves the saved assessment, fits the map to the farm, displays the result at source resolution, and opens a plain-language zone explanation on click.

SQLite is the authoritative pilot store. `selections`, `processing_runs`, and `assessments` are persistent and append assessment history; raw and derived artifacts are stored under `backend/data/processing/{selection_id}/{pipeline_run_id}`. Cached raw clips can be reused by the existing pipeline.

## Assessment method

### Layer A: observed ground movement

The current classifier is explicitly `exploratory_relative_concern`, not a validated hazard model.

- Grey: the source pixel fails the existing pipeline reliability mask or has no finite movement estimate.
- Green: the reliable pixel is not spatially elevated and persistent relative to the reliable pixels on that farm.
- Yellow: absolute LOS velocity is at least 1.5 robust spatial deviations above the farm median and at least 60% of nonzero time-series increments agree with the net direction.
- Red: uncertainty must be interpretable, movement must be at least two estimated standard deviations from zero, at least two robust spatial deviations above the farm median, and at least 75% temporally persistent.

The robust scale is `1.4826 × MAD`, with a small numerical floor to avoid division by zero on uniform data. These relative criteria do not claim that a particular millimetre rate is a validated damage threshold. Red is deliberately withheld when formal uncertainty is unavailable. Every zone records its class, explanation, observation dates, LOS change, persistence, coherence, uncertainty availability, plot ID, and original grid row/column.

The map preserves the processor grid. `concern_classification.tif` uses the exact source CRS, affine transform, width, and height; 0=grey, 1=green, 2=yellow, 3=red, and 255=outside/unmeasured. The frontend GeoJSON represents the same unsmoothed cells clipped to farm polygons. No interpolation is performed.

LOS motion is never silently relabelled vertical subsidence. Negative or positive LOS values retain the upstream product/processor convention recorded in the manifest. Acceleration and seasonal signals remain unavailable when the observation history is too short.

### Layer B: groundwater context

The provider service checks modern USGS Water Data OGC endpoints in supported US regions for parameter 72019 groundwater-depth field measurements. It reports site count, observation count, overlap with the satellite dates, a qualified first-to-last context statement when possible, and limitations. Outside supported coverage it returns `outside_coverage`; request failures and genuine no-data results are distinct.

Nearby wells alone do not prove aquifer relevance or causation. The current service therefore returns an insufficient relationship assessment unless a future regional adapter can establish aquifer relevance, geological context, temporal compatibility, and a defensible relationship. With insufficient evidence the complete app still provides Layer A and labels it **land movement only**.

### Forecast and recommendations

The application does not forecast a damage date because no calibrated local compaction model, validated threshold, pumping history, and uncertainty model are available. The API returns `forecast.status=not_available` and explains why. Recommendations are qualitative: review highlighted areas against field/irrigation conditions, obtain local well evidence, and refresh when newer observations exist. It never prescribes pumping volumes or claims a benefit from moving pumping within an aquifer.

## Main API

- `POST /api/v1/selections` — validate and save a farmer-confirmed farm.
- `GET /api/v1/selections/{id}` — retrieve the canonical farm and plot geometries.
- `POST /api/v1/selections/{id}/gunw-availability` — repeat the ASF coverage check.
- `POST /api/v1/selections/{id}/processing-runs` — start or refresh an analysis.
- `GET /api/v1/processing-runs/{run_id}` — retrieve progress, status, and assessment ID.
- `GET /api/v1/selections/{id}/processing-runs` — retrieve run history.
- `GET /api/v1/assessments/{assessment_id}` — retrieve one map-ready assessment.
- `GET /api/v1/selections/{id}/assessments` — retrieve completed history.
- `GET /api/v1/selections/{id}/assessments/latest` — retrieve the current assessment.
- `GET /api/v1/assessments/{id}/map` — retrieve the map-ready feature collection.
- `GET /api/v1/assessments/{id}/zones/{zone_id}` — retrieve one clickable zone and its evidence.
- `GET /api/v1/assessments/{id}/recommendations` — retrieve prioritized farmer guidance.

All errors use structured HTTP responses. Invalid/empty/oversized geometries, missing selections, absent imagery, credentials, pipeline failures, and missing assessments are represented separately. Interactive documentation is at `/docs`.

## Setup and launch

Copy `.env.example` to `.env` and `backend/.env.example` to `backend/.env`. Configure a browser-restricted MapTiler key in the frontend file. Configure NASA credentials only in `backend/.env` using `EARTHDATA_TOKEN` or the documented username/password variables. Never commit either environment file.

```bash
pnpm install
python3 -m venv backend/.venv
backend/.venv/bin/pip install -r backend/requirements.txt

backend/.venv/bin/uvicorn backend.app.main:app --reload --host 127.0.0.1 --port 8000 --env-file backend/.env
pnpm dev
```

Open `http://127.0.0.1:5173`. A direct saved-farm link is `http://127.0.0.1:5173/?selection=sel_...`.

## Verification

Run:

```bash
pnpm test:frontend
pnpm test:backend
pnpm lint
pnpm build
```

The automated suite covers geometry validation, multi-plot persistence, ASF parsing, protected technical reads, processing status, signal preservation, SBAS output, reliability filtering, conservative classification, missing uncertainty, groundwater absence, farm clipping, CRS/grid preservation, assessment persistence, and drawing-to-API flow.

### Verified real-data acceptance

On 2026-11-15 the complete local workflow was executed for an existing two-plot saved farm using actual ASF observations and configured Earthdata access. The refreshed run completed and persisted a second assessment rather than replacing the first.

- 9 compatible GUNW pairs and 10 epochs
- observation interval 2026-06-23 through 2026-10-21
- 13 farm pixels at the original 320 m grid resolution
- 13/13 pixels passed the existing reliability mask
- median observed interval LOS change: about -0.63 cm
- 13 clipped clickable zones plus an aligned classification GeoTIFF
- one plot classified Review and one Lower concern under the exploratory relative criteria
- result correctly labelled movement-only, evidence quality limited, groundwater provider unavailable for the region, forecast unavailable, and red withheld because the pair network cannot estimate formal uncertainty
- saved assessment reopened by selection link, plot switching worked, a yellow cell opened its explanation, and refresh completed from the UI using cached/retrieved real inputs

This acceptance proves operational integration and traceability; it does not validate groundwater causation or agricultural damage accuracy.

## Deployment and privacy prerequisites

The current SQLite/filesystem design is suitable for a single-machine pilot and demonstration. `APP_ENV=production` requires a technical API key and protects record, processing, history, refresh, and assessment reads. It is not a farmer identity system, and putting the technical secret in browser code would be unsafe.

Before a public multi-user launch, add a real identity provider and enforce farm ownership on every protected route, migrate records to managed PostgreSQL/PostGIS and artifacts to durable object storage, run processing through a persistent queue/worker, encrypt transport and backups, add retention/deletion controls, rate limits and monitoring, and deploy licensed map/geocoding services. These are explicit deployment prerequisites rather than hidden claims of readiness.
