"""Reusable native-grid imagery, process-safe request locks and bounded extents.

Only raw arrays are shared. Farm masks, multilooking and reference fits remain
selection-specific. No interpolation or resampling is performed by this module.
"""
from __future__ import annotations

from contextlib import contextmanager, closing
import json
import errno
import math
import os
from pathlib import Path
import sqlite3
import time


@contextmanager
def request_lock(path: Path):
    """OS-owned lock: released on process death, unlike a stale sentinel file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle:
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        while True:
            try:
                handle.seek(0)
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError as exc:
                if exc.errno not in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                    raise
                time.sleep(0.1)
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle, fcntl.LOCK_UN)


def enclosing_extent(bbox, step=0.1):
    """Outward grid-snapped acquisition extent; never shrink reference support.

    A single enclosing extent avoids mosaicking independently unwrapped products.
    step=0 keeps exact extents for controlled comparisons.
    """
    if not step:
        return tuple(bbox)
    if not 0 < step <= 1:
        raise ValueError("Acquisition grid step must be between 0 and 1 degree")
    w, s, e, n = bbox
    if not (-180 <= w < e <= 180 and -90 <= s < n <= 90):
        raise ValueError("Wrapped or invalid bounding box is not supported")
    return (max(-180, round(math.floor(w / step + 1e-10) * step, 8)),
            max(-90, round(math.floor(s / step + 1e-10) * step, 8)),
            min(180, round(math.ceil(e / step - 1e-10) * step, 8)),
            min(90, round(math.ceil(n / step - 1e-10) * step, 8)))


def crop_native(clip, bbox):
    """Match Harmony's interior native-pixel window; reject incomplete grids.

    Harmony's projected subset excludes boundary pixels straddling the projected
    bounds. Outward rounding moves the multilook origin and changes measurements.
    """
    from affine import Affine
    from rasterio.warp import transform_bounds
    from rasterio.windows import Window, from_bounds, transform
    tf = Affine(*clip["tf"])
    if tf.b or tf.d or tf.a <= 0 or tf.e >= 0:
        return None
    bounds = transform_bounds("EPSG:4326", clip["crs"], *bbox, densify_pts=21)
    win = from_bounds(*bounds, transform=tf)
    # Ignore floating point round-off at exact pixel edges.
    x0, y0 = math.ceil(win.col_off - 1e-7), math.ceil(win.row_off - 1e-7)
    x1 = math.floor(win.col_off + win.width + 1e-7)
    y1 = math.floor(win.row_off + win.height + 1e-7)
    h, w = clip["phase"].shape
    if x0 < 0 or y0 < 0 or x1 > w or y1 > h or x1 <= x0 or y1 <= y0:
        return None
    result = {k: (clip[k][y0:y1, x0:x1].copy() if clip.get(k) is not None else None)
              for k in ("phase", "coh", "cc", "incidence")}
    result.update(tf=tuple(transform(Window(x0, y0, x1-x0, y1-y0), tf))[:6], crs=clip["crs"])
    # Harmony also masks pixels outside the original geographic rectangle.
    # Its projected envelope alone includes extra corner pixels; including those
    # would change coherence fractions and multilook means near the boundary.
    import numpy as np
    from pyproj import Transformer
    yy, xx = np.indices((y1-y0, x1-x0))
    grid = Affine(*result["tf"])
    lon, lat = Transformer.from_crs(clip["crs"], "EPSG:4326", always_xy=True).transform(
        grid.c + (xx + .5) * grid.a, grid.f + (yy + .5) * grid.e)
    inside = (lon >= bbox[0]) & (lat >= bbox[1]) & (lon <= bbox[2]) & (lat <= bbox[3])
    for key in ("phase", "coh", "cc", "incidence"):
        if result[key] is not None:
            result[key][~inside] = 0 if key == "cc" else np.nan
    return result


class ExtentIndex:
    def __init__(self, root: Path):
        self.root = root
        self.path = root / "extent_index.sqlite3"
        with closing(sqlite3.connect(self.path, timeout=30)) as db, db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("CREATE TABLE IF NOT EXISTS extents "
                       "(identity TEXT, filename TEXT PRIMARY KEY, west REAL, south REAL, east REAL, north REAL)")
            db.execute("CREATE INDEX IF NOT EXISTS extents_identity ON extents(identity)")

    def register(self, identity, path, bbox):
        with closing(sqlite3.connect(self.path, timeout=30)) as db, db:
            db.execute("INSERT OR REPLACE INTO extents VALUES (?,?,?,?,?,?)",
                       (identity, path.name, *bbox))

    def candidates(self, identity, bbox):
        w, s, e, n = bbox
        with closing(sqlite3.connect(self.path, timeout=30)) as db:
            rows = db.execute("SELECT filename FROM extents WHERE identity=? "
                              "AND west<=? AND south<=? AND east>=? AND north>=? "
                              "ORDER BY (east-west)*(north-south)", (identity, w, s, e, n)).fetchall()
        return [self.root / row[0] for row in rows if (self.root / row[0]).is_file()]


def append_event(path, event):
    if path is None:
        return
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with request_lock(path.with_suffix(".lock")):
        with path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"at_unix": time.time(), **event}) + "\n")
