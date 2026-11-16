# A1: Accuracy benchmark and calibration plan

## Purpose

Turn the current classifier safeguards into a testable calibration workflow. A1 is not complete when a comparison file is merely stored: an independent, spatially held-out benchmark must pass the gates below, and its approved calibration must be loaded by the assessment model with a recorded version. Until suitable reference measurements exist, the model must remain explicitly uncalibrated and must not claim absolute ground-motion accuracy.

## Reference data to collect

One record per independent farm/site and observation interval, including:

- GNSS or levelling displacement/rate, its uncertainty, units, measurement dates, and reference frame;
- the SAR LOS unit vector and acquisition dates needed to project ground truth into the observed LOS direction;
- farm and plot geometries, SAR grid/CRS, valid-data mask, coherence/quality mask, and the exact processing/model version;
- reference station location and stability evidence, plus any levelling datum/benchmark checks;
- weather, crop/field operation notes, and known groundwater or infrastructure events when available.

Ground truth must be compared over matched dates, spatial support, and LOS direction. Vertical GNSS alone is not a valid direct target for LOS velocity unless geometry and horizontal components are accounted for. Do not treat the previous algorithm's output as ground truth.

## Benchmark protocol

1. Freeze the raw inputs, software revision, quality masks, and model configuration; retain a manifest hash for every run.
2. Match model estimates to reference observations by site, time interval, and spatial footprint. Exclude pairs that cannot be reconciled and report the exclusion count/reasons.
3. Split by farm/site (never random pixels): development/calibration sites, a validation set for threshold selection, and a final untouched test set. Also report a temporal holdout where enough dates exist. Keep neighboring plots and pixels from the same farm in one split.
4. Report continuous errors (bias, MAE, RMSE, median absolute error, and correlation), uncertainty calibration (one- and two-sigma interval coverage and standardized residuals), and concern-class precision/recall/F1, false-alarm rate, and missed-event rate. Include per-site results and bootstrap confidence intervals clustered by site, not by pixel.
5. Report coverage, usable area, spatial cluster support, persistence availability, and performance by farm size, incidence geometry, season, and reference quality. Compare against a zero-motion baseline and a simple robust farm-median baseline.
6. Run synthetic null/noise cases, injected coherent events, spatially isolated outliers, missing epochs, uneven cadence, and changing masks. Synthetic runs test false-positive behavior and failure handling; they do not replace the independent real-world test.

## Calibration and model integration

Use development sites to calibrate uncertainty scale and any minimum effect, significance, persistence, coverage, and spatial-support thresholds. Select thresholds on validation sites against a documented false-alarm target and event-recall objective. Freeze the selected values before final testing. Store them in a versioned calibration artifact with its data split, source-data hashes, method, validation metrics, approver, and expiry/review date. The assessment service should load only a validated artifact, attach its version to every assessment, and otherwise use conservative uncalibrated output labels. Never tune thresholds on the final test set.

The current model is already using the A1 classifier corrections in `backend/app/assessment.py`: its farm baseline uses reliable in-farm pixels, LOS velocity remains signed, a minimum effect scale and uncertainty gate are applied, and labels are explicitly relative to the farm baseline. Coverage and connected spatial support also limit farm-level summaries. These are active model behavior, not a dormant proposal. The next model update is numeric calibration from the benchmark above; no defensible calibration values can be fitted from the repository's algorithm-to-algorithm comparison alone.

## Acceptance gates

Before enabling calibrated labels, require: sufficient independent sites and both event/null examples; no material site-level bias concealed by the pooled average; uncertainty coverage compatible with nominal intervals within reported confidence bounds; false alarms below the predeclared validation target; useful recall on held-out events; stable performance under the documented missing-data/noise simulations; and a final untouched test report. Set numeric targets with the domain team before evaluating the holdout, not after seeing its results.

## Deliverables and status

- Frozen reference dataset specification and split manifest.
- Reproducible benchmark report and synthetic stress report.
- Versioned calibration artifact and model integration change only after gates pass.
- Current state: the classifier corrections are active and the benchmark/calibration plan is ready, but no independent ground truth is included in this repository. Numeric recalibration and an accuracy claim remain gated on acquiring the reference dataset.
