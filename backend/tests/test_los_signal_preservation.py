"""Numerical regressions runnable without the GIS/web stack or pytest.

Run: python backend/tests/test_los_signal_preservation.py
Synthetic truth verifies implementation only, not Rafsanjan field accuracy.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest

import numpy as np

ROOT = Path(__file__).resolve().parents[2]


def load_file(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


source = load_file("los_source_regression", "nisar_selection_subsidence.py")
sbas = load_file("los_sbas_regression", "subsidence_engine/sbas.py")


class LosSignalPreservationTests(unittest.TestCase):
    def setUp(self):
        yy, xx = np.indices((120, 160))
        self.target = (xx > 16) & (xx < 154) & (yy > 8) & (yy < 115)
        self.reference = ~self.target
        self.x = xx / 159.0
        self.scale = source.WAVELENGTH_M * 100.0 / (4 * np.pi)
        self.atmosphere = 0.8 + 0.2 * self.x + 0.3 * yy / 119.0

    def process(self, truth_cm, **kwargs):
        ph = (truth_cm / self.scale + self.atmosphere)[None]
        coh = np.full_like(ph, 0.9)
        return source._detrend_stack(ph, coh, self.reference,
                                     np.zeros(self.target.shape, bool), 1.0, **kwargs)[0]

    def test_four_cm_is_preserved_after_reference_only_ramp(self):
        truth = np.where(self.target, 4.0, 0.0)
        actual = self.process(truth, reference_only=True)
        np.testing.assert_allclose(actual, truth, atol=1e-5)

    def test_broad_gradient_is_not_fitted_away(self):
        truth = np.where(self.target, 4.0 * self.x, 0.0)
        legacy = self.process(truth)
        corrected = self.process(truth, reference_only=True)
        np.testing.assert_allclose(corrected, truth, atol=1e-5)
        # The old global fit absorbs part of a real deformation gradient.
        self.assertGreater(np.max(np.abs(legacy[self.target] - truth[self.target])), 0.1)

    def test_reference_only_fit_does_not_fall_back_to_target(self):
        self.reference[:] = False
        self.reference[:8, :8] = True  # below the 100-pixel ramp support minimum
        actual = self.process(np.where(self.target, 4.0, 0.0), reference_only=True)
        self.assertTrue(np.isnan(actual).all())

    def test_offset_only_mode_preserves_spatial_gradient(self):
        self.atmosphere[:] = 1.5
        truth = np.where(self.target, -4.0 * self.x, 0.0)
        actual = self.process(truth, reference_only=True, remove_ramp=False)
        np.testing.assert_allclose(actual, truth, atol=1e-5)

    def test_low_coherence_reference_pixels_do_not_set_zero(self):
        ph = np.full((1, 120, 160), 1.0)
        coh = np.full_like(ph, 0.9)
        ref_indices = np.flatnonzero(self.reference)
        bad = ref_indices[:int(0.75 * ref_indices.size)]
        ph[0].flat[bad] = 100.0
        coh[0].flat[bad] = 0.1
        actual = source._detrend_stack(ph, coh, self.reference,
                     np.zeros(self.target.shape, bool), 1.0,
                     reference_only=True, remove_ramp=False)
        np.testing.assert_allclose(actual[0, self.target], 0, atol=1e-5)

    def test_small_farm_is_not_rejected_when_reference_support_is_strong(self):
        phase = np.ones((40, 40), dtype=np.float32)
        coherence = np.full_like(phase, 0.9)
        connected = np.ones_like(phase, dtype=np.int32)
        original_zone_masks = source._zone_masks

        def small_target_with_large_reference(shape, transform, crs, center):
            target = np.zeros(shape, dtype=bool)
            target[:2, :2] = True
            reference = ~target
            return target, reference

        source._zone_masks = small_target_with_large_reference
        try:
            prepared = source._prepare_pair(
                {"phase": phase, "coh": coherence, "cc": connected,
                 "incidence": None, "tf": (1, 0, 0, 0, -1, 40), "crs": "EPSG:4326"},
                {"center": (0, 0)},
            )
        finally:
            source._zone_masks = original_zone_masks
        self.assertNotIn("skip", prepared)

    def test_empty_cached_incidence_layer_is_treated_as_unavailable(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp)
            path = cache / "cached.npz"
            np.savez_compressed(
                path,
                phase=np.ones((4, 4), dtype=np.float32),
                coh=np.ones((4, 4), dtype=np.float32),
                cc=np.zeros(0, dtype=np.int32),
                incidence=np.zeros(0, dtype=np.float32),
                tf=np.array((1, 0, 0, 0, -1, 4), dtype=np.float64),
                crs=np.array("EPSG:4326"),
            )
            fetcher = source.Fetcher(cache, source.RunOptions())
            loaded = fetcher._load_cache(path)
        self.assertIsNotNone(loaded)
        self.assertIsNone(loaded["incidence"])

    def test_sbas_recovers_signed_four_cm_over_actual_interval(self):
        days = np.array([0, 12, 36, 48, 72, 84, 96, 108, 132, 144.0])
        starts = np.arange(9)
        ends = starts + 1
        truth = days[:, None, None] / days[-1] * np.array([[4.0, -4.0]])
        pairs = truth[ends] - truth[starts]
        result = sbas.invert_sbas(pairs, starts, ends, days, np.ones_like(pairs))
        np.testing.assert_allclose(result.displacement_cm, truth, atol=2e-6)
        np.testing.assert_allclose(result.velocity_cm_year, np.array([[4.0, -4.0]]) * 365.25 / 144, atol=2e-6)
        self.assertTrue(result.connected.all())
        self.assertTrue(np.isnan(result.velocity_sigma_cm_year).all())

    def test_phase_to_sbas_preserves_four_cm_end_to_end(self):
        truth = np.where(self.target, -4.0 * self.x, 0.0)
        days = np.array([0, 12, 36, 60.0])
        starts, ends = np.array([0, 1, 2]), np.array([1, 2, 3])
        motion = days[:, None, None] / days[-1] * truth
        pairs = motion[ends] - motion[starts]
        phase = pairs / self.scale + self.atmosphere[None]
        coherence = np.full_like(phase, 0.9)
        screened = source._detrend_stack(phase, coherence, self.reference,
                         np.zeros(self.target.shape, bool), 1.0, reference_only=True)
        result = sbas.invert_sbas(screened, starts, ends, days, np.ones_like(pairs))
        np.testing.assert_allclose(result.displacement_cm[-1], truth, atol=2e-6)

    def test_disconnected_pixel_is_unknown_not_zero(self):
        pairs = np.ones((3, 1, 2))
        pairs[1, 0, 1] = np.nan
        result = sbas.invert_sbas(pairs, np.array([0, 1, 2]), np.array([1, 2, 3]),
                                 np.array([0, 12, 24, 36]), np.ones_like(pairs))
        self.assertTrue(result.connected[0, 0])
        self.assertFalse(result.connected[0, 1])
        self.assertTrue(np.isnan(result.displacement_cm[:, 0, 1]).all())

    def test_invalid_epoch_times_are_rejected(self):
        for days in ([0, 12, 12, 36], [0, 24, 12, 36], [0, 12, np.nan, 36]):
            with self.assertRaisesRegex(ValueError, "strictly increasing"):
                sbas.invert_sbas(np.ones((3, 1, 1)), np.array([0, 1, 2]),
                                 np.array([1, 2, 3]), np.array(days), np.ones((3, 1, 1)))


def benchmark():
    """Compare identical synthetic stacks; excludes network, GIS export and UI."""
    import json
    import statistics
    import time

    fixture = LosSignalPreservationTests()
    fixture.setUp()
    truth = np.where(fixture.target, 4 * fixture.x, 0)
    phase = np.repeat((truth / fixture.scale + fixture.atmosphere)[None], 9, axis=0)
    coherence = np.full_like(phase, 0.9)
    args = (phase, coherence, fixture.reference, np.zeros(fixture.target.shape, bool), 1.0)
    records = []
    for reference_only in (False, True):
        source._detrend_stack(*args, reference_only=reference_only)
        elapsed = []
        for _ in range(5):
            start = time.perf_counter()
            actual = source._detrend_stack(*args, reference_only=reference_only)
            elapsed.append(time.perf_counter() - start)
        records.append({"mode": "reference_only" if reference_only else "legacy_global",
                        "median_seconds": statistics.median(elapsed),
                        "max_target_error_cm": float(np.max(np.abs(actual[0, fixture.target] - truth[fixture.target]))),
                        "shape": list(phase.shape)})
    print(json.dumps({"synthetic_only": True, "results": records}, indent=2))


if __name__ == "__main__":
    if "--benchmark" in sys.argv:
        benchmark()
    else:
        unittest.main(verbosity=2)
