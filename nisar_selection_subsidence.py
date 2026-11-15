"""Small-area NISAR GUNW LOS deformation screening for four Kerman cities (v3).

ASF search selects only NISAR GUNW granules intersecting the configured city
boxes. NASA Harmony extracts only clipped unwrapped-phase, coherence (and, when
available, connected-component) COGs; the original HDF5 granules are never
downloaded. Temporary COGs are deleted immediately after reading. The small
clipped arrays are cached in <output>/clip_cache so re-runs and parameter tuning
do not hit Harmony again.

Install (Python 3.10+):
    python -m pip install --upgrade asf_search harmony-py numpy matplotlib rasterio pyproj requests

Typical use:
    python nisar_kerman_subsidence.py --inventory-only      # catalog only, no login
    python nisar_kerman_subsidence.py                       # full run (Earthdata login if needed)
    python nisar_kerman_subsidence.py --offline             # re-process cached clips only, no login
    python nisar_kerman_subsidence.py --no-plots            # fastest: tables/maps only, no PNGs
    python nisar_kerman_subsidence.py --cities Rafsanjan --workers 2

Speed: the first run is bounded by Harmony's server-side job latency (all requests are sent
concurrently). Every later run reads the local cache and takes seconds.

Credentials: set EARTHDATA_USER / EARTHDATA_PASS (or EDL_USERNAME / EDL_PASSWORD)
to avoid prompts. Login is only requested if at least one clip is not cached.

Results are differential line-of-sight (LOS) displacement relative to a local
reference annulus. They are NOT absolute and NOT vertical-only subsidence.
The phase sign convention is retained (override with --phase-sign -1 only after
validating it against the product documentation or a known stable/deforming site).
"""

from __future__ import annotations

import argparse
import csv
import getpass
import hashlib
import json
import math
import os
import re
import random
import tempfile
import threading
import time
import traceback
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date, datetime, timezone
from functools import lru_cache
from pathlib import Path

import numpy as np

# ================================ User settings =============================
AOIS = {
    "Rafsanjan": {"center": (55.98714, 30.40055), "bbox": (55.65, 30.10, 56.35, 30.70)},
    "Anar":      {"center": (55.27028, 30.86556), "bbox": (55.00, 30.60, 55.55, 31.15)},
    "Zarand":    {"center": (56.56900, 30.81400), "bbox": (56.30, 30.55, 56.85, 31.05)},
    "Sirjan":    {"center": (55.68100, 29.45200), "bbox": (55.30, 29.20, 56.05, 29.75)},
}
START = date(2025, 12, 1)
END_EXCLUSIVE = date(2026, 11, 1)
COLLECTION = "NISAR_L2_GUNW_PROVISIONAL_V1"
OUT_DIR = Path(__file__).resolve().parent / "subsidence_results_new"

# Spatial/statistical screening; tune only with documented local validation.
TARGET_RADIUS_KM = 10.0
REFERENCE_INNER_KM, REFERENCE_OUTER_KM = 15.0, 25.0
COHERENCE_MIN = 0.40
MULTILOOK = 4                    # 80 m samples -> about 320 m products
MIN_VALID_FRACTION = 0.20        # min fraction of multilooked pixels that must be valid per pair
MIN_PIXELS_PER_ZONE = 25
MIN_PAIRS_PER_PIXEL = 3
MIN_HOTSPOT_PIXELS = 15          # ~1.5 km^2 at 320 m posting
MIN_SIGNAL_CM_YR = 3.0
NOISE_SIGMA_MULTIPLIER = 3.0
SMOOTH_WINDOW = 5
MAX_RESULTS_PER_AOI = 200
WAVELENGTH_M = 299_792_458.0 / 1_257_500_000.0
PHASE_SIGN = 1.0                 # preserve product phase convention; do not guess a subsidence sign

# Robust processing controls
RAMP_ORDER = 1                   # 1 = plane, 2 = quadratic ramp (more flexible, absorbs more signal)
DETREND_ITERATIONS = 3           # ramp refits with detected bowls masked out (stops early on convergence)
HOTSPOT_DILATE_PX = 9            # exclusion margin around detected bowls during ramp refit
COH_WEIGHT_CAP = 5.0             # atmosphere dominates above ~0.9 coherence; cap the weight
TUKEY_C = 4.685                  # temporal outlier rejection (catches unwrapping jumps)
PAIR_REJECT_FACTOR = 3.0         # drop a pair whose residual scatter > this x median pair scatter
STRONG_AREA_FACTOR = 3.0         # "strong candidate": area >= this x MIN_HOTSPOT_PIXELS ...
STRONG_SIGNAL_FACTOR = 1.25      # ... and |mean anomaly| >= this x detection threshold (screening aid only)
MAX_WORKERS = 40                 # cold run: all Harmony jobs in flight at once (server-side latency dominates)
CACHE_VERSION = "v3"             # prepared-array cache; incidence angle remains optional when not available
RAW_CACHE_VERSION = "v2"         # preserve reusable phase/coherence clips; Harmony does not expose the 3-D angle cube as a coverage
SELECTION_GEOMETRY = None

STAMP_RE = re.compile(r"20\d{6}T\d{6}")
CMR_URL = "https://cmr.earthdata.nasa.gov/search/collections.json"
LAYER_TOKENS = (("phase", "unwrappedphase"), ("coh", "coherencemagnitude"),
                ("cc", "connectedcomponents"), ("incidence", "incidenceangle"))


@dataclass
class RunOptions:
    workers: int = 0                 # 0 = auto
    plots: bool = True
    phase_sign: float = PHASE_SIGN
    use_cache: bool = True
    offline: bool = False
    use_cc: bool = True
    engine_export_only: bool = False


# ============================== Catalog (ASF) ===============================
def bbox_wkt(box):
    west, south, east, north = box
    return f"POLYGON(({west} {south},{east} {south},{east} {north},{west} {north},{west} {south}))"


def parse_product(product):
    props = product.properties
    name = props.get("fileName") or props.get("sceneName") or product.umm.get("GranuleUR", "")
    name = Path(str(name)).name.removesuffix(".h5")
    fields = name.split("_")
    stamps = STAMP_RE.findall(name)
    if len(fields) < 11 or fields[3] != "GUNW" or len(stamps) < 4:
        return None
    try:
        return {
            "name": name,
            "track": fields[5], "direction": fields[6], "frame": fields[7],
            "pol": "HH" if fields[10] == "SH" else "VV" if fields[10] == "SV" else None,
            "start": datetime.strptime(stamps[0], "%Y%m%dT%H%M%S").replace(tzinfo=timezone.utc),
            "end": datetime.strptime(stamps[2], "%Y%m%dT%H%M%S").replace(tzinfo=timezone.utc),
            "product": product,
        }
    except (ValueError, IndexError):
        return None


def search_city(asf, city, spec):
    if SELECTION_GEOMETRY is not None:
        from shapely.geometry import shape as make_shape
        intersects = make_shape(SELECTION_GEOMETRY).wkt
    else:
        intersects = bbox_wkt(spec["bbox"])
    results = asf.search(
        dataset="NISAR", shortName=COLLECTION, processingLevel="GUNW",
        dataMaturity="PROVISIONAL", intersectsWith=intersects,
        start=f"{START.isoformat()}T00:00:00Z",
        end=f"{END_EXCLUSIVE.isoformat()}T00:00:00Z",
        maxResults=MAX_RESULTS_PER_AOI,
    )
    if len(results) >= MAX_RESULTS_PER_AOI:
        raise RuntimeError(f"ASF hit the {MAX_RESULTS_PER_AOI}-granule cap for {city}; refusing a truncated run.")
    found = {}
    for product in results:
        item = parse_product(product)
        if not item or not item["pol"]:
            continue
        if item["start"].date() < START or item["end"].date() >= END_EXCLUSIVE:
            continue
        key = (item["track"], item["direction"], item["frame"], item["pol"], item["start"], item["end"])
        found.setdefault(key, item)
    return sorted(found.values(), key=lambda p: (p["start"], p["track"], p["frame"]))


def choose_track(city, products):
    groups = defaultdict(list)
    for product in products:
        groups[(product["track"], product["direction"], product["frame"], product["pol"])].append(product)
    if not groups:
        return []
    # Prefer a coherent single geometry with the greatest date-pair coverage.
    chosen = max(groups.values(), key=lambda g: (len(g), g[0]["start"]))
    print(f"[{city}] selected {len(chosen)} pairs on {chosen[0]['track']}{chosen[0]['direction']} "
          f"frame {chosen[0]['frame']} {chosen[0]['pol']}; "
          f"{chosen[0]['start'].date()} to {max(c['end'] for c in chosen).date()}")
    return chosen


def get_collection_id(requests):
    response = requests.get(CMR_URL, params={"short_name": COLLECTION, "provider": "ASF", "page_size": 5}, timeout=45)
    response.raise_for_status()
    entries = response.json().get("feed", {}).get("entry", [])
    if not entries:
        raise RuntimeError(f"CMR collection not found: {COLLECTION}")
    return entries[0]["id"]


# ====================== Geospatial helpers (isolated) =======================
@lru_cache(maxsize=16)
def _transformer(src, dst):
    from pyproj import Transformer
    return Transformer.from_crs(src, dst, always_xy=True)


def _lonlat_to_xy(crs_wkt, lon, lat):
    return _transformer("EPSG:4326", crs_wkt).transform(lon, lat)


def _xy_to_lonlat(crs_wkt, x, y):
    return _transformer(crs_wkt, "EPSG:4326").transform(x, y)


def _scale_tf(tf, k):
    a, b, c, d, e, f = tf
    return (a * k, b * k, c, d * k, e * k, f)


def _xy_to_colrow(tf, x, y):
    """Invert a 6-coefficient affine (no external dependency). Returns fractional (col, row)."""
    a, b, c, d, e, f = tf
    det = a * e - b * d
    return ((e * (x - c) - b * (y - f)) / det, (-d * (x - c) + a * (y - f)) / det)


def _zone_masks(shape, tf, crs_wkt, center):
    """Boolean target disk and reference annulus for a grid (pixel centres)."""
    if SELECTION_GEOMETRY is not None:
        from rasterio.features import geometry_mask
        from rasterio.transform import Affine
        from pyproj import CRS, Transformer
        from shapely.geometry import shape as make_shape, mapping
        from shapely.ops import transform as transform_geometry
        geom = make_shape(SELECTION_GEOMETRY)
        project = Transformer.from_crs("EPSG:4326", CRS.from_wkt(crs_wkt), always_xy=True)
        geom = transform_geometry(project.transform, geom)
        affine = Affine(*tf)
        target = geometry_mask([mapping(geom)], out_shape=shape, transform=affine, invert=True)
        outer = geometry_mask([mapping(geom.buffer(20_000))], out_shape=shape, transform=affine, invert=True)
        inner = geometry_mask([mapping(geom.buffer(5_000))], out_shape=shape, transform=affine, invert=True)
        return target, outer & ~inner
    a, b, c, d, e, f = tf
    h, w = shape
    yy, xx = np.indices((h, w), dtype=np.float64)
    xx += 0.5
    yy += 0.5
    x = c + xx * a + yy * b
    y = f + xx * d + yy * e
    cx, cy = _lonlat_to_xy(crs_wkt, *center)
    radius = np.hypot(x - cx, y - cy)
    target = radius <= TARGET_RADIUS_KM * 1000
    reference = (radius >= REFERENCE_INNER_KM * 1000) & (radius <= REFERENCE_OUTER_KM * 1000)
    return target, reference


# ============================ Numerical helpers =============================
def _mad(x):
    x = np.asarray(x)
    x = x[np.isfinite(x)]
    if x.size == 0:
        return np.nan
    med = np.median(x)
    return float(1.4826 * np.median(np.abs(x - med)))


def _nanstat(fn, x):
    x = np.asarray(x, dtype=np.float64)
    x = x[np.isfinite(x)]
    return float(fn(x)) if x.size else np.nan


def _robust_lim(a, default, q=98):
    a = np.asarray(a)
    a = a[np.isfinite(a)]
    return float(max(default, np.percentile(np.abs(a), q))) if a.size else float(default)


def _coh_weight(c):
    c = np.clip(c, 0.05, 0.97)
    return np.minimum(c ** 2 / np.maximum(1.0 - c ** 2, 1e-4), COH_WEIGHT_CAP)


def _block_mean(a, k, weights=None):
    h, w = (a.shape[0] // k) * k, (a.shape[1] // k) * k
    if h == 0 or w == 0:
        raise ValueError("Clipped raster is smaller than the multilook window.")
    blocks = a[:h, :w].reshape(h // k, k, w // k, k)
    if weights is None:
        valid = np.isfinite(blocks)
        sums = np.where(valid, blocks, 0).sum((1, 3))
        counts = valid.sum((1, 3))
        return np.divide(sums, counts, out=np.full(sums.shape, np.nan), where=counts >= (k * k * 0.5))
    wb = weights[:h, :w].reshape(h // k, k, w // k, k)
    valid = np.isfinite(blocks) & (wb > 0)
    sw = np.where(valid, wb, 0).sum((1, 3))
    cnt = valid.sum((1, 3))
    total = (np.where(valid, blocks, 0) * np.where(valid, wb, 0)).sum((1, 3))
    return np.divide(total, sw, out=np.full(sw.shape, np.nan), where=(sw > 0) & (cnt >= k * k * 0.5))


def _smooth(a, window=5):
    """NaN-aware box filter using vectorized integral images."""
    k = window | 1
    pad = k // 2
    ok = np.isfinite(a)
    vals = np.pad(np.where(ok, a, 0.0), pad)
    cnts = np.pad(ok.astype(np.float64), pad)

    def sums(z):
        c = np.pad(z.cumsum(0).cumsum(1), ((1, 0), (1, 0)))
        return c[k:, k:] - c[:-k, k:] - c[k:, :-k] + c[:-k, :-k]

    ss, nn = sums(vals), sums(cnts)
    return np.divide(ss, nn, out=np.full(a.shape, np.nan), where=nn >= 0.4 * k * k)


def _dilate(mask, window):
    """Box-filter dilation (no scipy needed)."""
    return np.nan_to_num(_smooth(mask.astype(np.float64), window), nan=0.0) > 0


def _label(mask):
    """4-connected component labelling. Returns (labels, count)."""
    h, w = mask.shape
    labels = np.zeros((h, w), np.int32)
    n = 0
    for r, c in np.argwhere(mask):
        if labels[r, c]:
            continue
        n += 1
        labels[r, c] = n
        stack = [(r, c)]
        while stack:
            y, x = stack.pop()
            for yy, xx in ((y - 1, x), (y + 1, x), (y, x - 1), (y, x + 1)):
                if 0 <= yy < h and 0 <= xx < w and mask[yy, xx] and not labels[yy, xx]:
                    labels[yy, xx] = n
                    stack.append((yy, xx))
    return labels, n


def _design(h, w, order):
    y, x = np.indices((h, w), dtype=np.float64)
    x = (x / max(w - 1, 1) - 0.5) * 2
    y = (0.5 - y / max(h - 1, 1)) * 2
    cols = [np.ones_like(x), x, y]
    if order >= 2:
        cols += [x * x, x * y, y * y]
    return np.stack(cols, axis=-1)


def _robust_surface(z, fit_mask, order=None, iterations=5):
    """Huber-weighted polynomial ramp fitted only where fit_mask is True. Returns full-grid surface or None."""
    order = RAMP_ORDER if order is None else order
    D = _design(*z.shape, order)
    valid = fit_mask & np.isfinite(z)
    if valid.sum() < max(100, 10 * D.shape[-1]):
        return None
    A = D[valid]
    b = z[valid].astype(np.float64)
    weights = np.ones(b.size)
    coef = np.zeros(D.shape[-1])
    for _ in range(iterations):
        root = np.sqrt(weights)
        coef, *_ = np.linalg.lstsq(A * root[:, None], b * root, rcond=None)
        resid = b - A @ coef
        scale = max(_mad(resid), 1e-6)
        u = np.abs(resid) / (1.345 * scale)
        weights = np.where(u <= 1, 1.0, 1.0 / np.maximum(u, 1e-12))
    return D @ coef


# ===================== Acquisition: Harmony + local cache ====================
def _read_layers(files, want_cc):
    """Identify phase / coherence / connected-component GeoTIFFs from a Harmony response."""
    import rasterio
    found = {}
    for path in files:
        if path.suffix.lower() not in (".tif", ".tiff"):
            continue
        with rasterio.open(path) as ds:
            name = path.name.lower()
            kind = next((k for k, tok in LAYER_TOKENS if tok in name), None)
            if kind is None:  # opaque filenames: fall back to band descriptions / tags
                label = (" ".join(map(str, ds.descriptions)) + " " + str(ds.tags())).lower()
                kind = next((k for k, tok in LAYER_TOKENS if tok in label), None)
            if kind is None or kind in found:
                continue
            masked = ds.read(1, masked=True)
            data = masked.filled(0).astype(np.int32) if kind == "cc" else masked.filled(np.nan).astype(np.float32)
            found[kind] = (data, tuple(ds.transform)[:6], ds.crs.to_wkt())
    if "phase" not in found or "coh" not in found:
        raise RuntimeError(f"Could not identify phase/coherence GeoTIFFs in Harmony response ({[p.name for p in files]}).")
    phase, tf, crs = found["phase"]
    coh, tf2, crs2 = found["coh"]
    if phase.shape != coh.shape or tf != tf2 or crs != crs2:
        raise RuntimeError("Harmony phase/coherence raster grids do not match.")
    cc = None
    if "cc" in found:
        cc_arr, tf3, crs3 = found["cc"]
        if cc_arr.shape == phase.shape and tf3 == tf and crs3 == crs:
            cc = cc_arr
        else:
            print("  note: connectedComponents grid differs from phase grid; ignoring it for this pair")
    elif want_cc:
        print("  note: connectedComponents layer not returned; continuing without it for this pair")
    incidence = None
    if "incidence" in found:
        incidence, itf, icrs = found["incidence"]
        if incidence.shape != phase.shape or itf != tf or icrs != crs:
            print("  note: incidenceAngle grid differs from phase grid; vertical conversion unavailable")
            incidence = None
    return {"phase": phase, "coh": coh, "cc": cc, "incidence": incidence, "tf": tf, "crs": crs}


def _retry(fn, attempts=3, delay=4.0):
    """Retry transient Harmony/network failures with jittered exponential backoff."""
    for k in range(attempts):
        try:
            return fn()
        except Exception:
            if k == attempts - 1:
                raise
            time.sleep(delay * (2 ** k) * (0.5 + random.random()))


class Fetcher:
    """Cache-first, thread-safe access to clipped GUNW layers."""

    def __init__(self, cache_dir: Path, opts: RunOptions):
        self.cache_dir, self.opts = cache_dir, opts
        self._lock = threading.Lock()
        self._local = threading.local()
        self._creds = None
        self._token = None
        self._collection = None
        self._cc_disabled = not opts.use_cc
        if opts.use_cache:
            cache_dir.mkdir(parents=True, exist_ok=True)

    # -- cache --
    def _path(self, item, bbox):
        key = f"{RAW_CACHE_VERSION}|{item['name']}|{item['pol']}|{tuple(round(v, 6) for v in bbox)}"
        return self.cache_dir / f"{hashlib.sha1(key.encode()).hexdigest()[:20]}.npz"

    def _prep_path(self, item, spec):
        geometry_key = hashlib.sha1(json.dumps(SELECTION_GEOMETRY, sort_keys=True).encode()).hexdigest() if SELECTION_GEOMETRY else "city"
        params = (CACHE_VERSION, geometry_key, item["name"], item["pol"], tuple(round(v, 6) for v in spec["bbox"]),
                  tuple(spec["center"]), COHERENCE_MIN, MULTILOOK, COH_WEIGHT_CAP, TARGET_RADIUS_KM,
                  REFERENCE_INNER_KM, REFERENCE_OUTER_KM, MIN_VALID_FRACTION, MIN_PIXELS_PER_ZONE, self.opts.use_cc)
        return self.cache_dir / f"prep_{hashlib.sha1(repr(params).encode()).hexdigest()[:20]}.npz"

    def is_cached(self, item, spec):
        return self.opts.use_cache and (self._prep_path(item, spec).exists() or self._path(item, spec["bbox"]).exists())

    def load_prepared(self, item, spec):
        """Tiny multilooked arrays from a previous run with identical processing parameters (or None)."""
        path = self._prep_path(item, spec)
        if not (self.opts.use_cache and path.exists()):
            return None
        try:
            with np.load(path, allow_pickle=False) as z:
                if "skip" in z.files:
                    return {"skip": str(z["skip"])}
                return {"ph": z["ph"], "coh": z["coh"], "tf": tuple(float(v) for v in z["tf"]), "crs": str(z["crs"]),
                        "incidence": z["incidence"] if "incidence" in z.files else None,
                        "valid_fraction": float(z["valid_fraction"]), "mean_coherence": float(z["mean_coherence"]),
                        "note": str(z["note"])}
        except Exception:
            return None

    def save_prepared(self, item, spec, prep):
        if not self.opts.use_cache:
            return
        path = self._prep_path(item, spec)
        tmp = path.with_name(path.stem + ".partial.npz")
        if "skip" in prep:
            np.savez_compressed(tmp, skip=np.array(prep["skip"]))
        else:
            incidence = prep.get("incidence")
            if incidence is None:
                incidence = np.zeros(0, np.float32)
            np.savez_compressed(tmp, ph=prep["ph"], coh=prep["coh"], incidence=incidence,
                                tf=np.array(prep["tf"], dtype=np.float64),
                                crs=np.array(prep["crs"]), valid_fraction=prep["valid_fraction"],
                                mean_coherence=prep["mean_coherence"], note=np.array(prep["note"]))
        os.replace(tmp, path)

    def _load_cache(self, path):
        try:
            with np.load(path, allow_pickle=False) as z:
                cc = z["cc"] if z["cc"].size else None
                return {"phase": z["phase"], "coh": z["coh"], "cc": cc if self.opts.use_cc else None,
                        "incidence": z["incidence"] if "incidence" in z.files else None,
                        "tf": tuple(float(v) for v in z["tf"]), "crs": str(z["crs"])}
        except Exception as exc:  # corrupt/partial cache entry -> refetch
            print(f"  cache entry unreadable ({type(exc).__name__}); refetching")
            return None

    def _save_cache(self, path, clip):
        tmp = path.with_name(path.stem + ".partial.npz")
        cc = clip["cc"] if clip["cc"] is not None else np.zeros(0, np.int32)
        incidence = clip.get("incidence")
        if incidence is None:
            incidence = np.zeros(0, np.float32)
        np.savez_compressed(tmp, phase=clip["phase"], coh=clip["coh"], cc=cc,
                            incidence=incidence,
                            tf=np.array(clip["tf"], dtype=np.float64), crs=np.array(clip["crs"]))
        os.replace(tmp, path)

    # -- auth (called from the main thread before workers start) --
    def authenticate(self):
        import requests
        from earthdata_auth import get_token
        self._token = get_token()
        if self._token is None:
            user = os.environ.get("EARTHDATA_USER") or os.environ.get("EDL_USERNAME")
            password = os.environ.get("EARTHDATA_PASS") or os.environ.get("EDL_PASSWORD")
            if user and password:
                self._creds = (user, password)
            else:
                raise RuntimeError("No Earthdata token found. Run `python earthdata_auth.py --store` once to save a token securely.")
        self._collection = get_collection_id(requests)

    def _client(self):
        if getattr(self._local, "client", None) is None:
            from harmony import Client
            self._local.client = Client(token=self._token) if self._token else Client(auth=self._creds)
        return self._local.client

    def _harmony(self, item, bbox, want_cc):
        from harmony import BBox, Collection, Request
        base = f"/science/LSAR/GUNW/grids/frequencyA/unwrappedInterferogram/{item['pol']}"
        variables = [f"{base}/unwrappedPhase", f"{base}/coherenceMagnitude"]
        if want_cc:
            variables.append(f"{base}/connectedComponents")
        request = Request(collection=Collection(id=self._collection), spatial=BBox(*bbox),
                          granule_name=[item["name"]], variables=variables,
                          format="image/tiff", max_results=1, skip_preview=True)
        client = self._client()
        with tempfile.TemporaryDirectory(prefix="nisar_clip_", ignore_cleanup_errors=True) as tmp:
            job = client.submit(request)
            files = [Path(f.result()) for f in client.download_all(job, directory=tmp, overwrite=True)]
            return _read_layers(files, want_cc)

    def load(self, item, bbox):
        """Return (clip, source) where source is 'cache' or 'harmony'; clip None if offline cache miss."""
        path = self._path(item, bbox)
        if self.opts.use_cache and path.exists():
            clip = self._load_cache(path)
            if clip is not None:
                return clip, "cache"
        if self.opts.offline:
            return None, "offline"
        want_cc = not self._cc_disabled
        try:
            clip = _retry(lambda: self._harmony(item, bbox, want_cc), attempts=2 if want_cc else 3)
        except Exception as exc:
            if not want_cc:
                raise
            with self._lock:
                if not self._cc_disabled:
                    self._cc_disabled = True
                    print(f"  connectedComponents request failed twice ({type(exc).__name__}: {exc}); "
                          "continuing without it for all remaining pairs")
            clip = _retry(lambda: self._harmony(item, bbox, False))
        if self.opts.use_cache:
            self._save_cache(path, clip)
        return clip, "harmony"


# ======================= Per-pair preparation (compact) =====================
def _prepare_pair(clip, spec):
    """Mask, keep the dominant unwrapped component, and coherence-weighted multilook one clipped pair."""
    phase, coh, cc, tf, crs = clip["phase"], clip["coh"], clip["cc"], clip["tf"], clip["crs"]
    valid = np.isfinite(phase) & np.isfinite(coh) & (coh >= COHERENCE_MIN) & (phase != 0)
    note = ""
    if cc is not None:
        # Pixels in different connected components carry unrelated 2*pi offsets: keep only the component
        # that holds most coherent pixels in the target/reference zones, and drop unwrapping failures (0).
        valid &= cc > 0
        tgt, ref = _zone_masks(phase.shape, tf, crs, spec["center"])
        ids, counts = np.unique(cc[valid & (ref | tgt)], return_counts=True)
        if ids.size >= 1:
            keep = int(ids[np.argmax(counts)])
            n_comp = np.unique(cc[valid]).size
            valid &= cc == keep  # every other component (even outside the zones) has an unknown 2*pi offset
            if n_comp > 1:
                note = f"kept connected component {keep} of {n_comp}"
    weight = np.where(valid, _coh_weight(np.nan_to_num(coh)), 0.0)
    ph_ml = _block_mean(phase, MULTILOOK, weight)
    coh_ml = _block_mean(coh, MULTILOOK, valid.astype(np.float32))
    tf_ml = _scale_tf(tf, MULTILOOK)
    finite = np.isfinite(ph_ml)
    vfrac = float(finite.mean())
    if vfrac < MIN_VALID_FRACTION:
        return {"skip": f"valid fraction {vfrac:.2f} < {MIN_VALID_FRACTION}"}
    tml, rml = _zone_masks(ph_ml.shape, tf_ml, crs, spec["center"])
    if (finite & tml).sum() < MIN_PIXELS_PER_ZONE or (finite & rml).sum() < MIN_PIXELS_PER_ZONE:
        return {"skip": "too few coherent pixels in target/reference zones"}
    incidence = clip.get("incidence")
    inc_ml = _block_mean(incidence, MULTILOOK) if incidence is not None else None
    return {"ph": ph_ml.astype(np.float32), "coh": coh_ml.astype(np.float32), "incidence": inc_ml,
            "tf": tf_ml, "crs": crs,
            "valid_fraction": vfrac, "mean_coherence": float(np.nanmean(coh_ml)), "note": note}


def _acquire(city, idx, total, item, spec, fetcher):
    tag = f"[{city}] pair {idx}/{total} {item['start'].date()} -> {item['end'].date()}"
    try:
        prep = fetcher.load_prepared(item, spec)
        source = "prep-cache"
        if prep is None:
            clip, source = fetcher.load(item, spec["bbox"])
            if clip is None:
                print(f"{tag}: not cached (offline)")
                return {"status": "skipped: not in cache (offline mode)"}
            prep = _prepare_pair(clip, spec)
            fetcher.save_prepared(item, spec, prep)
    except Exception as exc:
        print(f"{tag}: FAILED {type(exc).__name__}: {exc}")
        return {"status": f"failed: {type(exc).__name__}: {exc}"}
    if "skip" in prep:
        print(f"{tag}: skipped ({prep['skip']})")
        return {"status": f"skipped: {prep['skip']}"}
    print(f"{tag}: ok ({source}{'; ' + prep['note'] if prep['note'] else ''})")
    prep["status"] = "ok"
    return prep


# ============================ Stack processing ==============================
def _detrend_stack(PH, COH, rml, exclude, sign):
    """Per-pair robust ramp removal (ramp fitted outside `exclude`), reference-annulus zeroing, rad -> LOS cm."""
    scale = sign * WAVELENGTH_M * 100.0 / (4 * np.pi)
    Y = np.full(PH.shape, np.nan, np.float32)
    for i in range(PH.shape[0]):
        ph = PH[i].astype(np.float64)
        usable = np.isfinite(ph) & (COH[i] >= COHERENCE_MIN)
        ramp = _robust_surface(ph, usable & ~exclude)
        if ramp is None:
            ramp = _robust_surface(ph, usable)
        if ramp is None:
            continue
        clean = ph - ramp
        ref = clean[rml & np.isfinite(clean)]
        if ref.size < MIN_PIXELS_PER_ZONE:
            continue
        Y[i] = (clean - np.median(ref)) * scale
    return Y


def _fit_rates(Y, C, dt, iterations=4):
    """Robust, coherence-weighted constant-rate fit through the origin (Y_i = rate * dt_i).

    - per-pair noise levels down-weight noisy pairs; grossly noisy pairs are dropped
    - Tukey bisquare reweighting across time rejects unwrapping jumps pixel by pixel
    - formal sigma treats pairs as independent, which is conservative for a chain of
      consecutive pairs (their atmospheric errors partly cancel); use the spatial noise floor too.
    """
    n = Y.shape[0]
    finite = np.isfinite(Y) & np.isfinite(C) & (C >= COHERENCE_MIN)
    Y0 = np.where(finite, Y, 0.0).astype(np.float64)
    Wc = np.where(finite, _coh_weight(np.nan_to_num(C)), 0.0)
    dt3 = dt[:, None, None]
    robust = np.ones_like(Wc)
    pair_w = np.ones(n)

    def solve(W):
        den = np.sum(W * dt3 ** 2, axis=0)
        nobs = np.sum(W > 0, axis=0)
        ok = (den > 0) & (nobs >= MIN_PAIRS_PER_PIXEL)
        rate = np.divide(np.sum(W * Y0 * dt3, axis=0), den, out=np.full(den.shape, np.nan), where=ok)
        res = np.where(finite & ok[None], Y0 - np.nan_to_num(rate)[None] * dt3, np.nan)
        return rate, den, nobs, ok, res

    for _ in range(iterations):
        W = Wc * robust * pair_w[:, None, None]
        _, _, _, _, res = solve(W)
        s = np.array([_mad(res[i]) for i in range(n)])
        good = np.isfinite(s) & (s > 1e-6)
        if not good.any():
            break
        ref_s = float(np.median(s[good]))
        pw = np.clip((ref_s / np.where(good, s, 1.0)) ** 2, 0.0, 4.0)
        pair_w = np.where(good & (s <= PAIR_REJECT_FACTOR * ref_s), pw, 0.0)
        scale = np.where(good, s, ref_s)
        u = np.abs(res) / (TUKEY_C * scale[:, None, None])
        robust = np.where(np.isfinite(u), np.where(u < 1, (1 - u ** 2) ** 2, 0.0), 1.0)

    W = Wc * robust * pair_w[:, None, None]
    rate, den, nobs, ok, res = solve(W)
    dof = np.maximum(nobs - 1, 1)
    safe_den = np.where(den > 0, den, np.nan)
    sig2 = np.sum(W * np.nan_to_num(res) ** 2, axis=0) / dof / safe_den
    sigma = np.where(ok & (nobs >= 2), np.sqrt(sig2), np.nan)
    pair_s = np.array([_mad(res[i]) for i in range(n)])
    rej = np.array([float(np.mean(robust[i][finite[i]] == 0)) if finite[i].any() else np.nan for i in range(n)])
    return {"rate_yr": rate * 365.25, "sigma_yr": sigma * 365.25, "nobs": nobs, "W": W,
            "pair_s": pair_s, "pair_w": pair_w, "rejected_fraction": rej}


def _detect(rate_yr, exclude):
    """Two-sided anomaly detection relative to the map median; noise measured away from known bowls."""
    smoothed = _smooth(rate_yr, SMOOTH_WINDOW)
    fin = np.isfinite(smoothed)
    use = fin & ~exclude
    if use.sum() < 100:
        use = fin
    baseline = _nanstat(np.median, smoothed[use])
    noise = _mad(smoothed[use])
    threshold = max(NOISE_SIGMA_MULTIPLIER * noise if np.isfinite(noise) else np.inf, MIN_SIGNAL_CM_YR)
    anomaly = smoothed - baseline
    blobs, hotspot = [], np.zeros(rate_yr.shape, bool)
    for sign, cand in ((+1, fin & (anomaly >= threshold)), (-1, fin & (anomaly <= -threshold))):
        if not cand.any():
            continue
        cand &= np.nan_to_num(_smooth(cand.astype(np.float64), 5), nan=0.0) >= 0.50
        labels, n = _label(cand)
        for lab in range(1, n + 1):
            rows, cols = np.nonzero(labels == lab)
            if rows.size >= MIN_HOTSPOT_PIXELS:
                blobs.append({"sign": sign, "rows": rows, "cols": cols})
                hotspot[rows, cols] = True
    blobs.sort(key=lambda b: -b["rows"].size)
    return {"smoothed": smoothed, "baseline": baseline, "noise": noise, "threshold": threshold,
            "hotspot": hotspot, "blobs": blobs}


def _cumulative_series(dates, values, weights):
    """Interval-increment inversion -> cumulative LOS displacement at each acquisition date.

    Intervals not covered by any usable pair (e.g. a flagged noisy pair) are bridged with the mean
    rate of the covered intervals and reported as interpolated. Returns (nodes, cum, interpolated)
    where interpolated[k] marks that the step into node k was bridged.
    """
    nodes = sorted({d.date() for ab in dates for d in ab})
    index = {d: i for i, d in enumerate(nodes)}
    A = np.zeros((len(dates), len(nodes) - 1))
    for p, (a, b) in enumerate(dates):
        i, j = index[a.date()], index[b.date()]
        A[p, i:j] = 1.0
    ok = np.isfinite(values) & (weights > 0)
    if ok.sum() < 2:
        return nodes, None, None
    sw = np.sqrt(weights[ok])
    inc, *_ = np.linalg.lstsq(A[ok] * sw[:, None], values[ok] * sw, rcond=None)
    covered = A[ok].sum(0) > 0
    days = np.diff([d.toordinal() for d in nodes]).astype(np.float64)
    inc = np.where(covered, inc, 0.0)
    if (~covered).any():
        inc[~covered] = inc[covered].sum() / days[covered].sum() * days[~covered]
    return nodes, np.concatenate([[0.0], np.cumsum(inc)]), np.concatenate([[False], ~covered])


# ================================ Output ====================================
def _clean(v):
    if isinstance(v, (float, np.floating)) and not np.isfinite(v):
        return None
    if isinstance(v, np.generic):
        return v.item()
    return v


def _write_csv(path, rows):
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fields = list(dict.fromkeys(k for r in rows for k in r))
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows([{k: _clean(v) for k, v in r.items()} for r in rows])


def _write_geotiff(path, arr, tf, crs_wkt):
    import rasterio
    from rasterio.transform import Affine
    with rasterio.open(path, "w", driver="GTiff", height=arr.shape[0], width=arr.shape[1], count=1,
                       dtype="float32", crs=crs_wkt, transform=Affine(*tf), nodata=np.nan, compress="deflate") as dst:
        dst.write(arr.astype(np.float32), 1)


def _plot_gallery(path, city, Y, labels, notes, plt):
    n = Y.shape[0]
    cols = min(4, n)
    rows = math.ceil(n / cols)
    fig, axes = plt.subplots(rows, cols, figsize=(3.5 * cols, 3.1 * rows + 0.6), squeeze=False, constrained_layout=True)
    lim = float(np.median([_robust_lim(Y[i], 1.0) for i in range(n)]))  # typical pair; outliers saturate
    im = None
    for ax in axes.ravel():
        ax.set_xticks([]); ax.set_yticks([])
    for i in range(n):
        ax = axes.ravel()[i]
        im = ax.imshow(Y[i], cmap="RdBu_r", vmin=-lim, vmax=lim, origin="upper")
        ax.set_title(f"{labels[i]}\n{notes[i]}", fontsize=8, color="crimson" if "FLAG" in notes[i] else "black")
    for ax in axes.ravel()[n:]:
        ax.axis("off")
    if im is not None:
        fig.colorbar(im, ax=axes, shrink=0.8, label="differential LOS (cm, phase convention retained)")
    fig.suptitle(f"{city}: per-pair QC gallery (inspect for unwrapping jumps / atmosphere)", fontsize=10)
    fig.savefig(path, dpi=100)
    plt.close(fig)


# =========================== City processing ================================
def _process_city(city, spec, items, acquired, opts, out_root):
    plt = Circle = None
    if opts.plots:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib.patches import Circle

    status_rows = [{"city": city, "granule": it["name"], "status": r["status"]}
                   for it, r in zip(items, acquired) if r["status"] != "ok"]
    good = [(it, r) for it, r in zip(items, acquired) if r["status"] == "ok"]

    # All pairs must share one grid; keep the most common grid and report the rest.
    def gkey(r):
        return (r["ph"].shape, tuple(round(v, 3) for v in r["tf"]), r["crs"])

    if good:
        main_key = Counter(gkey(r) for _, r in good).most_common(1)[0][0]
        for it, r in good:
            if gkey(r) != main_key:
                print(f"[{city}] dropping {it['name']}: clip grid differs from the other pairs")
                status_rows.append({"city": city, "granule": it["name"], "status": "skipped: grid mismatch"})
        good = [(it, r) for it, r in good if gkey(r) == main_key]
    if len(good) < MIN_PAIRS_PER_PIXEL:
        print(f"[{city}] only {len(good)} usable pairs; need at least {MIN_PAIRS_PER_PIXEL}")
        return status_rows
    items_u = [it for it, _ in good]
    PH = np.stack([r["ph"] for _, r in good])
    COH = np.stack([r["coh"] for _, r in good])
    INC = np.stack([r["incidence"] if r.get("incidence") is not None else np.full_like(r["ph"], np.nan)
                    for _, r in good])
    tf, crs = good[0][1]["tf"], good[0][1]["crs"]
    shape = PH.shape[1:]
    dates = [(it["start"], it["end"]) for it in items_u]
    dtd = np.array([(b - a).total_seconds() / 86400 for a, b in dates], dtype=np.float64)
    tml, rml = _zone_masks(shape, tf, crs, spec["center"])
    px_km2 = abs(tf[0] * tf[4] - tf[1] * tf[3]) / 1e6

    # The bridge only needs the screened displacement stack, not the older
    # hotspot/rate products. Skip those legacy iterative fits on bridge runs.
    if opts.engine_export_only:
        Y = _detrend_stack(PH, COH, rml, np.zeros(shape, bool), opts.phase_sign)
        epoch_dates = sorted({d for pair in dates for d in pair})
        epoch_index = {d: i for i, d in enumerate(epoch_dates)}
        epoch_days = np.array([(d - epoch_dates[0]).total_seconds() / 86400 for d in epoch_dates], dtype=np.float64)
        pair_start = np.array([epoch_index[a] for a, _ in dates], dtype=np.int16)
        pair_end = np.array([epoch_index[b] for _, b in dates], dtype=np.int16)
        engine_weights = np.where(np.isfinite(Y) & (COH >= COHERENCE_MIN),
                                  _coh_weight(np.nan_to_num(COH)), 0.0).astype(np.float32)
        out = out_root / city
        out.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(out / "pair_stack_for_engine.npz", pair_displacement_cm=Y.astype(np.float32),
                            pair_start=pair_start, pair_end=pair_end, epoch_days=epoch_days,
                            weights=engine_weights, pair_coherence=COH.astype(np.float32),
                            incidence_angle_deg=INC.astype(np.float32), transform=np.asarray(tf, dtype=np.float64),
                            crs_wkt=np.asarray(crs), epoch_dates=np.asarray([d.isoformat() for d in epoch_dates]))
        return []

    # Iterative ramp removal: refit each pair's ramp with detected bowls masked out.
    exclude = np.zeros(shape, bool)
    for stage in range(1, DETREND_ITERATIONS + 1):
        Y = _detrend_stack(PH, COH, rml, exclude, opts.phase_sign)
        fit = _fit_rates(Y, COH, dtd)
        det = _detect(fit["rate_yr"], exclude)
        new_exclude = _dilate(det["hotspot"], HOTSPOT_DILATE_PX) if det["hotspot"].any() else np.zeros(shape, bool)
        union = (new_exclude | exclude).sum()
        stable = union == 0 or (new_exclude & exclude).sum() / union > 0.95
        print(f"[{city}] stage {stage}: {len(det['blobs'])} anomaly blob(s), "
              f"noise={det['noise']:.2f} cm/yr, threshold={det['threshold']:.2f}")
        if stable or stage == DETREND_ITERATIONS:
            break
        exclude = new_exclude

    hotspot, blobs, smoothed = det["hotspot"], det["blobs"], det["smoothed"]
    baseline, noise, threshold = det["baseline"], det["noise"], det["threshold"]
    rate_yr, sigma_yr = fit["rate_yr"], fit["sigma_yr"]
    detected = bool(blobs)

    # Additive handoff stack for the new reusable engine; legacy result files remain unchanged.
    epoch_dates = sorted({d for pair in dates for d in pair})
    epoch_index = {d: i for i, d in enumerate(epoch_dates)}
    epoch_days = np.array([(d - epoch_dates[0]).total_seconds() / 86400 for d in epoch_dates], dtype=np.float64)
    pair_start = np.array([epoch_index[a] for a, _ in dates], dtype=np.int16)
    pair_end = np.array([epoch_index[b] for _, b in dates], dtype=np.int16)
    engine_weights = np.where(np.isfinite(Y) & (COH >= COHERENCE_MIN), _coh_weight(np.nan_to_num(COH)), 0.0).astype(np.float32)

    # Reference-ring sanity check: the ring should not itself be deforming relative to the map.
    ring_rate = _nanstat(np.median, smoothed[rml])
    ref_offset = ring_rate - baseline if np.isfinite(ring_rate) else np.nan
    if np.isfinite(ref_offset) and abs(ref_offset) > threshold:
        print(f"[{city}] WARNING: reference annulus rate differs from the map median by {ref_offset:.1f} cm/yr "
              "(> detection threshold); the annulus may sit on deforming ground. Consider moving it.")

    out = out_root / city
    out.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(out / "pair_stack_for_engine.npz",
                        pair_displacement_cm=Y.astype(np.float32), pair_start=pair_start,
                        pair_end=pair_end, epoch_days=epoch_days, weights=engine_weights,
                        transform=np.asarray(tf, dtype=np.float64), crs_wkt=np.asarray(crs),
                        epoch_dates=np.asarray([d.isoformat() for d in epoch_dates]))

    # Pair QC table + gallery
    labels, notes, rows = [], [], []
    ok_by_pair = np.isfinite(Y).reshape(len(items_u), -1).any(axis=1)
    for i, it in enumerate(items_u):
        flagged = (fit["pair_w"][i] == 0) or not ok_by_pair[i]
        s = fit["pair_s"][i]
        labels.append(f"{it['start'].date()} -> {it['end'].date()}")
        notes.append(("FLAGGED " if flagged else "") + (f"resid MAD {s:.2f} cm" if np.isfinite(s) else "no data"))
        rows.append({"city": city, "pair_start": it["start"].isoformat(), "pair_end": it["end"].isoformat(),
                     "interval_days": float(dtd[i]), "track": it["track"], "direction": it["direction"],
                     "frame": it["frame"], "pol": it["pol"],
                     "target_median_los_cm": _nanstat(np.median, Y[i][tml]),
                     "valid_fraction": good[i][1]["valid_fraction"], "mean_coherence": good[i][1]["mean_coherence"],
                     "residual_mad_cm": s, "pair_weight": float(fit["pair_w"][i]),
                     "rejected_pixel_fraction": fit["rejected_fraction"][i],
                     "status": "flagged_noisy_excluded" if flagged else "used", "note": good[i][1]["note"],
                     "granule": it["name"]})
    if plt:
        _plot_gallery(out / "pair_gallery.png", city, Y, labels, notes, plt)

    # Blob statistics (+ lon/lat centroids)
    cx, cy = _lonlat_to_xy(crs, *spec["center"])
    blob_rows = []
    for k, b in enumerate(blobs[:10], 1):
        r, c = b["rows"], b["cols"]
        px, py = tf[0] * (c.mean() + 0.5) + tf[1] * (r.mean() + 0.5) + tf[2], tf[3] * (c.mean() + 0.5) + tf[4] * (r.mean() + 0.5) + tf[5]
        lon, lat = _xy_to_lonlat(crs, px, py)
        mean_anom = float(np.nanmean(rate_yr[r, c]) - baseline)
        blob_rows.append({"city": city, "blob": k, "sign": "positive LOS rate" if b["sign"] > 0 else "negative LOS rate",
                          "pixels": int(r.size), "area_km2": float(r.size * px_km2),
                          "mean_rate_vs_baseline_cm_yr": mean_anom,
                          "z_vs_noise_floor": float(abs(mean_anom) / noise) if np.isfinite(noise) and noise > 0 else None,
                          "strong_candidate": bool(r.size >= STRONG_AREA_FACTOR * MIN_HOTSPOT_PIXELS
                                                   and abs(mean_anom) >= STRONG_SIGNAL_FACTOR * threshold),
                          "peak_smoothed_rate_vs_baseline_cm_yr": float(smoothed[r, c][np.nanargmax(np.abs(smoothed[r, c] - baseline))] - baseline),
                          "mean_formal_sigma_cm_yr": _nanstat(np.mean, sigma_yr[r, c]),
                          "centroid_lon": float(lon), "centroid_lat": float(lat),
                          "centroid_distance_to_center_km": float(math.hypot(px - cx, py - cy) / 1000)})

    # Cumulative LOS time series (dominant blobs) from the weighted interval inversion
    ts_rows, series = [], []
    for k, b in enumerate(blobs[:3], 1):
        vals = np.array([_nanstat(np.mean, Y[i][b["rows"], b["cols"]]) for i in range(len(items_u))])
        nodes, cum, interp = _cumulative_series(dates, vals, fit["pair_w"])
        if cum is not None:
            series.append((f"blob {k} ({'+' if b['sign'] > 0 else '-'}, {b['rows'].size} px)", nodes, cum, interp))
            ts_rows += [{"city": city, "region": f"blob_{k}", "date": d.isoformat(), "cumulative_los_cm": v,
                         "interpolated": bool(ip)} for d, v, ip in zip(nodes, cum, interp)]
    vals = np.array([_nanstat(np.median, Y[i][tml]) for i in range(len(items_u))])
    nodes, cum, interp = _cumulative_series(dates, vals, fit["pair_w"])
    if cum is not None:
        series.append(("target-zone median", nodes, cum, interp))
        ts_rows += [{"city": city, "region": "target_zone_median", "date": d.isoformat(), "cumulative_los_cm": v,
                     "interpolated": bool(ip)} for d, v, ip in zip(nodes, cum, interp)]
    if plt and series:
        fig, ax = plt.subplots(figsize=(9, 4.8), constrained_layout=True)
        for label, nodes, cum, interp in series:
            line, = ax.plot(nodes, cum, marker="o", label=label)
            for k in np.nonzero(interp)[0]:  # bridged (excluded-pair) steps drawn dashed + hollow
                ax.plot(nodes[k - 1:k + 1], cum[k - 1:k + 1], ls=":", color="white", lw=2.5, zorder=3)
                ax.plot(nodes[k - 1:k + 1], cum[k - 1:k + 1], ls="--", color=line.get_color(), lw=1.2, zorder=4)
        ax.axhline(0, color="black", linewidth=0.7)
        ax.set_ylabel("cumulative differential LOS (cm)")
        ax.set_title(f"{city}: cumulative LOS change vs reference annulus (dashed = bridged excluded pair)")
        ax.grid(True, alpha=0.3); ax.legend(fontsize=8)
        fig.autofmt_xdate()
        fig.savefig(out / "timeseries.png", dpi=130); plt.close(fig)

    # Month-by-month modelled snapshots (final robust weights)
    W = fit["W"]
    monthly, cur = [], date(START.year, START.month, 1)
    big = blobs[0] if blobs else None
    while cur < END_EXCLUSIVE:
        nxt = date(cur.year + (cur.month == 12), cur.month % 12 + 1, 1)
        ids = [i for i, (a, b) in enumerate(dates) if cur <= (a + (b - a) / 2).date() < nxt]
        row = {"city": city, "month": cur.strftime("%Y-%m"), "n_pairs": len(ids),
               "modeled_target_median_delta_cm": None, "dominant_blob_mean_delta_cm": None}
        if ids:
            wm, dm = W[ids], dtd[ids, None, None]
            denom = np.sum(wm * dm ** 2, axis=0)
            mr = np.divide(np.sum(wm * np.nan_to_num(Y[ids]) * dm, axis=0), denom,
                           out=np.full(denom.shape, np.nan), where=denom > 0) * (nxt - cur).days
            row["modeled_target_median_delta_cm"] = _nanstat(np.median, mr[tml])
            if big is not None:
                row["dominant_blob_mean_delta_cm"] = _nanstat(np.mean, mr[big["rows"], big["cols"]])
        monthly.append(row)
        cur = nxt

    # Rate maps: arrays, GeoTIFFs, figures
    np.savez_compressed(out / "rate_map.npz", rate_cm_year=rate_yr.astype(np.float32),
                        formal_sigma_cm_year=sigma_yr.astype(np.float32), n_obs=fit["nobs"].astype(np.int16),
                        hotspot=hotspot, transform=np.array(tf), crs_wkt=np.array(crs),
                        noise_floor_cm_year=np.float32(noise), baseline_cm_year=np.float32(baseline))
    try:
        _write_geotiff(out / "rate_cm_year.tif", rate_yr, tf, crs)
        _write_geotiff(out / "rate_formal_sigma_cm_year.tif", sigma_yr, tf, crs)
    except Exception as exc:
        print(f"[{city}] GeoTIFF export skipped ({type(exc).__name__}: {exc})")

    if plt:
        fig, (ax, ax2) = plt.subplots(1, 2, figsize=(13, 5.6), constrained_layout=True)
        lim = _robust_lim(smoothed - baseline, 3.0)
        im = ax.imshow(smoothed - baseline, cmap="RdBu_r", vmin=-lim, vmax=lim, origin="upper")
        for b, color in ((bb, "black" if bb["sign"] > 0 else "magenta") for bb in blobs):
            m = np.zeros(shape, float)
            m[b["rows"], b["cols"]] = 1
            ax.contour(m, levels=[0.5], colors=color, linewidths=0.8)
        col, row = _xy_to_colrow(tf, cx, cy)
        ax.plot(col - 0.5, row - 0.5, marker="*", color="gold", markeredgecolor="black", markersize=12)
        ax.add_patch(Circle((col - 0.5, row - 0.5), TARGET_RADIUS_KM * 1000 / abs(tf[0]), fill=False, ls="--", lw=0.8, ec="gray"))
        ax.set_title(f"{city} | LOS rate vs map median (cm/yr)\n"
                     f"{'candidate anomalies: ' + str(len(blobs)) if detected else 'no robust anomaly detected'} "
                     f"| noise {noise:.2f}, threshold {threshold:.2f}", fontsize=9)
        fig.colorbar(im, ax=ax, label="cm/yr (black: +, magenta: -)")
        im2 = ax2.imshow(sigma_yr, cmap="viridis", origin="upper", vmin=0, vmax=_robust_lim(sigma_yr, 1.0, 95))
        ax2.set_title("Formal rate sigma (cm/yr, conservative)", fontsize=9)
        fig.colorbar(im2, ax=ax2, label="cm/yr")
        fig.savefig(out / "overall_rate.png", dpi=140); plt.close(fig)

        fig, ax = plt.subplots(figsize=(11, 4.8), constrained_layout=True)
        mx = np.arange(len(monthly))
        ax.bar(mx, [np.nan if r["modeled_target_median_delta_cm"] is None else r["modeled_target_median_delta_cm"] for r in monthly], color="#287da1")
        ax.axhline(0, color="black", linewidth=0.7)
        ax.set_xticks(mx, [r["month"] for r in monthly], rotation=45, ha="right")
        ax.set_ylabel("Modeled differential LOS change (cm/month)")
        ax.set_title(f"{city}: modelled monthly change, target-zone median (blank = no GUNW pair in month)")
        ax.grid(True, axis="y", alpha=0.25)
        fig.savefig(out / "monthly_deltas.png", dpi=140); plt.close(fig)

    span_days = (max(b for _, b in dates) - min(a for a, _ in dates)).total_seconds() / 86400
    target_rate = _nanstat(np.median, rate_yr[tml])
    overall = [{"city": city, "first_pair_start": min(a for a, _ in dates).isoformat(),
                "last_pair_end": max(b for _, b in dates).isoformat(), "span_days": span_days,
                "pairs_used": int(np.sum(fit["pair_w"] > 0)), "pairs_flagged": int(np.sum(fit["pair_w"] == 0)),
                "target_zone_median_los_cm_per_year": target_rate,
                "target_zone_los_delta_cm_over_span": target_rate * span_days / 365.25,
                "map_median_rate_cm_per_year": baseline, "reference_ring_offset_cm_per_year": ref_offset,
                "anomaly_blobs": len(blobs), "strong_candidate_blobs": sum(bool(r["strong_candidate"]) for r in blob_rows),
                "candidate_anomaly_pixels": int(hotspot.sum()),
                "candidate_anomaly_detected": detected, "noise_floor_cm_per_year": noise,
                "threshold_cm_per_year": threshold, "ramp_order": RAMP_ORDER, "detrend_stages": stage,
                "phase_sign_applied": opts.phase_sign,
                "sign_note": "two-sided LOS anomaly; sign not automatically labeled subsidence"}]
    _write_csv(out / "pair_measurements.csv", rows)
    _write_csv(out / "hotspots.csv", blob_rows)
    _write_csv(out / "timeseries.csv", ts_rows)
    _write_csv(out / "monthly_summary.csv", monthly)
    _write_csv(out / "overall_summary.csv", overall)
    print(f"[{city}] {int(np.sum(fit['pair_w'] > 0))}/{len(items_u)} pairs used; noise floor={noise:.2f} cm/yr; "
          f"anomaly blobs={len(blobs)}; artifacts={out}")
    return rows + status_rows


# ================================= Main =====================================
def _strip(items):
    return [{k: v for k, v in it.items() if k != "product"} for it in items]  # ASF product objects don't pickle


def _save_selection_preview(clip, spec, label, item, output):
    """Render the selected footprint over raw GUNW phase and coherence; performs no deformation analysis."""
    import matplotlib.pyplot as plt
    from rasterio.features import geometry_mask
    from rasterio.transform import Affine
    from shapely.geometry import mapping, shape as make_shape
    from pyproj import CRS, Transformer
    geom = make_shape(SELECTION_GEOMETRY)
    project = Transformer.from_crs("EPSG:4326", CRS.from_wkt(clip["crs"]), always_xy=True)
    from shapely.ops import transform as transform_geometry
    projected = transform_geometry(project.transform, geom)
    inside = geometry_mask([mapping(projected)], out_shape=clip["phase"].shape,
                           transform=Affine(*clip["tf"]), invert=True)
    phase = np.ma.masked_where(~inside | ~np.isfinite(clip["phase"]) | (clip["phase"] == 0), clip["phase"])
    coherence = np.ma.masked_where(~inside | ~np.isfinite(clip["coh"]), clip["coh"])
    fig, axes = plt.subplots(1, 2, figsize=(12, 5), constrained_layout=True)
    for ax, data, title, cmap in ((axes[0], phase, "Unwrapped phase (radians)", "RdBu_r"),
                                  (axes[1], coherence, "Coherence magnitude", "viridis")):
        im = ax.imshow(data, cmap=cmap)
        ax.set_title(title)
        ax.set_axis_off()
        fig.colorbar(im, ax=ax, shrink=0.78)
    fig.suptitle(f"{label} | NISAR GUNW {item['start'].date()} → {item['end'].date()}\n"
                 "Raw selected-area raster preview; no subsidence analysis performed")
    fig.savefig(output, dpi=180)
    plt.close(fig)


def _expanded_aoi_bbox(geometry, margin_m=22_000):
    """Return a lon/lat bbox around a metric buffer, large enough for the reference annulus."""
    from pyproj import Transformer
    from shapely.geometry import shape as make_shape
    from shapely.ops import transform as transform_geometry
    geom = make_shape(geometry)
    center = geom.representative_point()
    zone = max(1, min(60, int((center.x + 180) // 6) + 1))
    epsg = (32600 if center.y >= 0 else 32700) + zone
    to_utm = Transformer.from_crs("EPSG:4326", f"EPSG:{epsg}", always_xy=True)
    to_lonlat = Transformer.from_crs(f"EPSG:{epsg}", "EPSG:4326", always_xy=True)
    buffered = transform_geometry(to_utm.transform, geom).buffer(margin_m)
    west, south, east, north = transform_geometry(to_lonlat.transform, buffered).bounds
    return west, south, east, north


def _download_asf_browse(item, output):
    """Save ASF's original NISAR browse PNG for the GUNW granule intersecting the AOI."""
    import requests
    from earthdata_auth import get_token
    urls = (item.get("product").properties.get("browse", []) if item.get("product") else [])
    if isinstance(urls, str):
        urls = [urls]
    url = next((u for u in urls if "_LATLON.png" in u), None)
    url = url or next((u for u in urls if u.lower().endswith(".png")), None)
    if not url:
        raise RuntimeError(f"ASF returned no browse PNG for {item['name']}.")
    token = get_token()
    response = requests.get(url, headers={"Authorization": f"Bearer {token}"} if token else {}, timeout=120)
    response.raise_for_status()
    if not response.content.startswith(b"\x89PNG\r\n\x1a\n"):
        raise RuntimeError(f"ASF browse endpoint did not return PNG bytes (content type {response.headers.get('Content-Type')}).")
    output.write_bytes(response.content)


def main():
    t_start = time.perf_counter()
    parser = argparse.ArgumentParser(description="NISAR GUNW small-area LOS change screening (v3)")
    parser.add_argument("--inventory-only", action="store_true", help="ASF catalog search only; no login or raster retrieval")
    parser.add_argument("--offline", action="store_true", help="use only cached clips; never contact Harmony or ask for login")
    parser.add_argument("--no-cache", action="store_true", help="do not read or write the clip cache")
    parser.add_argument("--no-connected-components", action="store_true", help="do not request the connectedComponents layer (less server work)")
    parser.add_argument("--no-plots", action="store_true", help="skip PNG figures (CSV/NPZ/GeoTIFF only; fastest)")
    parser.add_argument("--engine-export-only", action="store_true",
                        help="build the bridge stack and skip the legacy hotspot/rate model and visual products")
    parser.add_argument("--serial", action="store_true", help="process cities one after another instead of in parallel processes")
    parser.add_argument("--workers", type=int, default=0, help="concurrent Harmony requests (default: all of them, max %d)" % MAX_WORKERS)
    parser.add_argument("--phase-sign", type=float, choices=(1.0, -1.0), default=PHASE_SIGN, help="multiply phase by this sign")
    parser.add_argument("--cities", nargs="+", type=str.capitalize, choices=list(AOIS), help="subset of cities")
    parser.add_argument("--output", type=Path, default=OUT_DIR)
    parser.add_argument("--cache-dir", type=Path, help="persistent directory for raw and prepared spatial subsets")
    parser.add_argument("--geojson", type=Path, help="GeoJSON Polygon or MultiPolygon AOI")
    parser.add_argument("--selection-id", help="Load a saved app selection directly from backend/data/selections.sqlite3")
    parser.add_argument("--label", default="Selected area")
    parser.add_argument("--start-date", type=date.fromisoformat, help="inclusive ASF search start date (YYYY-MM-DD)")
    parser.add_argument("--end-date-exclusive", type=date.fromisoformat, help="exclusive ASF search end date (YYYY-MM-DD)")
    parser.add_argument("--preview-only", action="store_true", help="save the original ASF browse PNG for one intersecting GUNW granule; skip analysis")
    parser.add_argument("--raster-preview", action="store_true", help="save the Harmony phase/coherence raster plot instead of the ASF browse PNG")
    parser.add_argument("--store-earthdata-token", action="store_true", help="securely save a user token in the OS credential vault, then exit")
    parser.add_argument("--clear-earthdata-token", action="store_true", help="remove the token from the OS credential vault, then exit")
    args = parser.parse_args()
    global START, END_EXCLUSIVE
    START = args.start_date or START
    END_EXCLUSIVE = args.end_date_exclusive or END_EXCLUSIVE
    if START >= END_EXCLUSIVE:
        raise ValueError("--start-date must be earlier than --end-date-exclusive")
    if args.store_earthdata_token or args.clear_earthdata_token:
        from earthdata_auth import clear_token, store_token
        clear_token() if args.clear_earthdata_token else store_token()
        return
    global SELECTION_GEOMETRY
    if args.geojson or args.selection_id:
        from shapely.geometry import shape as make_shape
        from shapely.validation import explain_validity
        if args.selection_id:
            import sqlite3
            db_path = Path(__file__).resolve().parent / "backend" / "data" / "selections.sqlite3"
            with sqlite3.connect(db_path) as db:
                if args.selection_id == "latest":
                    row = db.execute("SELECT selection_id, record_json FROM selections ORDER BY created_at DESC, id DESC LIMIT 1").fetchone()
                else:
                    row = db.execute("SELECT selection_id, record_json FROM selections WHERE selection_id = ?", (args.selection_id,)).fetchone()
            if not row:
                raise ValueError(f"No saved selection found for ID {args.selection_id}")
            if args.selection_id == "latest":
                args.selection_id = row[0]
            record = json.loads(row[1])
            feature = record["geometry"]
            args.label = record["label"].replace(" ", "")
        else:
            feature = json.loads(args.geojson.read_text(encoding="utf-8"))
        if feature.get("type") == "Feature":
            feature = feature.get("geometry") or {}
        geom = make_shape(feature)
        if geom.geom_type not in ("Polygon", "MultiPolygon") or geom.is_empty or not geom.is_valid:
            raise ValueError(f"Invalid AOI GeoJSON: {explain_validity(geom)}")
        SELECTION_GEOMETRY = feature
        fetch_bbox = _expanded_aoi_bbox(feature)
        point = geom.representative_point()
        AOIS[args.label] = {"center": (point.x, point.y), "bbox": fetch_bbox}
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    opts = RunOptions(workers=max(0, args.workers), plots=not args.no_plots, phase_sign=args.phase_sign,
                      use_cache=not args.no_cache, offline=args.offline, use_cc=not args.no_connected_components,
                      engine_export_only=args.engine_export_only)
    has_selection = bool(args.geojson or args.selection_id)
    aois = {c: AOIS[c] for c in (args.cities or ([args.label] if has_selection else AOIS))}

    import asf_search as asf
    try:
        inventory = {city: choose_track(city, search_city(asf, city, spec)) for city, spec in aois.items()}
    except Exception as exc:
        details = f"{type(exc).__name__}: {exc}"
        if "getaddrinfo failed" in details or "NameResolutionError" in details:
            raise SystemExit(
                "ASF catalog search could not resolve cmr.earthdata.nasa.gov. "
                "Check internet access, VPN/proxy, and DNS, then retry. "
                "This occurs before Earthdata token authentication."
            ) from None
        raise
    inv_rows = [{**{k: (v.isoformat() if isinstance(v, datetime) else v) for k, v in item.items() if k != "product"}, "city": city}
                for city, items in inventory.items() for item in items]
    _write_csv(out / "asf_inventory.csv", inv_rows)
    if args.inventory_only:
        print(f"Inventory written to {out}; no raster downloads requested.")
        return
    if not any(inventory.values()):
        print("No matching NISAR GUNW products found. Stopping without raster requests.")
        return

    if args.preview_only or args.raster_preview:
        if SELECTION_GEOMETRY is None:
            raise ValueError("Preview mode requires --geojson or --selection-id")
        city = next(name for name, items in inventory.items() if items)
        item = inventory[city][0]
        if args.preview_only:
            browse_path = out / f"{city}_asf_browse_{item['start'].date()}.png"
            _download_asf_browse(item, browse_path)
            print(f"Original ASF browse image saved to {browse_path}; no analysis or raster rendering was performed.")
            return
        fetcher = Fetcher(args.cache_dir or out / "clip_cache", opts)
        raw_clip_cached = opts.use_cache and fetcher._path(item, aois[city]["bbox"]).exists()
        if not raw_clip_cached and not opts.offline:
            from earthdata_auth import get_token
            token = get_token()
            has_password_env = bool((os.environ.get("EARTHDATA_USER") or os.environ.get("EDL_USERNAME")) and
                                    (os.environ.get("EARTHDATA_PASS") or os.environ.get("EDL_PASSWORD")))
            if not token and not has_password_env:
                raise RuntimeError("No Earthdata token is configured. Save one first with `python nisar_selection_subsidence.py --store-earthdata-token`.")
            fetcher.authenticate()
        cached, _source = fetcher.load(item, aois[city]["bbox"])
        if cached is None:
            raise RuntimeError("No cached GUNW raster is available; configure Earthdata credentials to fetch via Harmony.")
        preview_path = out / f"{city}_gunw_preview.png"
        _save_selection_preview(cached, aois[city], city, item, preview_path)
        print(f"Preview saved to {preview_path}; screening and deformation analysis were skipped.")
        return

    fetcher = Fetcher(args.cache_dir or out / "clip_cache", opts)
    missing = [(c, it) for c, items in inventory.items() for it in items if not fetcher.is_cached(it, aois[c])]
    total = sum(len(v) for v in inventory.values())
    if missing and not opts.offline:
        print(f"{len(missing)} of {total} clip(s) not cached; authenticating for Harmony "
              f"(all {len(missing)} requests will run concurrently - expect roughly one Harmony job latency).")
        fetcher.authenticate()
    elif missing:
        print(f"Offline mode: {len(missing)} uncached clip(s) will be skipped.")
    else:
        print(f"All {total} clips cached; no login or Harmony requests needed.")
    workers = opts.workers or min(MAX_WORKERS, max(4, len(missing)))

    cities = [c for c in inventory if inventory[c]]
    if not cities:
        return
    all_pairs, failed = [], []
    io_pool = ThreadPoolExecutor(max_workers=workers)
    n_proc = 1 if args.serial else max(1, min(len(cities), os.cpu_count() or 1))
    proc_pool = ProcessPoolExecutor(max_workers=n_proc) if n_proc > 1 else None
    try:
        pair_futs, owner = {}, {}
        for city in cities:
            pair_futs[city] = [io_pool.submit(_acquire, city, i, len(inventory[city]), it, aois[city], fetcher)
                               for i, it in enumerate(inventory[city], 1)]
            owner.update({f: city for f in pair_futs[city]})
        remaining = {c: len(f) for c, f in pair_futs.items()}
        city_jobs = {}
        for fut in as_completed(owner):                 # process each city the moment its last clip lands
            city = owner[fut]
            remaining[city] -= 1
            if remaining[city]:
                continue
            acquired = [f.result() for f in pair_futs[city]]
            args_ = (city, aois[city], _strip(inventory[city]), acquired, opts, out)
            if proc_pool:
                city_jobs[proc_pool.submit(_process_city, *args_)] = city
            else:
                try:
                    all_pairs.extend(_process_city(*args_))
                except Exception:
                    failed.append(city)
                    print(f"[{city}] processing failed:\n{traceback.format_exc()}")
        for fut in as_completed(city_jobs):
            try:
                all_pairs.extend(fut.result())
            except Exception:
                failed.append(city_jobs[fut])
                print(f"[{city_jobs[fut]}] processing failed:\n{''.join(traceback.format_exception(fut.exception()))}")
    finally:
        io_pool.shutdown(wait=True, cancel_futures=True)
        if proc_pool:
            proc_pool.shutdown(wait=True, cancel_futures=True)

    _write_csv(out / "all_city_pair_measurements.csv", all_pairs)
    first = min((it["start"] for items in inventory.values() for it in items), default=None)
    last = max((it["end"] for items in inventory.values() for it in items), default=None)
    elapsed = time.perf_counter() - t_start
    manifest = {
        "created_utc": datetime.now(timezone.utc).isoformat(), "mission": "NISAR", "archive": "ASF DAAC",
        "collection": COLLECTION, "period_start": START.isoformat(), "period_end_exclusive": END_EXCLUSIVE.isoformat(),
        "catalog_coverage_found": [first.isoformat() if first else None, last.isoformat() if last else None],
        "cities_processed": [c for c in cities if c not in failed], "cities_failed": failed,
        "runtime_seconds": round(elapsed, 1), "clips_fetched_from_harmony": len(missing) if not opts.offline else 0,
        "raster_access": ("Harmony spatial subset; phase, coherence and (if available) connectedComponents COGs; "
                          "temporary files deleted; small clipped arrays cached in clip_cache") if opts.use_cache else
                         "Harmony spatial subset; temporary files deleted; no cache",
        "analysis": ("dominant connected component, coherence-weighted multilooking, iterative robust ramp removal with "
                     "bowl masking, local reference annulus, Tukey-robust weighted LOS rate fit, two-sided blob detection"),
        "interpretation": "LOS relative displacement only; not vertical-only subsidence; phase sign not auto-interpreted",
        "parameters": {k: v for k, v in globals().items() if k.isupper() and isinstance(v, (int, float, str, tuple))
                       and k not in ("CMR_URL", "STAMP_RE")} | {"phase_sign_applied": opts.phase_sign,
                                                                 "connected_components_requested": opts.use_cc},
    }
    (out / "run_manifest.json").write_text(json.dumps(manifest, indent=2, default=str), encoding="utf-8")
    print(f"Finished in {elapsed:.1f} s. Results are in {out}")


if __name__ == "__main__":
    main()
