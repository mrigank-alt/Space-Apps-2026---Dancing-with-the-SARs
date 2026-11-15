from __future__ import annotations

import hashlib
import csv
import json
import logging
import platform
import shutil
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import rasterio
from rasterio.mask import mask as raster_mask
from rasterio.shutil import copy as raster_copy
from shapely.geometry import mapping, shape

from .config import PipelineConfig
from .sbas import SbasResult, invert_sbas

log = logging.getLogger("subsidence_engine")


def _gradient(rate: np.ndarray, transform: tuple[float, ...]) -> np.ndarray:
    px_x, px_y = abs(transform[0]), abs(transform[4])
    gy, gx = np.gradient(rate.astype(np.float32), px_y, px_x)
    return np.hypot(gx, gy) * 1000.0  # cm/km


def _write_cog(path: Path, data: np.ndarray, transform, crs, unit: str, nodata: float = -9999.0) -> None:
    data = np.asarray(data, dtype=np.float32)
    profile = {
        "driver": "GTiff", "height": data.shape[0], "width": data.shape[1], "count": 1,
        "dtype": "float32", "crs": crs, "transform": transform, "nodata": nodata,
        "tiled": True, "blockxsize": 256, "blockysize": 256, "compress": "deflate",
    }
    encoded = np.where(np.isfinite(data), data, nodata).astype(np.float32)
    tmp = path.with_suffix(".tmp.tif")
    with rasterio.open(tmp, "w", **profile) as dst:
        dst.write(encoded, 1)
        dst.update_tags(UNIT=unit)
    raster_copy(tmp, path, driver="COG", compress="DEFLATE")
    tmp.unlink()


def run_pipeline(config: PipelineConfig | dict[str, Any]) -> dict[str, Any]:
    """Run batched SBAS on an AOI-masked NPZ pair stack and publish an additive run folder.

    NPZ keys: pair_displacement_cm (pair,y,x), pair_start/end (pair), epoch_days (time),
    weights (pair,y,x; inverse variance), transform (GDAL affine), crs_wkt (string).
    """
    run_started = time.perf_counter()
    source_started = None
    source_screening_seconds = None
    source_metrics: dict[str, Any] = {}
    legacy_rate = None
    cfg = config if isinstance(config, PipelineConfig) else PipelineConfig.model_validate(config)
    if cfg.reference_point is not None:
        raise NotImplementedError("Reference-point override is not wired into the source screening stage yet.")
    geojson = cfg.geometry
    selection_id = cfg.selection_id
    if geojson is None:
        db = Path(__file__).resolve().parents[1] / "backend" / "data" / "selections.sqlite3"
        import sqlite3
        with sqlite3.connect(db) as con:
            if selection_id == "latest":
                row = con.execute("SELECT selection_id, record_json FROM selections ORDER BY created_at DESC, id DESC LIMIT 1").fetchone()
            else:
                row = con.execute("SELECT selection_id, record_json FROM selections WHERE selection_id=?", (selection_id,)).fetchone()
        if not row:
            raise ValueError(f"Saved selection not found: {cfg.selection_id}")
        selection_id = row[0]
        geojson = json.loads(row[1])["geometry"]
    geom = shape(geojson)
    if geom.is_empty or not geom.is_valid or geom.geom_type not in {"Polygon", "MultiPolygon"}:
        raise ValueError("AOI must be a valid GeoJSON Polygon or MultiPolygon")
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ_") + uuid.uuid4().hex[:8]
    run_dir = cfg.output_root / cfg.aoi_id / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    stack_path = cfg.pair_stack_npz
    if stack_path is None:
        source_dir = run_dir / "source_screening"
        source_dir.mkdir()
        script = Path(__file__).resolve().parents[1] / "nisar_selection_subsidence.py"
        cache_dir = cfg.output_root / ".cache" / cfg.aoi_id
        cache_dir.mkdir(parents=True, exist_ok=True)
        # Migrate reusable raw and multilooked clips from prior per-run caches.
        prior_caches = sorted((cfg.output_root / cfg.aoi_id).glob("*/source_screening/clip_cache"),
                              key=lambda p: p.stat().st_mtime, reverse=True)
        for old_cache in prior_caches:
            for cached in old_cache.glob("*.npz"):
                target = cache_dir / cached.name
                if not target.exists():
                    shutil.copy2(cached, target)
        command = [sys.executable, str(script), "--output", str(source_dir), "--cache-dir", str(cache_dir),
                   "--no-plots", "--serial", "--engine-export-only"]
        if not cfg.remove_ramp:
            command += ["--no-remove-ramp"]
        if selection_id:
            command += ["--selection-id", selection_id]
        else:
            aoi_path = run_dir / "aoi.geojson"
            aoi_path.write_text(json.dumps(geojson), encoding="utf-8")
            command += ["--geojson", str(aoi_path), "--label", cfg.aoi_id]
        if cfg.start_date:
            command += ["--start-date", cfg.start_date]
        if cfg.end_date:
            command += ["--end-date-exclusive", cfg.end_date]
        if cfg.phase_sign != 1.0:
            command += ["--phase-sign", str(cfg.phase_sign)]
        source_started = time.perf_counter()
        completed = subprocess.run(command, capture_output=True, text=True)
        source_screening_seconds = time.perf_counter() - source_started
        if completed.returncode:
            raise RuntimeError("GUNW acquisition/screening failed:\n" + completed.stderr[-4000:] + completed.stdout[-2000:])
        stacks = list(source_dir.rglob("pair_stack_for_engine.npz"))
        if len(stacks) != 1:
            raise RuntimeError(f"Expected one prepared pair stack, found {len(stacks)}.\n"
                               + completed.stdout[-5000:] + completed.stderr[-3000:])
        stack_path = stacks[0]
    if not stack_path.is_file():
        raise FileNotFoundError(f"pair stack not found: {stack_path}")
    source_dir = stack_path.parents[1]
    source_manifest_path = source_dir / "run_manifest.json"
    if not source_metrics and source_manifest_path.is_file():
        source_metrics = json.loads(source_manifest_path.read_text(encoding="utf-8"))
        source_screening_seconds = source_metrics.get("runtime_seconds", source_screening_seconds)
    if legacy_rate is None:
        legacy_maps = list(source_dir.rglob("rate_map.npz"))
        if legacy_maps:
            with np.load(legacy_maps[0], allow_pickle=False) as legacy:
                legacy_rate = legacy["rate_cm_year"].astype(np.float32)
    with np.load(stack_path, allow_pickle=False) as z:
        data = {key: z[key] for key in z.files}
    phase_processing = str(data.get("phase_processing", "unknown_preprocessed_input"))
    if phase_processing == "unknown_preprocessed_input":
        log.warning("Input stack has no phase-processing provenance. Regenerate from cached clips to apply reference-only ramp fitting.")
    if "pair_coherence" not in data:
        data["pair_coherence"] = np.full_like(data["pair_displacement_cm"], np.nan, dtype=np.float32)
    if "incidence_angle_deg" not in data:
        data["incidence_angle_deg"] = np.full_like(data["pair_displacement_cm"], np.nan, dtype=np.float32)
    transform = tuple(float(v) for v in data["transform"])
    crs_wkt = str(data["crs_wkt"])
    solver_started = time.perf_counter()
    result = invert_sbas(data["pair_displacement_cm"], data["pair_start"], data["pair_end"],
                         data["epoch_days"], data["weights"], cfg.minimum_valid_pairs)
    sbas_seconds = time.perf_counter() - solver_started
    raster_dir = run_dir / "rasters"
    if not cfg.csv_only:
        raster_dir.mkdir(parents=True, exist_ok=False)
    from rasterio.features import geometry_mask
    from rasterio.transform import Affine
    # Input stack is already on its common grid; mask outputs using the same GeoJSON AOI.
    # The geometry must be supplied in the stack CRS to avoid silently misprojecting.
    if crs_wkt != "EPSG:4326" and not geom.is_empty:
        from pyproj import Transformer
        from shapely.ops import transform as transform_geometry
        transformer = Transformer.from_crs("EPSG:4326", crs_wkt, always_xy=True)
        geom = transform_geometry(transformer.transform, geom)
    mask = geometry_mask([mapping(geom)], out_shape=result.velocity_cm_year.shape,
                         transform=Affine(*transform), invert=True)
    for field_name in result.__dataclass_fields__:
        value = getattr(result, field_name)
        if value.ndim == 2 and value.dtype == bool:
            value &= mask
        elif field_name == "valid_pair_count":
            value[~mask] = 0
        elif value.ndim == 2:
            value[~mask] = np.nan
        elif value.ndim == 3:
            value[:, ~mask] = np.nan

    # Metric gradient uses actual common-grid pixel size.
    gx, gy = np.gradient(result.velocity_cm_year, abs(transform[0]), abs(transform[4]))
    gradient = np.hypot(gx, gy) * 1000.0
    valid_fraction = np.isfinite(result.displacement_cm).sum(axis=0).astype(np.float32) / result.displacement_cm.shape[0]
    coh = data["pair_coherence"]
    coh_count = np.isfinite(coh).sum(axis=0)
    coherence = np.divide(np.nansum(coh, axis=0), coh_count,
                          out=np.full(result.velocity_cm_year.shape, np.nan, np.float32), where=coh_count > 0)
    angle_data = data["incidence_angle_deg"]
    incidence = (np.nanmedian(np.where(np.isfinite(angle_data), angle_data, np.nan), axis=0)
                 if np.isfinite(angle_data).any()
                 else np.full(result.velocity_cm_year.shape, np.nan, np.float32))
    vertical_scale = np.cos(np.deg2rad(incidence))
    has_incidence = np.isfinite(incidence) & (vertical_scale > 0.1)
    vertical_velocity = np.divide(result.velocity_cm_year, vertical_scale,
                                  out=np.full_like(result.velocity_cm_year, np.nan), where=has_incidence)
    vertical_velocity_sigma = np.divide(result.velocity_sigma_cm_year, vertical_scale,
                                        out=np.full_like(result.velocity_sigma_cm_year, np.nan), where=has_incidence)
    vertical_displacement = np.divide(result.displacement_cm, vertical_scale[None, :, :],
                                      out=np.full_like(result.displacement_cm, np.nan),
                                      where=has_incidence[None, :, :])
    vertical_displacement_sigma = np.divide(result.displacement_sigma_cm, vertical_scale[None, :, :],
                                            out=np.full_like(result.displacement_sigma_cm, np.nan),
                                            where=has_incidence[None, :, :])
    # Observed interval change, not annual velocity multiplied by requested dates.
    los_change = result.displacement_cm[-1] - result.displacement_cm[0]
    vertical_change = vertical_displacement[-1] - vertical_displacement[0]
    reliability = (result.connected & (coherence >= 0.4) & (result.valid_pair_count >= cfg.minimum_valid_pairs)
                   & (valid_fraction >= cfg.reliability_min_valid_fraction))
    # A tree network yields point estimates but cannot estimate a residual variance.
    uncertainty_available = np.isfinite(vertical_velocity_sigma)
    layers = {
        "cumulative_los_displacement": (result.displacement_cm, "cm"),
        "mean_velocity_los": (result.velocity_cm_year, "cm/year"),
        "mean_velocity_los_sigma_1sigma": (result.velocity_sigma_cm_year, "cm/year"),
        "fit_residual_rms": (result.residual_rms_cm, "cm"),
        "valid_pair_count": (result.valid_pair_count.astype(np.float32), "count"),
        "valid_time_fraction": (valid_fraction, "fraction"),
        "reliability_mask": (reliability.astype(np.float32), "boolean"),
        "differential_subsidence_gradient": (gradient.astype(np.float32), "cm/km"),
    }
    layer_meta = []
    for name, (array, unit) in (layers.items() if not cfg.csv_only else []):
        if array.ndim == 3:
            continue  # displacement cube is written to Zarr
        path = raster_dir / f"{name}.tif"
        _write_cog(path, array, Affine(*transform), crs_wkt, unit)
        layer_meta.append({"name": name, "path": f"rasters/{path.name}", "units": unit,
                           "nodata": -9999, "dtype": "float32", "crs": crs_wkt})

    # One row per selected grid pixel with scalar layers and the full LOS time series.
    csv_path = run_dir / "heatmap_pixels.csv"
    scalar_names = [name for name, (array, _unit) in layers.items() if array.ndim == 2]
    row_idx, col_idx = np.nonzero(mask)
    x_coords = transform[2] + (col_idx + 0.5) * transform[0] + (row_idx + 0.5) * transform[1]
    y_coords = transform[5] + (col_idx + 0.5) * transform[3] + (row_idx + 0.5) * transform[4]
    from pyproj import Transformer
    to_lonlat = Transformer.from_crs(crs_wkt, "EPSG:4326", always_xy=True)
    lon, lat = to_lonlat.transform(x_coords, y_coords)
    epoch_labels = [str(x)[:10] for x in data.get("epoch_dates", data["epoch_days"])]
    gradient_vertical = _gradient(vertical_velocity, transform)
    gradient_los = _gradient(result.velocity_cm_year, transform)
    fields = ["row", "column", "x", "y", "longitude", "latitude", "los_velocity_cm_year",
              "los_velocity_sigma_cm_year_1sigma", "vertical_velocity_cm_year",
              "vertical_velocity_sigma_cm_year_1sigma", "incidence_angle_deg", "coherence_mean",
              "valid_pair_count", "valid_time_fraction", "quality_mask", "uncertainty_available",
              "differential_los_cm_year_per_km", "differential_subsidence_cm_year_per_km", "acceleration_cm_year2",
              "seasonal_velocity_cm_year", "long_term_velocity_cm_year",
              "los_displacement_change_cm", "vertical_displacement_change_cm",
              "measurement_start", "measurement_end"]
    fields += [f"cumulative_los_cm_{d}" for d in epoch_labels]
    fields += [f"cumulative_vertical_cm_{d}" for d in epoch_labels]
    fields += [f"cumulative_los_sigma_cm_{d}_1sigma" for d in epoch_labels]
    fields += [f"cumulative_vertical_sigma_cm_{d}_1sigma" for d in epoch_labels]
    with csv_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(fields)
        for k, (r, c) in enumerate(zip(row_idx, col_idx)):
            acc = np.nan  # four months cannot support the configured six-month acceleration minimum
            seasonal = np.nan  # seasonal/long-term decomposition requires at least twelve months
            long_term = np.nan
            writer.writerow([int(r), int(c), float(x_coords[k]), float(y_coords[k]), float(lon[k]), float(lat[k]),
                             result.velocity_cm_year[r, c], result.velocity_sigma_cm_year[r, c],
                             vertical_velocity[r, c], vertical_velocity_sigma[r, c], incidence[r, c], coherence[r, c],
                             int(result.valid_pair_count[r, c]), valid_fraction[r, c], int(reliability[r, c]),
                             int(uncertainty_available[r, c]), gradient_los[r, c], gradient_vertical[r, c],
                             acc, seasonal, long_term, los_change[r, c], vertical_change[r, c],
                             epoch_labels[0], epoch_labels[-1], *result.displacement_cm[:, r, c].tolist(),
                             *vertical_displacement[:, r, c].tolist(),
                             *result.displacement_sigma_cm[:, r, c].tolist(),
                             *vertical_displacement_sigma[:, r, c].tolist()])

    comparison = None
    if legacy_rate is not None and legacy_rate.shape == result.velocity_cm_year.shape:
        both = mask & np.isfinite(legacy_rate) & np.isfinite(result.velocity_cm_year)
        if both.any():
            delta = result.velocity_cm_year[both] - legacy_rate[both]
            comparison = {
                "comparison": "new SBAS velocity vs legacy robust-rate velocity on identical inputs; not independent ground truth",
                "n_pixels": int(both.sum()), "bias_cm_year": float(np.mean(delta)),
                "mae_cm_year": float(np.mean(np.abs(delta))), "rmse_cm_year": float(np.sqrt(np.mean(delta**2))),
                "correlation": float(np.corrcoef(result.velocity_cm_year[both], legacy_rate[both])[0, 1]) if both.sum() > 1 else None,
            }
            if not cfg.csv_only:
                (run_dir / "accuracy_benchmark.json").write_text(json.dumps(comparison, indent=2), encoding="utf-8")

    in_aoi = result.connected & mask
    reliable_in_aoi = reliability & mask
    quality_summary = {
        "aoi_pixel_count": int(mask.sum()), "connected_solution_pixels": int(in_aoi.sum()),
        "reliable_pixels": int(reliable_in_aoi.sum()),
        "reliable_pixel_fraction": float(reliable_in_aoi.sum() / max(mask.sum(), 1)),
        "median_velocity_los_cm_year": float(np.nanmedian(result.velocity_cm_year[mask])) if np.isfinite(result.velocity_cm_year[mask]).any() else None,
        "median_los_displacement_change_cm": float(np.nanmedian(los_change[mask])) if np.isfinite(los_change[mask]).any() else None,
        "median_velocity_sigma_1sigma_cm_year": float(np.nanmedian(result.velocity_sigma_cm_year[mask])) if np.isfinite(result.velocity_sigma_cm_year[mask]).any() else None,
        "median_fit_residual_rms_cm": float(np.nanmedian(result.residual_rms_cm[mask])) if np.isfinite(result.residual_rms_cm[mask]).any() else None,
    }
    validation_rows = [
        ("source_search_download_and_stack_export_seconds", source_screening_seconds, "seconds"),
        ("sbas_solver_seconds", sbas_seconds, "seconds"),
        ("elapsed_total_seconds", time.perf_counter() - run_started, "seconds"),
        ("source_pairs_fetched", source_metrics.get("clips_fetched_from_harmony"), "pairs"),
        ("aoi_pixel_count", quality_summary["aoi_pixel_count"], "pixels"),
        ("connected_solution_pixels", quality_summary["connected_solution_pixels"], "pixels"),
        ("reliable_pixel_fraction", quality_summary["reliable_pixel_fraction"], "fraction"),
        ("median_velocity_los_cm_year", quality_summary["median_velocity_los_cm_year"], "cm/year"),
        ("median_velocity_sigma_1sigma_cm_year", quality_summary["median_velocity_sigma_1sigma_cm_year"], "cm/year"),
        ("median_fit_residual_rms_cm", quality_summary["median_fit_residual_rms_cm"], "cm"),
    ]
    if comparison:
        validation_rows.extend((f"legacy_comparison_{k}", v, "cm/year" if k.endswith("cm_year") else "unitless")
                               for k, v in comparison.items() if isinstance(v, (float, int)))
    if not cfg.csv_only:
        with (run_dir / "validation_metrics.csv").open("w", newline="", encoding="utf-8") as stream:
            writer = csv.writer(stream)
            writer.writerow(["metric", "value", "units"])
            writer.writerows(validation_rows)
    try:
        import zarr
        cube_path = run_dir / "cube" / "timeseries.zarr"
        if cfg.csv_only:
            cube_path = None
        else:
            cube_path.parent.mkdir(parents=True, exist_ok=True)
            root = zarr.open_group(str(cube_path), mode="w")
            root.create_array("displacement_cm", data=result.displacement_cm, chunks=(1, min(256, mask.shape[0]), min(256, mask.shape[1])))
            root.create_array("displacement_sigma_cm_1sigma", data=result.displacement_sigma_cm,
                              chunks=(1, min(256, mask.shape[0]), min(256, mask.shape[1])))
            root.create_array("time_days", data=np.asarray(data["epoch_days"], dtype=np.float64))
            root.attrs.update({"crs_wkt": crs_wkt, "transform": transform, "units": "cm", "reference": "first epoch fixed to zero"})
    except ImportError:
        log.warning("zarr is unavailable; displacement cube not written")
        cube_path = None

    run_config = cfg.model_dump(mode="json")
    config_hash = hashlib.sha256(json.dumps(run_config, sort_keys=True, default=str).encode()).hexdigest()
    dates = np.asarray(data["epoch_days"], dtype=float)
    incidence = np.zeros((len(data["pair_start"]), len(dates)), dtype=np.float64)
    for i, (start, end) in enumerate(zip(data["pair_start"], data["pair_end"])):
        incidence[i, int(start)] = -1
        incidence[i, int(end)] = 1
    network_rank = int(np.linalg.matrix_rank(incidence))
    network_components = int(len(dates) - network_rank)
    network_cycle_rank = int(len(data["pair_start"]) - network_rank)
    manifest = {
        "schema_version": "1.0", "aoi_id": cfg.aoi_id, "run_id": run_id, "run_dir": str(run_dir),
        "created_utc": datetime.now(timezone.utc).isoformat(), "crs": crs_wkt,
        "grid_transform": list(transform), "grid_shape": list(mask.shape),
        "date_range_days": [float(dates.min()), float(dates.max())],
        "epoch_dates": [str(x) for x in data.get("epoch_dates", dates)],
        "input_stack": str(stack_path),
        "heatmap_csv": str(csv_path.relative_to(run_dir)),
        "speed": {"source_search_download_and_stack_export_seconds": source_screening_seconds,
                  "sbas_solver_seconds": sbas_seconds, "elapsed_total_seconds": time.perf_counter() - run_started,
                  "source_pairs_fetched": source_metrics.get("clips_fetched_from_harmony")},
        "accuracy_benchmark": comparison,
        "quality_summary": quality_summary,
        "requested_date_range": {"start_inclusive": cfg.start_date, "end_exclusive": cfg.end_date},
        "measurement_interval": {"start": epoch_labels[0], "end": epoch_labels[-1],
                                 "elapsed_days": float(data["epoch_days"][-1] - data["epoch_days"][0]),
                                 "delta_definition": "last observed epoch minus first observed epoch; relative LOS cm"},
        "pair_network": {"pair_count": int(len(data["pair_start"])), "epoch_count": int(len(dates)),
                         "incidence_rank": network_rank, "connected_components": network_components,
                         "independent_cycle_count": network_cycle_rank,
                         "uncertainty_interpretable": network_cycle_rank > 0},
        "layers": layer_meta, "cube": str(cube_path.relative_to(run_dir)) if cube_path else None,
        "config_sha256": config_hash, "software": {"python": platform.python_version(), "numpy": np.__version__, "rasterio": rasterio.__version__},
        "processing": {"solver": "batched weighted SBAS grouped by valid-pair mask", "minimum_valid_pairs": cfg.minimum_valid_pairs,
                       "phase_sign": float(data["phase_sign"]) if "phase_sign" in data else None,
                       "phase_processing": phase_processing,
                       "ramp_removal": (True if phase_processing == "reference_only_ramp" else
                                        False if phase_processing == "reference_only_offset" else None),
                       "ramp_removal_requested": cfg.remove_ramp,
                       "reference": ("exterior annulus; stability is not independently verified"
                                     if phase_processing.startswith("reference_only_") else "unknown preprocessed input")},
        "known_limitations": ["GUNW search and spatial subset retrieval still depend on ASF/Harmony network latency.",
                              "Harmony did not expose the GUNW 3-D incidence-angle metadata cube as a raster; vertical fields are null and LOS fields are supplied.",
                              "The 9-pair/10-epoch network has zero independent cycles; formal uncertainty fields are null.",
                              "Acceleration is null for this four-month span; seasonal/long-term split requires at least twelve months.",
                              "Closure-based unwrapping quality flags and temporal coherence are not emitted by this stage.",
                              "Ancillary providers are unconfigured pending official endpoint and license verification."]
    }
    manifest_path = run_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def zonal_stats(manifest: dict[str, Any], polygon_geojson: dict[str, Any], layers: list[str]) -> dict[str, Any]:
    """Read only the raster window intersecting a polygon and return robust summary stats."""
    output: dict[str, Any] = {"layers": {}}
    run_dir = Path(manifest["run_dir"]) if "run_dir" in manifest else None
    if run_dir is None:
        raise ValueError("Pass manifest with _run_dir set to the run folder")
    polygon = shape(polygon_geojson)
    for layer in layers:
        info = next((x for x in manifest["layers"] if x["name"] == layer), None)
        if info is None:
            raise KeyError(f"Layer not in manifest: {layer}")
        with rasterio.open(run_dir / info["path"]) as ds:
            geom = polygon
            if ds.crs and ds.crs.to_string() != "EPSG:4326":
                from pyproj import Transformer
                from shapely.ops import transform as transform_geometry
                transformer = Transformer.from_crs("EPSG:4326", ds.crs, always_xy=True)
                geom = transform_geometry(transformer.transform, geom)
            arr, _ = raster_mask(ds, [mapping(geom)], crop=True, filled=False)
            vals = arr[0].compressed()
        output["layers"][layer] = ({"mean": float(np.mean(vals)), "median": float(np.median(vals)),
                                    "p95": float(np.percentile(vals, 95)), "valid_pixel_fraction": float(vals.size / max(arr.shape[1] * arr.shape[2], 1)),
                                    "units": info["units"]} if vals.size else {"mean": None, "median": None, "p95": None, "valid_pixel_fraction": 0.0, "units": info["units"]})
    return output
