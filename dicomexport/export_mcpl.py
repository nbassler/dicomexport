"""
MCPL phase-space generator for scanned proton spots.

- Samples spot indices proportional to MU
- Samples transverse phase space from beam model (Gaussian with covariances)
- Applies spot scanning rotation
- Writes MCPL records in buffered chunks
"""

from __future__ import annotations

import logging
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Tuple

import numpy as np

from dicomexport.__version__ import __version__
from dicomexport.beam_model import BeamModel
from dicomexport.model_plan import Plan, Field

logger = logging.getLogger(__name__)


_particle_struct = struct.Struct("<fff fff f i")  # x y z, fp1 fp2 ekin, time, pdg (int32)

L2 = np.ndarray  # (2,2)
R3 = np.ndarray  # (3,3)
CovCache = Dict[float, Tuple[L2, L2]]  # energy_key -> (Lx, Ly)


# ---- dataclasses ----
@dataclass(frozen=True)
class FieldSampler:
    idxE: np.ndarray      # (N,) uint16/int32
    cumw: np.ndarray      # (N,) float64
    total: float
    R_spot: np.ndarray    # (N,3,3) float32

    Enom: np.ndarray      # (K,) float32
    Emean: np.ndarray     # (K,) float32
    Esig: np.ndarray      # (K,) float32


@dataclass(frozen=True)
class BeamCache:
    Lx: np.ndarray        # (K,2,2) float32
    Ly: np.ndarray        # (K,2,2) float32


def generate_mcpl_file(
    plan: Plan,
    beam_model: BeamModel,
    output_path: str,
    *,
    field_list: list[int] | None = None,
    num_primaries: int = int(1e8),
    buffer_size: int = 1 << 20,
    rng_seed: int | None = None,
) -> None:
    rng = np.random.default_rng(rng_seed)
    header = _mcpl_header(num_primaries)

    fields = plan.fields if field_list is None else [plan.fields[i - 1] for i in field_list]

    # enforce suffix once (no need to repeat per field)
    suffix = Path(output_path).suffix
    if suffix.lower() != ".mcpl":
        logger.warning("Output path suffix is not .mcpl, changing it to .mcpl")
        suffix = ".mcpl"

    base = Path(output_path).with_suffix(suffix)

    for field in fields:
        logger.info("Processing field: %s", field.name)

        sampler = _prepare_field_sampler(field, beam_model)
        cache = _prewarm_beam_cache(sampler, beam_model)

        output_path_field = base.with_name(f"{base.stem}_field{field.number:02}{base.suffix}")
        logger.info("Writing MCPL file: %s", output_path_field)

        with open(output_path_field, "wb") as f:
            f.write(header)

            written = 0
            while written < num_primaries:
                n = min(buffer_size, num_primaries - written)

                buf = _sample_mcpl_buffer_fused(
                    sampler,
                    cache,
                    n,
                    rng=rng,
                )
                f.write(buf)

                written += n
                print(f"\rWritten {written}/{num_primaries} particles", end="", flush=True)


def _prepare_field_sampler(field: Field, bm: BeamModel) -> FieldSampler:
    Enom_list: list[float] = []
    Emean_list: list[float] = []
    Esig_list: list[float] = []
    energy_to_bin: dict[float, int] = {}

    idxE_list: list[int] = []
    w_list: list[float] = []
    R_list: list[np.ndarray] = []

    D = float(bm.beam_model_position)
    dx = field.lateral_spreading_device_distanceX
    dy = field.lateral_spreading_device_distanceY

    for layer in field.layers:
        Enom = float(layer.energy_nominal)

        k = energy_to_bin.get(Enom)
        if k is None:
            k = len(Enom_list)
            energy_to_bin[Enom] = k
            Enom_list.append(Enom)
            Emean_list.append(float(bm.f_e(Enom)))
            Esig_list.append(float(bm.f_espread(Enom)))

        for s in layer.spots:
            w = float(s.mu)
            if w <= 0.0:
                continue

            x_iso = float(s.x)
            y_iso = float(s.y)

            x_bm = x_iso * (dx - D) / dx
            y_bm = y_iso * (dy - D) / dy

            d = np.array([x_bm, y_bm, -D], dtype=float)
            d /= np.linalg.norm(d)

            idxE_list.append(k)
            w_list.append(w)
            R_list.append(_rotation_from_direction(d))

    if not w_list:
        raise ValueError(f"Field {field.name} has no spots with positive MU.")

    w = np.asarray(w_list, dtype=np.float64)
    cumw = np.cumsum(w)
    total = float(cumw[-1])

    K = len(Enom_list)
    idx_dtype = np.uint16 if K < 65535 else np.int32
    idxE = np.asarray(idxE_list, dtype=idx_dtype)
    R_spot = np.asarray(R_list, dtype=np.float32)

    Enom = np.asarray(Enom_list, dtype=np.float32)
    Emean = np.asarray(Emean_list, dtype=np.float32)
    Esig = np.asarray(Esig_list, dtype=np.float32)

    return FieldSampler(idxE=idxE, cumw=cumw, total=total, R_spot=R_spot, Enom=Enom, Emean=Emean, Esig=Esig)


def _sample_mcpl_buffer_fused(
    sampler: FieldSampler,
    cache: BeamCache,
    n: int,
    *,
    rng: np.random.Generator,
    pdg: int = 2212,
) -> bytearray:
    u = rng.random(n) * sampler.total
    idxs = np.searchsorted(sampler.cumw, u, side="right").astype(np.int64, copy=False)

    Z = rng.standard_normal((n, 5), dtype=np.float32)

    out = bytearray(n * _particle_struct.size)
    off = 0

    for j, idx in enumerate(idxs):
        k = int(sampler.idxE[idx])

        Lx = cache.Lx[k]
        Ly = cache.Ly[k]

        z0, z1, z2, z3, zE = Z[j]

        x_local = Lx[0, 0] * z0
        xp = Lx[1, 0] * z0 + Lx[1, 1] * z1
        y_local = Ly[0, 0] * z2
        yp = Ly[1, 0] * z2 + Ly[1, 1] * z3

        # local direction
        vx_l = -xp
        vy_l = -yp
        vz_l = -1.0
        invnorm = 1.0 / np.sqrt(vx_l*vx_l + vy_l*vy_l + 1.0)
        vx_l *= invnorm
        vy_l *= invnorm
        vz_l *= invnorm

        R = sampler.R_spot[idx]

        xg = R[0, 0]*x_local + R[0, 1]*y_local
        yg = R[1, 0]*x_local + R[1, 1]*y_local
        zg = R[2, 0]*x_local + R[2, 1]*y_local

        vx = R[0, 0]*vx_l + R[0, 1]*vy_l + R[0, 2]*vz_l
        vy = R[1, 0]*vx_l + R[1, 1]*vy_l + R[1, 2]*vz_l
        vz = R[2, 0]*vx_l + R[2, 1]*vy_l + R[2, 2]*vz_l

        invn = 1.0 / np.sqrt(vx*vx + vy*vy + vz*vz)
        vx *= invn
        vy *= invn
        vz *= invn

        # energy sampling:
        Emean = float(sampler.Emean[k])
        Esig = float(sampler.Esig[k])

        ekin = Emean + Esig * zE
        if ekin < 0.0:
            ekin = 0.0

        # APP packing:
        ux, uy, uz = float(vx), float(vy), float(vz)
        ax, ay, az = abs(ux), abs(uy), abs(uz)

        inv_uz = (1.0 / uz) if uz != 0.0 else float(np.inf)

        if az >= ax and az >= ay:
            fp1 = ux
            fp2 = uy
            ekin_signed = -ekin if uz < 0.0 else ekin
        elif ax >= ay and ax > az:
            fp1 = inv_uz
            fp2 = uy
            ekin_signed = -ekin if ux < 0.0 else ekin
        else:
            fp1 = ux
            fp2 = inv_uz
            ekin_signed = -ekin if uy < 0.0 else ekin

        _particle_struct.pack_into(
            out, off,
            np.float32(xg), np.float32(yg), np.float32(zg),
            np.float32(fp1), np.float32(fp2), np.float32(ekin_signed),
            np.float32(0.0),
            int(pdg),
        )
        off += _particle_struct.size

    return out


def _prewarm_beam_cache(sampler: FieldSampler, bm: BeamModel) -> BeamCache:
    K = sampler.Enom.shape[0]
    Lx = np.empty((K, 2, 2), dtype=np.float32)
    Ly = np.empty((K, 2, 2), dtype=np.float32)

    for k in range(K):
        Enom = float(sampler.Enom[k])

        sx = float(bm.f_sx(Enom))
        sy = float(bm.f_sy(Enom))
        divx = float(bm.f_divx(Enom))
        divy = float(bm.f_divy(Enom))
        covx = float(bm.f_covx(Enom))
        covy = float(bm.f_covy(Enom))

        Lx[k] = _chol2_psd(sx*sx, divx*divx, covx).astype(np.float32)
        Ly[k] = _chol2_psd(sy*sy, divy*divy, covy).astype(np.float32)

    return BeamCache(Lx=Lx, Ly=Ly)


def _chol2_psd(a: float, b: float, c: float) -> L2:
    if a < 0.0:
        a = 0.0
    if b < 0.0:
        b = 0.0
    if a == 0.0:
        return np.array([[0.0, 0.0],
                         [0.0, np.sqrt(b)]], dtype=float)
    L00 = np.sqrt(a)
    L10 = c / L00
    L11_sq = b - (c * c) / a
    if L11_sq < 0.0:
        L11_sq = 0.0
    return np.array([[L00, 0.0],
                     [L10, np.sqrt(L11_sq)]], dtype=float)


def _rotation_from_direction(d: np.ndarray, up_hint: np.ndarray | None = None) -> R3:
    d = np.asarray(d, dtype=float)
    d /= np.linalg.norm(d)

    up = np.array([0.0, 1.0, 0.0], dtype=float) if up_hint is None else np.asarray(up_hint, dtype=float)
    if abs(float(np.dot(up, d))) > 0.99:
        up = np.array([1.0, 0.0, 0.0], dtype=float)

    ex = np.cross(up, d)
    ex /= np.linalg.norm(ex)
    ey = np.cross(d, ex)
    ez = d
    return np.column_stack([ex, ey, ez])


def _mcpl_header(num_particles: int) -> bytes:
    """
    Create MCPL binary file header.

    Args:
        num_particles: Total number of particles.

    Returns:
        Byte string of the MCPL header.
    """

    source_name = f"dicomexport {__version__}".encode('ascii')

    header = (
        b"MCPL"  # Magic number
        b"003"   # Version
        b"L"     # Little endian
        + struct.pack("<Q", num_particles)  # Total particles
        + struct.pack("<I", 0)  # No custom comments
        + struct.pack("<I", 0)  # No custom binary blobs
        + struct.pack("<I", 0)  # No user flags
        + struct.pack("<I", 0)  # No polarization
        + struct.pack("<I", 1)  # Single precision
        + struct.pack("<i", 0)  # All particles have PDG code
        + struct.pack("<I", 32)  # Data length per particle
        + struct.pack("<I", 1)  # Universal weight
        + struct.pack("<d", 1.0)  # Universal weight value
        + struct.pack("<I", len(source_name))  # Source name length
        + source_name  # source name as bytes
    )

    return header
