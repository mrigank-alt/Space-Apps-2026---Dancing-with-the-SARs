from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import time
from unittest.mock import patch

import numpy as np
from affine import Affine

import nisar_selection_subsidence as source
from acquisition_cache import crop_native, enclosing_extent


def clip():
    phase = np.arange(10000, dtype=np.float32).reshape(100, 100)
    return dict(phase=phase, coh=np.ones_like(phase), cc=np.ones_like(phase, dtype=np.int32),
                incidence=None, tf=(0.01, 0, 0, 0, -0.01, 1), crs="EPSG:4326")


def test_crop_preserves_native_values_transform_and_missing_layers():
    original = clip()
    cropped = crop_native(original, (.2, .3, .6, .8))
    np.testing.assert_array_equal(cropped["phase"], original["phase"][20:70, 20:60])
    assert cropped["tf"] == tuple(Affine(.01, 0, .2, 0, -.01, .8))[:6]
    assert cropped["incidence"] is None
    assert crop_native(original, (-.1, .3, .6, .8)) is None
    fractional = crop_native(original, (.203, .303, .607, .807))
    np.testing.assert_array_equal(fractional["phase"], original["phase"][20:69, 21:60])
    assert enclosing_extent((-.21, .31, .69, .89), .1) == (-.3, .3, .7, .9)
    snapped = (.3, -.7, .6, -.2)
    assert enclosing_extent(snapped, .1) == snapped


def test_containing_cache_reused_without_remote_call(tmp_path):
    fetcher = source.Fetcher(tmp_path, source.RunOptions(offline=True))
    item = {"name": "test-product", "pol": "HH"}
    large = (0, 0, 1, 1)
    path = fetcher._path(item, large)
    fetcher._save_cache(path, clip())
    fetcher._extent_index.register(fetcher._identity(item), path, large)
    with patch.object(fetcher, "_harmony", side_effect=AssertionError("remote access")):
        actual, origin = fetcher.load(item, (.2, .3, .6, .8))
    assert origin == "spatial-cache"
    np.testing.assert_array_equal(actual["phase"], clip()["phase"][20:70, 20:60])
    other, origin = fetcher.load({**item, "pol": "VV"}, (.2, .3, .6, .8))
    assert other is None and origin == "offline"


def test_observed_harmony_projected_window_and_geographic_mask():
    # Geometry/transform captured from the independently downloaded pilot, not
    # calculated by crop_native. Prevents a one-pixel multilook-origin regression.
    values = np.ones((900, 900), dtype=np.float32)
    raw = dict(phase=values, coh=values.copy(), cc=np.ones_like(values, dtype=np.int32),
               incidence=None, tf=(80, 0, 648720, 0, -80, 4242000), crs="EPSG:32610")
    result = crop_native(raw, (-121.21697186784252, 37.78206176084002,
                               -120.60588561124597, 38.26791183228357))
    assert result["phase"].shape == (688, 685)
    assert result["tf"] == (80, 0, 656000, 0, -80, 4238240)
    assert np.isnan(result["phase"][0, 0])
    assert result["cc"][0, 0] == 0
    assert result["phase"][344, 342] == 1


def test_prefetch_cannot_treat_prepared_only_cache_as_raw_coverage(tmp_path):
    fetcher = source.Fetcher(tmp_path, source.RunOptions(prefetch_only=True))
    item = {"name": "test", "pol": "HH"}
    spec = {"bbox": (0, 0, 1, 1), "center": (.5, .5)}
    fetcher.save_prepared(item, spec, {"skip": "too few coherent pixels"})
    assert not fetcher.is_cached(item, spec)


def test_corrupt_exact_cache_does_not_suppress_authentication(tmp_path):
    fetcher = source.Fetcher(tmp_path, source.RunOptions())
    item = {"name": "test", "pol": "HH"}
    spec = {"bbox": (0, 0, 1, 1), "center": (.5, .5)}
    fetcher._path(item, spec["bbox"]).write_bytes(b"broken")
    assert not fetcher.is_cached(item, spec)


def test_two_fetchers_share_one_inflight_request(tmp_path):
    a = source.Fetcher(tmp_path, source.RunOptions())
    b = source.Fetcher(tmp_path, source.RunOptions())
    item = {"name": "test", "pol": "HH"}
    calls = []
    def remote(*args):
        calls.append(1)
        time.sleep(.15)
        return clip()
    with patch.object(a, "_harmony", side_effect=remote), patch.object(b, "_harmony", side_effect=remote):
        with ThreadPoolExecutor(2) as pool:
            results = list(pool.map(lambda f: f.load(item, (0, 0, 1, 1)), (a, b)))
    assert len(calls) == 1
    assert sorted(r[1] for r in results) == ["cache", "harmony"]


def test_completed_layer_survives_transfer_failure_and_new_fetcher(tmp_path):
    import rasterio
    from concurrent.futures import Future
    item = {"name": "test", "pol": "HH"}
    downloads = []
    fail = True
    class Client:
        def submit(self, request):
            return "persisted-job"
        def result_urls(self, job, **kwargs):
            assert job == "persisted-job"
            return ["https://example.test/unwrappedPhase.tif?secret=never-log",
                    "https://example.test/coherenceMagnitude.tif"]
        def download(self, url, directory, **kwargs):
            nonlocal fail
            f = Future()
            name = url.split("/")[-1].split("?")[0]
            downloads.append(name)
            if "coherence" in name and fail:
                f.set_exception(ValueError("simulated transfer failure"))
            else:
                path = Path(directory) / name
                with rasterio.open(path, "w", driver="GTiff", width=100, height=100,
                                   count=1, dtype="float32", crs="EPSG:4326",
                                   transform=Affine(*clip()["tf"])) as ds:
                    ds.write(np.ones((100, 100), dtype=np.float32), 1)
                f.set_result(str(path))
            return f
    opts = source.RunOptions(use_cc=False, trace_path=tmp_path / "events.jsonl")
    first = source.Fetcher(tmp_path, opts)
    first._collection = "C123-TEST"
    with patch.object(first, "_client", return_value=Client()):
        import pytest
        with pytest.raises(ValueError):
            first.load(item, (0, 0, 1, 1))
    fail = False
    second = source.Fetcher(tmp_path, opts)
    second._collection = "C123-TEST"
    client = Client()
    with patch.object(second, "_client", return_value=client), patch.object(client, "submit", side_effect=AssertionError("resubmitted")):
        actual, origin = second.load(item, (0, 0, 1, 1))
    assert actual["phase"].shape == (100, 100)
    assert downloads.count("unwrappedPhase.tif") == 1
    assert downloads.count("coherenceMagnitude.tif") == 2
    assert "never-log" not in opts.trace_path.read_text()
    assert not list((tmp_path / "downloads").iterdir())
