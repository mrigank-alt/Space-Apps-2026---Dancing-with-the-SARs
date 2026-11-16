# Acquisition speed implementation and measured limits

Implemented 2026-11-16. Scope: imagery acquisition, reuse and preparation. The
observation period, product inventory, coherence masks, reference area and
scientific thresholds were not shortened or relaxed for speed.

## What changed

1. `acquisition_cache.py` indexes raw imagery by collection, raw-cache version,
   granule, polarization, requested connected-component policy and geographic
   coverage. A smaller requested extent can reuse a containing cached extent.
   The actual raster grid is checked before reuse; incomplete/rotated grids are
   rejected. Corrupt entries are skipped and can be fetched again.
2. New acquisitions use outward 0.1-degree grid-aligned enclosing extents. These
   are single rectangles, not mosaics across independently unwrapped products.
   All farm/reference calculations still operate on the original requested
   extent. `GUNW_EXTENT_STEP=0` disables expansion for controlled comparisons.
3. Native cropping matches Harmony's **interior** pixel window and geographic
   pixel-centre mask. Outward pixel rounding was explicitly rejected in live
   validation because it shifts the multilook origin. No resampling is used.
4. OS-owned request locks share identical in-flight acquisitions between
   processes using the same cache. Locks release on process exit. Cache writes
   use unique temporary files and atomic replacement. Prepared farm-specific
   arrays remain keyed separately from reusable source imagery.
5. Remote job IDs and completed raster files survive interruption. Each layer is
   marked complete only after raster validation. A failed layer is downloaded
   again while completed layers are reused. A terminal failed remote job is
   removed from the resume registry, allowing a subsequent attempt to submit
   afresh. Existing exact-extent jobs are resumed even after enabling expansion.
6. Remote submissions and file transfers have independent per-process limits
   (4 submissions, 8 transfers). Active product requests retain the previous
   automatic limit, up to 40. Authentication is validated once per acquisition
   process; threads keep separate HTTP sessions. Downloads have connection/read
   inactivity timeouts of 15/60 seconds.
7. `acquisition_events.jsonl` records per-product stage durations, download bytes,
   retries, reused transfers, cache outcomes and failures without credentials or
   signed URLs. The source manifest includes stage aggregates and concurrency
   settings; the engine manifest carries these into the backend's run summary.
   Remote/transfer aggregates **sum concurrent work**, while `runtime_seconds`
   is elapsed wall time. These numbers must not be added together as sequential
   delays. Cache probing is timed separately.
8. Preparation already overlaps downloads in `_acquire`; this behaviour remains.
   There was no measured reason to rewrite the numerical solver or parallelise
   the same preparation a second time.

## Pilot and validation

The bounded San Joaquin pilot is configured in `config/acquisition_regions.json`.
It covers the test farms plus their required exterior reference area. Its raw
acquisition extent is [-121.3, 37.7, -120.5, 38.3] and contains 25 products for
2025-12-06 through 2026-10-14. Raw compressed arrays occupy about **126.8 MB**.
The initial pilot acquisition took **358.8 seconds**. Prewarming moves this work
before the user request; it does not make NASA's service intrinsically faster.

Compared all 25 independently downloaded original exact clips against crops
from the containing pilot imagery. Phase, coherence, connected components,
transforms, optional incidence availability and prepared arrays matched
**exactly**, including missing-value masks. This verifies reuse on this dataset,
not geophysical accuracy or performance everywhere.

Three previously unprocessed boundary variants (98%, 97%, 96% of the original
farm's dimensions) retained all 25 pairs and made zero Harmony requests:

| Boundary variant | Source search/preparation | Pipeline + assessment |
| --- | ---: | ---: |
| 98% | 10.2 s | 16.09 s |
| 97% | 9.7 s | 15.37 s |
| 96% | 9.6 s | 13.55 s |

Median source time was 9.7 seconds, versus the earlier 238.4-second cold source
run (95.9% less user-visible source latency). Median pipeline plus assessment
time was 15.37 seconds. These are different boundary variants on prepared
coverage, **not a controlled claim of faster fresh NASA acquisition**. They
exclude the browser rendering time and the earlier imagery-availability check.
No benchmark assessments were inserted into the application's selection history.

An incremental pilot refresh found all 25 products cached and finished in
7.7 seconds with no NASA jobs. The legacy migration registered 75 existing raw
extents without downloading or modifying their arrays.

Live evidence (local, ignored by Git):

- `backend/data/acquisition_experiments/pilot/equivalence.json`
- `backend/data/acquisition_experiments/pilot/warm_farm/three_boundaries.json`
- `backend/data/acquisition_experiments/pilot/prefetch/run_manifest.json`
- `backend/data/acquisition_experiments/regions/` refresh reports
- `backend/data/acquisition_experiments/benchmark_72a5185b/` cold/warm trials

## Operation and reproduction

From PowerShell:

```powershell
cd "C:\Users\prati\OneDrive\Documents\New project\Space-Apps-2026---Dancing-with-the-SARs-fresh"
python scripts/prefetch_regions.py
```

This command runs independently of the API queue. It refreshes the explicitly
configured regions/dates once, acquiring only missing products. Run it from the
deployment's background scheduler when new imagery should be checked. No OS
scheduled task or indefinitely running service is installed by this change.
Update the explicit date range to include newly desired observations. This
prevents an implicit expansion of the analysis period or storage footprint.

To register existing clips using their saved selection and inventory provenance:

```powershell
python scripts/index_existing_imagery.py
```

To run controlled cold/warm acquisition trials:

```powershell
python scripts/benchmark_acquisition.py --selection-id sel_18a6abf32da742279539cd54017393e2 --workers 25 16 8 4 --repeats 1
```

Each cold trial uses an isolated cache, the full inventory and exact extents;
its warm repeat uses that same trial's cache. Trials are sequential so they do
not compete with each other. Avoid other live acquisitions while benchmarking.
More rounds are needed to quantify remote-service variability; alternating
rounds reverse the order. Local cache isolation cannot disable NASA-side reuse.
The benchmark leaves its bounded trial caches intact for inspection/resumption.

To reproduce the independent spatial comparison:

```powershell
python scripts/verify_spatial_cache.py --selection-id sel_18a6abf32da742279539cd54017393e2 --inventory backend/data/processing/sel_18a6abf32da742279539cd54017393e2/20261116T042144Z_f460dd4c/source_screening/asf_inventory.csv --output backend/data/acquisition_experiments/pilot/equivalence.json
```

The comparison explicitly excludes the original exact-cache file as a candidate,
so it cannot accidentally validate a raster against itself.

## Limits and rollout

- Prepared coverage meets the sub-minute target in this pilot. Arbitrary cold
  locations still depend on live NASA processing; a 50–80% cold improvement is
  not established by the warm results.
- Geographic coverage alone is insufficient: the selected products and dates
  must also exist in the cache. A different track or newly available product can
  require acquisition.
- Expanded extents consume more storage and may make a cold job larger. The
  0.1-degree setting is deliberately bounded and configurable. There is no
  automatic eviction in this change; refresh reports include cache bytes.
- The live equivalence validation covers one NISAR track and projected grid.
  Re-run it when changing provider versions, grids or acquisition semantics.
  Wrapped/date-line bounding boxes are rejected rather than silently cropped.
- Concurrency semaphores are per process. Duplicate request locks are shared by
  processes on the same filesystem, not across machines. Distributed deployment
  would require shared coordination and cache infrastructure.
- The acquisition script is launched afresh for each backend run, so its new
  caching behaviour is available to subsequent runs. Restart the backend to
  load the additional engine timing fields and earlier queue changes.

Validation: 70 backend tests passed, including numerical preservation, native
crop/mask regressions, cache corruption, concurrent duplicate suppression and
completed-layer recovery after a simulated interrupted download. Existing
FastAPI/Shapely deprecation warnings remain. `git diff --check` passed.
