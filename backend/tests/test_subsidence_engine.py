from __future__ import annotations

import numpy as np
import pytest

from subsidence_engine.sbas import invert_sbas


def test_batched_sbas_recovers_known_linear_motion_and_bowl():
    times = np.array([0, 12, 24, 36], dtype=float)
    starts = np.array([0, 1, 2, 0, 1])
    ends = np.array([1, 2, 3, 2, 3])
    truth_rate = np.array([[0.0, 0.4], [0.8, 1.2]], dtype=np.float32)
    motion = truth_rate[None] * (times[:, None, None] / 365.25)
    pairs = np.stack([motion[e] - motion[s] for s, e in zip(starts, ends)])
    # A smooth synthetic bowl plus a spatially uniform nuisance offset in each pair.
    yy, xx = np.indices((2, 2))
    bowl = np.exp(-((xx - 0.5) ** 2 + (yy - 0.5) ** 2))
    pairs += np.arange(len(starts), dtype=np.float32)[:, None, None] * 0.001 * bowl
    result = invert_sbas(pairs, starts, ends, times, np.ones_like(pairs), minimum_pairs=3)
    np.testing.assert_allclose(result.velocity_cm_year, truth_rate, atol=0.08)
    assert np.all(result.connected)
    assert np.all(result.valid_pair_count == len(starts))


def test_missing_pairs_are_grouped_and_broken_network_is_invalid():
    times = np.array([0, 12, 24, 36], dtype=float)
    starts = np.array([0, 1, 2, 0])
    ends = np.array([1, 2, 3, 2])
    shape = (2, 3)
    rate = np.full(shape, 0.5, dtype=np.float32)
    motion = rate[None] * (times[:, None, None] / 365.25)
    pairs = np.stack([motion[e] - motion[s] for s, e in zip(starts, ends)])
    weights = np.ones_like(pairs)
    pairs[1, 0, 0] = np.nan
    weights[:, 1, 2] = 0  # that pixel has no connected observations
    result = invert_sbas(pairs, starts, ends, times, weights, minimum_pairs=3)
    assert result.connected[0, 0]
    assert not result.connected[1, 2]
    assert np.isnan(result.velocity_cm_year[1, 2])


def test_tree_network_keeps_point_estimate_but_marks_uncertainty_unknown():
    times = np.array([0, 12, 24, 36], dtype=float)
    starts, ends = np.array([0, 1, 2]), np.array([1, 2, 3])
    motion = (0.7 * times / 365.25)[:, None, None] * np.ones((4, 1, 1))
    pairs = np.stack([motion[e] - motion[s] for s, e in zip(starts, ends)])
    result = invert_sbas(pairs, starts, ends, times, np.ones_like(pairs), minimum_pairs=3)
    assert result.velocity_cm_year[0, 0] == pytest.approx(0.7, abs=1e-5)
    assert np.isnan(result.velocity_sigma_cm_year[0, 0])


def test_pipeline_config_requires_aoi():
    from subsidence_engine.config import PipelineConfig

    with pytest.raises(ValueError, match="geometry or selection_id"):
        PipelineConfig(aoi_id="test")


def test_pipeline_writes_cogs_zarr_manifest_and_zonal_stats(tmp_path):
    import json
    from affine import Affine
    from pyproj import Transformer
    from shapely.geometry import Polygon, mapping

    from subsidence_engine.pipeline import run_pipeline, zonal_stats

    height = width = 8
    transform = Affine(1000, 0, 500000, 0, -1000, 3400000)
    to_geo = Transformer.from_crs("EPSG:32640", "EPSG:4326", always_xy=True)
    polygon = Polygon([to_geo.transform(x, y) for x, y in [
        (500000, 3400000), (508000, 3400000), (508000, 3392000),
        (500000, 3392000), (500000, 3400000),
    ]])
    geometry = mapping(polygon)
    times = np.array([0, 120, 240, 360], dtype=float)
    starts, ends = np.array([0, 1, 2, 0, 1]), np.array([1, 2, 3, 2, 3])
    trend = np.full((height, width), 0.5, np.float32)
    motion = trend[None] * (times[:, None, None] / 365.25)
    pairs = np.stack([motion[e] - motion[s] for s, e in zip(starts, ends)])
    stack = tmp_path / "stack.npz"
    np.savez_compressed(stack, pair_displacement_cm=pairs, pair_start=starts, pair_end=ends,
                        epoch_days=times, weights=np.ones_like(pairs), transform=np.array(transform),
                        crs_wkt=np.array("EPSG:32640"))
    config = {
        "aoi_id": "synthetic", "geometry": geometry, "pair_stack_npz": stack,
        "output_root": tmp_path / "outputs", "minimum_valid_pairs": 3,
    }
    manifest = run_pipeline(config)
    assert len(manifest["layers"]) == 7
    assert (tmp_path / manifest["run_dir"] / "cube" / "timeseries.zarr").exists()
    loaded_manifest = json.loads((tmp_path / manifest["run_dir"] / "manifest.json").read_text())
    stats = zonal_stats(loaded_manifest, geometry, ["mean_velocity_los"])
    assert stats["layers"]["mean_velocity_los"]["mean"] == pytest.approx(0.5, abs=1e-4)


def test_unconfigured_ancillary_provider_is_explicit_todo(tmp_path):
    from subsidence_engine.providers import ANCILLARY_PROVIDERS

    with pytest.raises(NotImplementedError, match="verify official access"):
        ANCILLARY_PROVIDERS["dem"].fetch((0, 0, 1, 1), "EPSG:4326", (1, 0, 0, 0, -1, 1), (1, 1), tmp_path)
