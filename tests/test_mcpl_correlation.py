"""
Regression tests for the MCPL phase-space position-angle (Twiss) correlation.

Guards against issue #72: the transverse position offsets used to be applied in the
global x/y axes while the angular offsets were applied in the local beam basis (t1/t2).
For the -Z beam direction the local basis has t1 = -x_hat, which inverted the X-plane
position-angle correlation only -- so a symmetric focusing beam model converged in Y but
diverged in X. The fix applies the position offsets in the same t1/t2 basis as the angles.
"""

import numpy as np
import pytest

from dicomexport.export_mcpl import (
    FieldSampler,
    BeamCache,
    _make_transverse_basis_from_v,
    _chol2_psd,
    _sample_mcpl_buffer_fused_numpy,
    _sample_mcpl_buffer_fused,
)

_REC_DTYPE = np.dtype([
    ("x", "<f4"), ("y", "<f4"), ("z", "<f4"),
    ("fp1", "<f4"), ("fp2", "<f4"), ("ekin_signed", "<f4"),
    ("time", "<f4"), ("pdg", "<i4"),
])


def _unpack_dir(fp1, fp2, ek):
    """Invert the adaptive-projection packing used by export_mcpl."""
    fp1 = np.asarray(fp1, dtype=np.float64)
    fp2 = np.asarray(fp2, dtype=np.float64)
    ek = np.asarray(ek, dtype=np.float64)
    ux = np.empty_like(fp1)
    uy = np.empty_like(fp1)
    uz = np.empty_like(fp1)

    m1 = np.abs(fp1) > 1.0                    # fp1 = 1/uz  (x dominant)
    m2 = (~m1) & (np.abs(fp2) > 1.0)          # fp2 = 1/uz  (y dominant)
    m0 = ~(m1 | m2)                           # fp1=ux, fp2=uy (z dominant)

    ux[m0] = fp1[m0]
    uy[m0] = fp2[m0]
    uz[m0] = np.sqrt(np.maximum(0.0, 1.0 - fp1[m0]**2 - fp2[m0]**2)) * np.sign(ek[m0])

    uz[m1] = 1.0 / fp1[m1]
    uy[m1] = fp2[m1]
    ux[m1] = np.sqrt(np.maximum(0.0, 1.0 - uy[m1]**2 - uz[m1]**2)) * np.sign(ek[m1])

    uz[m2] = 1.0 / fp2[m2]
    ux[m2] = fp1[m2]
    uy[m2] = np.sqrt(np.maximum(0.0, 1.0 - ux[m2]**2 - uz[m2]**2)) * np.sign(ek[m2])

    return ux, uy, uz


def _symmetric_focusing_sampler(rho=-0.8, sx=3.0, sy=3.0, divx=0.006, divy=0.006,
                                z_plane=500.0):
    """A single on-axis spot with identical, focusing Twiss in X and Y."""
    v0 = np.array([0.0, 0.0, -1.0], dtype=np.float32)
    t1, t2 = _make_transverse_basis_from_v(v0)

    sampler = FieldSampler(
        idxE=np.array([0], dtype=np.uint16),
        cum_n=np.array([1.0], dtype=np.float64),
        total_n=1.0,
        xbm=np.array([0.0], dtype=np.float32),
        ybm=np.array([0.0], dtype=np.float32),
        v0=v0.reshape(1, 3),
        t1=np.asarray(t1, dtype=np.float32).reshape(1, 3),
        t2=np.asarray(t2, dtype=np.float32).reshape(1, 3),
        z_plane=z_plane,
        Enom=np.array([100.0], dtype=np.float32),
        Emean=np.array([100.0], dtype=np.float32),
        Esig=np.array([1.0], dtype=np.float32),
    )
    Lx = _chol2_psd(sx * sx, divx * divx, rho * sx * divx).astype(np.float32)
    Ly = _chol2_psd(sy * sy, divy * divy, rho * sy * divy).astype(np.float32)
    cache = BeamCache(Lx=Lx.reshape(1, 2, 2), Ly=Ly.reshape(1, 2, 2))
    return sampler, cache


def _drift_to_isocenter(buf):
    """Decode a record buffer and drift every particle from its plane to z=0."""
    rec = np.frombuffer(buf, dtype=_REC_DTYPE)
    x, y, z = rec["x"].astype(np.float64), rec["y"].astype(np.float64), rec["z"].astype(np.float64)
    ux, uy, uz = _unpack_dir(rec["fp1"], rec["fp2"], rec["ekin_signed"])
    t = (0.0 - z) / uz
    return x, y, x + t * ux, y + t * uy


def test_symmetric_beam_converges_symmetrically():
    """A symmetric focusing beam model must converge equally in X and Y (issue #72)."""
    sampler, cache = _symmetric_focusing_sampler()
    rng = np.random.default_rng(0)
    buf = _sample_mcpl_buffer_fused_numpy(sampler, cache, 200_000, rng=rng)
    x0, y0, xi, yi = _drift_to_isocenter(buf)

    sx_plane, sy_plane = x0.std(), y0.std()
    sx_iso, sy_iso = xi.std(), yi.std()

    # Both planes focus (a negative upstream correlation converges downstream)...
    assert sx_iso < sx_plane, f"X should converge: {sx_plane:.3f} -> {sx_iso:.3f} mm"
    assert sy_iso < sy_plane, f"Y should converge: {sy_plane:.3f} -> {sy_iso:.3f} mm"
    # ...and, being symmetric, focus by the same amount.
    assert sx_iso == pytest.approx(sy_iso, rel=0.03)


def _decode(buf):
    rec = np.frombuffer(buf, dtype=_REC_DTYPE)
    ux, uy, uz = _unpack_dir(rec["fp1"], rec["fp2"], rec["ekin_signed"])
    return dict(x=rec["x"].astype(np.float64), y=rec["y"].astype(np.float64),
                z=rec["z"].astype(np.float64), ux=ux, uy=uy, uz=uz)


def test_rotx180_is_rigid_rotation():
    """rotx180 must flip the beam to +Z travel and Y sign, preserving beam optics (#71)."""
    sampler, cache = _symmetric_focusing_sampler()
    a = _decode(_sample_mcpl_buffer_fused_numpy(
        sampler, cache, 100_000, rng=np.random.default_rng(7), rot180x=False))
    b = _decode(_sample_mcpl_buffer_fused_numpy(
        sampler, cache, 100_000, rng=np.random.default_rng(7), rot180x=True))

    # Same RNG seed -> identical underlying draws, then a deterministic 180-deg-about-X:
    # (x,y,z)->(x,-y,-z) and (ux,uy,uz)->(ux,-uy,-uz).
    assert np.allclose(b["x"], a["x"])
    assert np.allclose(b["y"], -a["y"])
    assert np.allclose(b["z"], -a["z"])
    assert np.allclose(b["ux"], a["ux"], atol=1e-6)
    assert np.allclose(b["uy"], -a["uy"], atol=1e-6)
    assert np.allclose(b["uz"], -a["uz"], atol=1e-6)

    # Beam now travels toward +Z from a source at -D.
    assert b["uz"].mean() > 0.99
    assert b["z"].mean() == pytest.approx(-a["z"].mean(), rel=1e-6)

    # Optics preserved: drift to isocenter (z=0) still converges by the same amount.
    t = (0.0 - b["z"]) / b["uz"]
    xi, yi = b["x"] + t * b["ux"], b["y"] + t * b["uy"]
    assert xi.std() < b["x"].std()
    assert yi.std() < b["y"].std()
    assert xi.std() == pytest.approx(yi.std(), rel=0.03)


def test_scalar_and_numpy_paths_agree():
    """The reference scalar path must reproduce the vectorized path's behaviour."""
    sampler, cache = _symmetric_focusing_sampler()
    x0n, y0n, xin, yin = _drift_to_isocenter(
        _sample_mcpl_buffer_fused_numpy(sampler, cache, 100_000, rng=np.random.default_rng(1)))
    x0s, y0s, xis, yis = _drift_to_isocenter(
        _sample_mcpl_buffer_fused(sampler, cache, 100_000, rng=np.random.default_rng(1)))

    # Same statistical convergence in both implementations (independent RNG draws).
    assert xin.std() == pytest.approx(xis.std(), rel=0.05)
    assert yin.std() == pytest.approx(yis.std(), rel=0.05)
    assert xis.std() < x0s.std()
