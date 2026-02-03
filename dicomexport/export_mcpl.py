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


L2 = np.ndarray
R3 = np.ndarray


# ---- dataclasses ----
@dataclass(frozen=True)
class FieldSampler:
    # per-spot sampling
    idxE: np.ndarray       # (N,) uint16/int32 energy-bin index per spot
    cumw: np.ndarray       # (N,) float64 cumulative MU weights
    total: float           # total MU

    # per-spot mean at beam-model plane
    xbm: np.ndarray        # (N,) float32
    ybm: np.ndarray        # (N,) float32

    # per-spot orthonormal basis (columns)
    ex: np.ndarray         # (N,3) float32
    ey: np.ndarray         # (N,3) float32
    ez: np.ndarray         # (N,3) float32  (central ray direction)

    # plane coordinate
    z_plane: float         # scalar (float), typically -D (mm)

    # per-energy-bin info (K bins)
    Enom: np.ndarray       # (K,) float32
    Emean: np.ndarray      # (K,) float32
    Esig: np.ndarray       # (K,) float32


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

    ex_list: list[np.ndarray] = []
    ey_list: list[np.ndarray] = []
    ez_list: list[np.ndarray] = []

    D = float(bm.beam_model_position)  # mm upstream of isocenter (positive number)
    z_plane = D                        # isocenter at z=0, upstream of isocenter is positive z
    logger.info("Beam model position D = %+.1f mm", D)

    dx = float(field.lateral_spreading_device_distanceX)  # mm
    dy = float(field.lateral_spreading_device_distanceY)  # mm

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

            # mean spot center in beam-model plane (backproject from isocenter plane)
            x_bm = x_iso * (dx - D) / dx
            y_bm = y_iso * (dy - D) / dy

            # central ray direction (from point on plane to isocenter)
            # point on plane: (x_bm, y_bm, D); isocenter: (0,0,0)
            # vector to isocenter:
            ez = np.array([-x_bm, -y_bm, -D], dtype=float)
            ez /= np.linalg.norm(ez)

            ex, ey = _make_transverse_basis(ez)

            idxE_list.append(k)
            w_list.append(w)

            xbm_list.append(x_bm)
            ybm_list.append(y_bm)
            ex_list.append(ex)
            ey_list.append(ey)
            ez_list.append(ez)

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

    ex = np.asarray(ex_list, dtype=np.float32)  # (N,3)
    ey = np.asarray(ey_list, dtype=np.float32)
    ez = np.asarray(ez_list, dtype=np.float32)

    Enom = np.asarray(Enom_list, dtype=np.float32)
    Emean = np.asarray(Emean_list, dtype=np.float32)
    Esig = np.asarray(Esig_list, dtype=np.float32)

    return FieldSampler(
        idxE=idxE,
        cumw=cumw,
        total=total,
        xbm=xbm,
        ybm=ybm,
        ex=ex,
        ey=ey,
        ez=ez,
        z_plane=z_plane,
        Enom=Enom,
        Emean=Emean,
        Esig=Esig,
    )


def _make_transverse_basis(ez: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Given unit ez, return orthonormal ex, ey with ex ⟂ ez and ey = ez × ex."""
    up = np.array([0.0, 1.0, 0.0], dtype=float)
    if abs(float(np.dot(up, ez))) > 0.99:
        up = np.array([1.0, 0.0, 0.0], dtype=float)

    ex = np.cross(up, ez)
    ex /= np.linalg.norm(ex)
    ey = np.cross(ez, ex)
    return ex, ey


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

        Lx[k] = _chol2_psd(sx * sx, divx * divx, covx).astype(np.float32)
        Ly[k] = _chol2_psd(sy * sy, divy * divy, covy).astype(np.float32)

    return BeamCache(Lx=Lx, Ly=Ly)


# ---- sampling hot path ----
def _sample_mcpl_buffer_fused(
    sampler: FieldSampler,
    cache: BeamCache,
    n: int,
    *,
    rng: np.random.Generator,
    pdg: int = 2212,
) -> bytearray:
    # pick spots MU-weighted
    u = rng.random(n) * sampler.total
    idxs = np.searchsorted(sampler.cumw, u, side="right").astype(np.int64, copy=False)

    # z0,z1,z2,z3 for x/y phase space + zE for energy
    Z = rng.standard_normal((n, 5), dtype=np.float32)

    out = bytearray(n * _particle_struct.size)
    off = 0

    z_plane = float(sampler.z_plane)

    for j, idx in enumerate(idxs):
        k = int(sampler.idxE[idx])
        Lx = cache.Lx[k]
        Ly = cache.Ly[k]

        z0, z1, z2, z3, zE = Z[j]

        # local transverse phase space sample
        x_local = Lx[0, 0] * z0
        xp = Lx[1, 0] * z0 + Lx[1, 1] * z1
        y_local = Ly[0, 0] * z2
        yp = Ly[1, 0] * z2 + Ly[1, 1] * z3

        # basis at this spot
        ex = sampler.ex[idx]
        ey = sampler.ey[idx]
        ez = sampler.ez[idx]

        # ---- position pinned to plane z = -D ----
        # r = r0 + x_local*ex + y_local*ey   (with r0 = (x_bm, y_bm, z_plane))
        xg = float(sampler.xbm[idx]) + float(x_local * ex[0] + y_local * ey[0])
        yg = float(sampler.ybm[idx]) + float(x_local * ex[1] + y_local * ey[1])
        zg = z_plane

        # ---- direction ----
        # Interpret xp,yp as small angular deviations in the transverse basis
        # v = normalize(ez + xp*ex + yp*ey)
        vx = float(ez[0] + xp * ex[0] + yp * ey[0])
        vy = float(ez[1] + xp * ex[1] + yp * ey[1])
        vz = float(ez[2] + xp * ex[2] + yp * ey[2])

        invn = 1.0 / np.sqrt(vx * vx + vy * vy + vz * vz)
        vx *= invn
        vy *= invn
        vz *= invn

        # ---- energy sampling ----
        Emean = float(sampler.Emean[k])
        Esig = float(sampler.Esig[k])
        ekin = Emean + Esig * float(zE)
        if ekin < 0.0:
            ekin = 0.0

        # ---- MCPL APP packing (fp1, fp2, ekin_signed) ----
        fp1, fp2, ekin_signed = _mcpl_app_pack(vx, vy, vz, ekin)

        _particle_struct.pack_into(
            out, off,
            np.float32(xg), np.float32(yg), np.float32(zg),
            np.float32(fp1), np.float32(fp2), np.float32(ekin_signed),
            np.float32(0.0),   # time
            int(pdg),
        )
        off += _particle_struct.size

    return out


def _mcpl_app_pack(ux: float, uy: float, uz: float, ekin: float) -> tuple[float, float, float]:
    """Adaptive Projection Packing compatible with the mcpl python reader."""
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
