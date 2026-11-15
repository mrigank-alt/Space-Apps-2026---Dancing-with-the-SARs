"""Batched SBAS inversion grouped by identical valid-interferogram masks."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(slots=True)
class SbasResult:
    displacement_cm: np.ndarray  # time, y, x; first epoch is zero reference
    displacement_sigma_cm: np.ndarray
    velocity_cm_year: np.ndarray
    velocity_sigma_cm_year: np.ndarray
    residual_rms_cm: np.ndarray
    valid_pair_count: np.ndarray
    connected: np.ndarray


def invert_sbas(
    pair_displacement_cm: np.ndarray,
    pair_start: np.ndarray,
    pair_end: np.ndarray,
    epoch_days: np.ndarray,
    weights: np.ndarray,
    minimum_pairs: int = 3,
) -> SbasResult:
    """Invert pairwise LOS displacement to epochs with batched weighted least squares.

    All per-pixel solves are batched by a shared finite-pair mask. Disconnected or
    rank-deficient pair networks remain NaN. Pair weights should be inverse variance.
    """
    obs = np.asarray(pair_displacement_cm, dtype=np.float32)
    wgt = np.asarray(weights, dtype=np.float32)
    starts, ends = np.asarray(pair_start, int), np.asarray(pair_end, int)
    times = np.asarray(epoch_days, dtype=np.float64)
    if times.ndim != 1 or times.size < 2 or not np.all(np.isfinite(times)) or np.any(np.diff(times) <= 0):
        raise ValueError("epoch_days must contain at least two finite, strictly increasing epochs")
    if obs.ndim != 3 or wgt.shape != obs.shape:
        raise ValueError("displacements and weights must share shape (pair, y, x)")
    if starts.ndim != 1 or ends.ndim != 1 or len(starts) != obs.shape[0] or len(ends) != obs.shape[0]:
        raise ValueError("pair endpoint arrays must have one entry per interferogram")
    if starts.min(initial=0) < 0 or ends.max(initial=-1) >= times.size or np.any(ends <= starts):
        raise ValueError("pair endpoints must index increasing epochs")

    npair, height, width = obs.shape
    nparam = times.size - 1  # epoch zero is the explicit zero reference
    y = obs.reshape(npair, -1).T
    w = wgt.reshape(npair, -1).T
    valid = np.isfinite(y) & np.isfinite(w) & (w > 0)
    packed = np.packbits(valid, axis=1)
    patterns, inverse = np.unique(packed, axis=0, return_inverse=True)
    npx = y.shape[0]
    disp = np.full((times.size, npx), np.nan, np.float32)
    sigma = np.full_like(disp, np.nan)
    velocity = np.full(npx, np.nan, np.float32)
    velocity_sigma = np.full(npx, np.nan, np.float32)
    rms = np.full(npx, np.nan, np.float32)
    counts = valid.sum(axis=1).astype(np.uint16)
    connected = np.zeros(npx, bool)
    design = np.zeros((npair, nparam), np.float64)
    for i, (start, end) in enumerate(zip(starts, ends)):
        if start > 0:
            design[i, start - 1] -= 1.0
        if end > 0:
            design[i, end - 1] += 1.0

    for group_id, pattern in enumerate(patterns):
        pixels = np.flatnonzero(inverse == group_id)
        rows = np.flatnonzero(np.unpackbits(pattern)[:npair])
        if rows.size < max(minimum_pairs, nparam):
            continue
        a = design[rows]
        if np.linalg.matrix_rank(a) < nparam:
            continue
        yp = y[np.ix_(pixels, rows)].astype(np.float64)
        wp = w[np.ix_(pixels, rows)].astype(np.float64)
        normal = np.einsum("ri,pr,rj->pij", a, wp, a, optimize=True)
        try:
            cov_base = np.linalg.inv(normal)
        except np.linalg.LinAlgError:
            continue
        rhs = np.einsum("ri,pr,pr->pi", a, wp, yp, optimize=True)
        beta = np.einsum("pij,pj->pi", cov_base, rhs, optimize=True)
        residual = yp - beta @ a.T
        # A full-rank tree solves the epochs exactly but has no residual degrees
        # of freedom. Keep its point estimate, but report uncertainty as unknown.
        if rows.size > nparam:
            dof = rows.size - nparam
            variance = np.sum(wp * residual**2, axis=1) / dof
            cov = cov_base * variance[:, None, None]
        else:
            cov = np.full_like(cov_base, np.nan)
        full = np.column_stack((np.zeros(pixels.size), beta)).astype(np.float32)
        full_sigma = np.column_stack((np.zeros(pixels.size), np.sqrt(np.maximum(np.diagonal(cov, axis1=1, axis2=2), 0)))).astype(np.float32)
        disp[:, pixels] = full.T
        sigma[:, pixels] = full_sigma.T
        rms[pixels] = np.sqrt(np.mean(residual**2, axis=1)).astype(np.float32)
        connected[pixels] = True

        # Temporal trend WLS using propagated epoch displacement variances.
        x = (times - times[0]) / 365.25
        epoch_var = full_sigma.astype(np.float64) ** 2
        uncertainty_available = np.all(np.isfinite(epoch_var), axis=1)
        tw = np.divide(1.0, epoch_var, out=np.zeros_like(epoch_var), where=epoch_var > 1e-10)
        zero_noise = np.all(epoch_var <= 1e-10, axis=1)
        tw[zero_noise | ~uncertainty_available] = 1.0
        sw = tw.sum(axis=1)
        sx = (tw * x[None, :]).sum(axis=1)
        sy = (tw * full).sum(axis=1)
        sxx = (tw * x[None, :] ** 2).sum(axis=1)
        sxy = (tw * x[None, :] * full).sum(axis=1)
        den = sw * sxx - sx**2
        good = den > 0
        sl = np.divide(sw * sxy - sx * sy, den, out=np.full_like(den, np.nan), where=good)
        vel_var = np.divide(sw, den, out=np.full_like(den, np.nan), where=good)
        vel_var[zero_noise] = 0.0
        velocity[pixels] = sl.astype(np.float32)
        velocity_sigma[pixels] = np.where(uncertainty_available, np.sqrt(np.maximum(vel_var, 0)), np.nan).astype(np.float32)

    shape = (height, width)
    return SbasResult(
        displacement_cm=disp.reshape(times.size, *shape),
        displacement_sigma_cm=sigma.reshape(times.size, *shape),
        velocity_cm_year=velocity.reshape(shape),
        velocity_sigma_cm_year=velocity_sigma.reshape(shape),
        residual_rms_cm=rms.reshape(shape),
        valid_pair_count=counts.reshape(shape),
        connected=connected.reshape(shape),
    )
