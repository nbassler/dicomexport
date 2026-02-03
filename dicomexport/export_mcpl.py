"""
MCPL phase-space generator for scanned proton spots.

- Samples spot indices proportional to MU
- Samples transverse phase space from beam model (Gaussian with covariances)
- Applies scanning by using per-spot central ray basis (ex,ey,ez)
- Writes MCPL records in buffered chunks
"""

from __future__ import annotations

import logging
import struct
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from dicomexport.__version__ import __version__
from dicomexport.beam_model import BeamModel
from dicomexport.model_plan import Plan, Field

logger = logging.getLogger(__name__)

# MCPL particle record:
# x,y,z, fp1,fp2, ekin_signed, time, pdg(int32)  -> 7 floats + 1 int32 = 32 bytes
_particle_struct = struct.Struct("<fff fff f i")

PDG_PROTON = 2212

L2 = np.ndarray
R3 = np.ndarray


# ---- dataclasses ----
@dataclass(frozen=True)
class FieldSampler:
    idxE: np.ndarray
    cumw: np.ndarray
    total: float

    xbm: np.ndarray
    ybm: np.ndarray

    v0: np.ndarray         # (N,3) float32
    t1: np.ndarray         # (N,3) float32
    t2: np.ndarray         # (N,3) float32

    z_plane: float

    Enom: np.ndarray
    Emean: np.ndarray
    Esig: np.ndarray


@dataclass(frozen=True)
class BeamCache:
    Lx: np.ndarray         # (K,2,2) float32
    Ly: np.ndarray         # (K,2,2) float32


# ---- public API ----
def generate_mcpl_file(

    plan: Plan,
    beam_model: BeamModel,
    output_path: str,
    *,
    field_list: list[int] | None = None,
    num_primaries: int = int(1e7),  # default 10 million particles to generate
    buffer_size: int = 1 << 20,  # approx 1 million particles for buffered writes
    rng_seed: int | None = None,
) -> None:
    """
    Generate an MCPL (Monte Carlo Particle List) file for a given treatment plan.

    This function processes the fields of a treatment plan, simulates particle
    trajectories using a beam model, and writes the results to an MCPL file. The
    output file can be customized with various parameters, including the number
    of particles to generate, buffer size for writing, and random number generator
    seed.

    Args:
        plan (Plan): The treatment plan containing fields to process.
        beam_model (BeamModel): The beam model used for particle simulation.
        output_path (str): The base path for the output MCPL file. The suffix will
            be enforced as ".mcpl".
        field_list (list[int] | None, optional): A list of field indices to process.
            If None, all fields in the plan will be processed. Defaults to None.
        num_primaries (int, optional): The total number of primary particles to
            generate. Defaults to 10 million (1e7).
        buffer_size (int, optional): The buffer size for writing particles to the
            file, in number of particles. Defaults to approximately 1 million
            particles (1 << 20).
        rng_seed (int | None, optional): The seed for the random number generator.
            If None, a random seed will be used. Defaults to None.

    Returns:
        None

    Raises:
        ValueError: If the output path is invalid or if the field list contains
            invalid indices.

    Notes:
        - The function enforces the ".mcpl" suffix for the output file.
        - Progress is printed to the console during particle generation.
        - Each field in the plan is processed and written to a separate MCPL file
          with a suffix indicating the field number.
    """

    rng = np.random.default_rng(rng_seed)
    header = _mcpl_header(num_primaries)

    fields = plan.fields if field_list is None else [plan.fields[i - 1] for i in field_list]

    # enforce suffix once
    suffix = Path(output_path).suffix
    if suffix.lower() != ".mcpl":
        logger.warning("Output path suffix is not .mcpl, changing it to .mcpl")
        suffix = ".mcpl"
    base = Path(output_path).with_suffix(suffix)

    for i, field in enumerate(fields, start=1):
        logger.info("Processing field %02d: '%s'", i, field.name)

        sampler = _prepare_field_sampler(field, beam_model)
        cache = _prewarm_beam_cache(sampler, beam_model)

        output_path_field = base.with_name(f"{base.stem}_field{field.number:02}{base.suffix}")
        logger.info("Writing MCPL file: %s", output_path_field)

        with open(output_path_field, "wb") as f:
            f.write(header)

            wrote_count = 0
            while wrote_count < num_primaries:
                n = min(buffer_size, num_primaries - wrote_count)
                buf = _sample_mcpl_buffer_fused(sampler, cache, n, rng=rng)
                f.write(buf)
                wrote_count += n
                rprog = (wrote_count * 100) / num_primaries
                print(f"\rWrote {wrote_count}/{num_primaries} particles ({rprog:.1f}%)", end="", flush=True)

    print()  # newline after progress


# ---- preparation ----
def _prepare_field_sampler(field: Field, bm: BeamModel) -> FieldSampler:
    Enom_list: list[float] = []
    Emean_list: list[float] = []
    Esig_list: list[float] = []
    energy_to_bin: dict[float, int] = {}

    idxE_list: list[int] = []
    w_list: list[float] = []

    xbm_list: list[float] = []
    ybm_list: list[float] = []
    v0_list: list[np.ndarray] = []
    t1_list: list[np.ndarray] = []
    t2_list: list[np.ndarray] = []

    D = float(bm.beam_model_position)
    if D <= 0.0:
        raise ValueError(f"Beam model position must be positive (upstream). Got {D}")
    z_plane = D
    logger.info("Beam model position D = %+.1f mm", D)

    dx = float(field.lateral_spreading_device_distanceX)
    dy = float(field.lateral_spreading_device_distanceY)

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

            v0 = np.array([-x_bm, -y_bm, -D], dtype=float)
            v0 /= np.linalg.norm(v0)

            t1, t2 = _make_transverse_basis_from_v(v0)

            idxE_list.append(k)
            w_list.append(w)

            xbm_list.append(x_bm)
            ybm_list.append(y_bm)
            v0_list.append(v0)
            t1_list.append(t1)
            t2_list.append(t2)

    if not w_list:
        raise ValueError(f"Field {field.name} has no spots with positive MU.")

    w = np.asarray(w_list, dtype=np.float64)
    cumw = np.cumsum(w)
    total = float(cumw[-1])

    K = len(Enom_list)
    idx_dtype = np.uint16 if K < 65535 else np.int32
    idxE = np.asarray(idxE_list, dtype=idx_dtype)

    xbm = np.asarray(xbm_list, dtype=np.float32)
    ybm = np.asarray(ybm_list, dtype=np.float32)
    v0 = np.asarray(v0_list, dtype=np.float32)
    t1 = np.asarray(t1_list, dtype=np.float32)
    t2 = np.asarray(t2_list, dtype=np.float32)

    Enom = np.asarray(Enom_list, dtype=np.float32)
    Emean = np.asarray(Emean_list, dtype=np.float32)
    Esig = np.asarray(Esig_list, dtype=np.float32)

    return FieldSampler(
        idxE=idxE,
        cumw=cumw,
        total=total,
        xbm=xbm,
        ybm=ybm,
        v0=v0,
        t1=t1,
        t2=t2,
        z_plane=z_plane,
        Enom=Enom,
        Emean=Emean,
        Esig=Esig,
    )


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

        # the beam model holdes correlation coefficients, not covariances
        rho_x = float(bm.f_corx(Enom))
        rho_y = float(bm.f_cory(Enom))

        covx = rho_x * sx * divx
        covy = rho_y * sy * divy

        Lx[k] = _chol2_psd(sx * sx, divx * divx, covx).astype(np.float32)
        Ly[k] = _chol2_psd(sy * sy, divy * divy, covy).astype(np.float32)

    return BeamCache(Lx=Lx, Ly=Ly)


def _make_transverse_basis_from_v(v: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    up = np.array([0.0, 1.0, 0.0], dtype=float)
    if np.isclose(abs(float(np.dot(up, v))), 1.0):
        up = np.array([1.0, 0.0, 0.0], dtype=float)
    t1 = np.cross(up, v)
    t1 /= np.linalg.norm(t1)
    t2 = np.cross(v, t1)
    t2 /= np.linalg.norm(t2)
    return t1, t2


# ---- sampling hot path ----
def _sample_mcpl_buffer_fused(
    sampler: FieldSampler,
    cache: BeamCache,
    n: int,
    *,
    rng: np.random.Generator,
    pdg: int = PDG_PROTON,
) -> bytearray:

    u = rng.random(n) * sampler.total
    idxs = np.searchsorted(sampler.cumw, u, side="right").astype(np.int64, copy=False)

    Z = rng.standard_normal((n, 5), dtype=np.float32)

    out = bytearray(n * _particle_struct.size)
    off = 0
    z_plane = float(sampler.z_plane)

    for j, idx in enumerate(idxs):
        k = int(sampler.idxE[idx])
        Lx = cache.Lx[k]
        Ly = cache.Ly[k]

        z0, z1, z2, z3, zE = Z[j]

        x_local = Lx[0, 0] * z0
        xp = Lx[1, 0] * z0 + Lx[1, 1] * z1
        y_local = Ly[0, 0] * z2
        yp = Ly[1, 0] * z2 + Ly[1, 1] * z3

        xg = float(sampler.xbm[idx] + x_local)
        yg = float(sampler.ybm[idx] + y_local)
        zg = z_plane

        v0 = sampler.v0[idx]
        t1 = sampler.t1[idx]
        t2 = sampler.t2[idx]

        vx = float(v0[0] + xp * t1[0] + yp * t2[0])
        vy = float(v0[1] + xp * t1[1] + yp * t2[1])
        vz = float(v0[2] + xp * t1[2] + yp * t2[2])

        invn = 1.0 / np.sqrt(vx * vx + vy * vy + vz * vz)
        vx *= invn
        vy *= invn
        vz *= invn

        Emean = float(sampler.Emean[k])
        Esig = float(sampler.Esig[k])
        ekin = Emean + Esig * float(zE)
        if ekin < 0.0:
            ekin = 0.0

        fp1, fp2, ekin_signed = _mcpl_app_pack(vx, vy, vz, ekin)

        _particle_struct.pack_into(
            out, off,
            np.float32(xg), np.float32(yg), np.float32(zg),
            np.float32(fp1), np.float32(fp2), np.float32(ekin_signed),
            np.float32(0.0),
            int(pdg),
        )
        off += _particle_struct.size

    return out


def _mcpl_app_pack(ux: float, uy: float, uz: float, ekin: float) -> tuple[float, float, float]:
    """
    Adaptive Projection Packing compatible with the mcpl python reader.
    Given a unit direction (ux,uy,uz) and kinetic energy ekin (float),
    return (fp1, fp2, ekin_signed) according to the APP scheme.
    """
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

    return fp1, fp2, ekin_signed


# ---- helpers ----
def _chol2_psd(a: float, b: float, c: float) -> L2:
    """
    Given 2x2 PSD matrix [[a, c],
                          [c, b]],
    return its Cholesky factor L such that LL^T = PSD.
    """
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


def _mcpl_header(num_particles: int) -> bytes:
    """
    Generate MCPL file header for given number of particles.
    """
    source_name = f"dicomexport {__version__}".encode("ascii")

    header = (
        b"MCPL"
        + b"003"
        + b"L"
        + struct.pack("<Q", num_particles)
        + struct.pack("<I", 0)      # no comments
        + struct.pack("<I", 0)      # no blobs
        + struct.pack("<I", 0)      # no user flags
        + struct.pack("<I", 0)      # no polarization
        + struct.pack("<I", 1)      # single precision
        + struct.pack("<i", 0)      # all particles have PDG code
        + struct.pack("<I", 32)     # particle length
        + struct.pack("<I", 1)      # universal weight
        + struct.pack("<d", 1.0)    # universal weight value
        + struct.pack("<I", len(source_name))
        + source_name
    )
    return header
