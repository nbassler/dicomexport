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
import time

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
class FieldSampler:  # computed per field
    # these arrays have the length of the number of spots N in the field
    idxE: np.ndarray  # for each spot i, idxE[i] index which energy bin to use
    cum_n: np.ndarray  # cumulative particle numbers used for inverse-CDF sampling
    total_n: float  # total number of particles across all spots in the field (cum_n[-1])

    xbm: np.ndarray  # spot centers at beam model position  [mm]
    ybm: np.ndarray  # spot centers at beam model position  [mm]

    # unit vector giving the nominal direction of the spot central ray from beam model plane towards isocenter
    v0: np.ndarray         # (N,3) float32

    # two unit vectors orthonormal to v0, spanning the transverse plane perpendicular to the local beam direction.
    t1: np.ndarray         # (N,3) float32
    t2: np.ndarray         # (N,3) float32

    z_plane: float    # z position of the beam model plane [mm]

    # these arrays have the length of the number of unique energy bins (layers) K in the field
    Enom: np.ndarray  # nominal energy for each energy layer
    Emean: np.ndarray  # actial mean energy for each energy layer
    Esig: np.ndarray  # energy spread (1 sigma) for each energy layer


# per-field cache of Cholesky factors for the transverse 2D Gaussian phase-space in each plane.
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
    rot180x: bool = False,
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
        rot180x (bool, optional): If False (default), particles are emitted in the
            canonical IEC 61217 gantry/nozzle frame: source plane at +D, beam travelling
            toward -Z, isocenter at the origin. If True, the whole phase space is rigidly
            rotated 180 deg about X so the beam travels toward +Z (source at -D); this
            necessarily flips the sign of Y. Use it for downstream codes that expect a
            +Z-forward beam. It is a rigid rotation and preserves all beam optics.

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

    if rot180x:
        logger.info("MCPL frame: rotx180 -- beam travels toward +Z (source at -D), Y sign flipped.")
    else:
        logger.info("MCPL frame: iec -- beam travels toward -Z (source at +D), isocenter at origin.")

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
                t0 = time.perf_counter()
                # buf = _sample_mcpl_buffer_fused(sampler, cache, n, rng=rng)
                buf = _sample_mcpl_buffer_fused_numpy(sampler, cache, n, rng=rng, rot180x=rot180x)
                t1 = time.perf_counter()
                f.write(buf)
                t2 = time.perf_counter()
                logger.debug("Sampled and wrote %d particles in %.3f + %.3f s", n, t1 - t0, t2 - t1)
                wrote_count += n
                rprog = (wrote_count * 100) / num_primaries
                print(f"\rWrote {wrote_count}/{num_primaries} particles ({rprog:.1f}%)", end="", flush=True)

            print()  # newline after progress
            logger.info("Wrote MCPL file %s for %d particles", output_path_field, num_primaries)


# ---- preparation ----
def _prepare_field_sampler(field: Field, bm: BeamModel) -> FieldSampler:
    """
    Precalculate per-field sampling data structures.
    """
    logger.debug("Preparing field sampler for field '%s'", field.name)
    # for every energy layer in the field
    Enom_list: list[float] = []
    Emean_list: list[float] = []
    Esig_list: list[float] = []
    PpMU_list: list[float] = []  # protons per MU for this particular energy layer
    energy_to_bin: dict[float, int] = {}

    # for every spot in the field across all energy layers
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

    # Backprojection needs the source-to-axis distance. Keying this off
    # has_spreading_device meant RayStation PBS plans -- which write no lateral
    # spreading device but do carry VirtualSourceAxisDistances -- were silently
    # exported as a parallel beam (issue #79). Use the SAD the importer resolved;
    # it is only unset for formats that genuinely carry none (PLD, RST).
    dx, dy = (float(v) for v in field.sad)
    diverging = dx > 0.0 and dy > 0.0

    if diverging:
        if D > dx or D > dy:
            logger.warning("Beam model plane is upstream of scan distance: D=%.1f dx=%.1f dy=%.1f -> sign flip possible",
                           D, dx, dy)
    else:
        logger.warning("No source-to-axis distance in plan; assuming parallel beam (no backprojection).")

    for layer in field.layers:
        Enom = float(layer.energy_nominal)

        # build energy bin index and populate energy arrays
        k = energy_to_bin.get(Enom)
        if k is None:
            k = len(Enom_list)
            energy_to_bin[Enom] = k
            Enom_list.append(Enom)
            Emean_list.append(float(bm.f_e(Enom)))
            Esig_list.append(float(bm.f_espread(Enom)))
            PpMU_list.append(float(bm.f_ppmu(Enom)))

        # process spots in this layer
        for s in layer.spots:
            w = float(s.mu) * PpMU_list[k] * 1e6  # number of protons for this spot
            if w <= 0.0:
                continue

            # positions at isocenter
            x_iso = float(s.x)
            y_iso = float(s.y)

            if diverging:
                # backproject beam positions to beam model plane
                x_bm = x_iso * (dx - D) / dx
                y_bm = y_iso * (dy - D) / dy
            else:
                x_bm = x_iso
                y_bm = y_iso

            # direction of ray crossing x_bm,y_bm at beam model plane and x_iso,y_iso at isocenter
            v0 = np.array([x_iso - x_bm, y_iso - y_bm, -D], dtype=float)
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

    logger.debug("Field has %d spots across %d energy layers", len(w_list), len(Enom_list))
    logger.debug("Total protons in field: %.3e", total)

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
        cum_n=cumw,
        total_n=total,
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
    logger.debug("Prewarming beam cache for %d energy layers", sampler.Enom.shape[0])
    K = sampler.Enom.shape[0]
    Lx = np.empty((K, 2, 2), dtype=np.float32)
    Ly = np.empty((K, 2, 2), dtype=np.float32)

    # loop over energy layers
    for k in range(K):
        Enom = float(sampler.Enom[k])

        # get interpolated beam model parameters
        sx = float(bm.f_sx(Enom))
        sy = float(bm.f_sy(Enom))
        divx = float(bm.f_divx(Enom))
        divy = float(bm.f_divy(Enom))

        # the beam model holdes correlation coefficients (not covariances as stated earlier)
        rho_x = float(bm.f_corx(Enom))
        rho_y = float(bm.f_cory(Enom))

        # some sanity checks
        a = sx * sx
        b = divx * divx
        c = rho_x * sx * divx
        det = a*b - c*c

        if abs(rho_x) > 1.0001:
            logger.warning("rho_x out of range at Enom=%.3f: rho_x=%.6g", Enom, rho_x)

        if det < -1e-12 * (a*b):  # relative tolerance
            logger.warning("Cov not PSD at Enom=%.3f: sx=%.6g divx=%.6g rho=%.6g det=%.6g",
                           Enom, sx, divx, rho_x, det)
        if divx > 0.1:  # 0.1 rad = 100 mrad, extremely large for clinical pencil beams
            logger.warning("divx unusually large (rad?): Enom=%.1f divx=%.4g", Enom, divx)

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
    rot180x: bool = False,
) -> bytearray:
    """
    MCPL buffer generation with fused loop for better CPU cache usage.
    Produces exactly n records (32 bytes each) as bytes ready for f.write().
    """

    # sample spot indices proportional to MU
    u = rng.random(n) * sampler.total_n
    idxs = np.searchsorted(sampler.cum_n, u, side="right").astype(np.int64, copy=False)

    # get 5 sets of standard normal random numbers per particle
    Z = rng.standard_normal((n, 5), dtype=np.float32)

    out = bytearray(n * _particle_struct.size)
    off = 0
    z_plane = float(sampler.z_plane)

    # loop over every particle to sample
    for j, idx in enumerate(idxs):

        # get spot energy layer index and the cached Cholesky factors
        k = int(sampler.idxE[idx])
        Lx = cache.Lx[k]
        Ly = cache.Ly[k]

        z0, z1, z2, z3, zE = Z[j]

        # Sample correlated transverse phase space:
        #   x_local, y_local : transverse position offsets at z = z_plane [mm]
        #   xprim,  yprim    : transverse slopes dx/dz, dy/dz (small angles) [rad]
        # The correlation between position and angle is encoded via the shared z0/z2 terms.
        x_local = Lx[0, 0] * z0
        xprim = Lx[1, 0] * z0 + Lx[1, 1] * z1  # xprim = dx/dz ~ angle in radians
        y_local = Ly[0, 0] * z2
        yprim = Ly[1, 0] * z2 + Ly[1, 1] * z3  # yprim = dy/dz

        v0 = sampler.v0[idx]
        t1 = sampler.t1[idx]
        t2 = sampler.t2[idx]

        # Offset the x/y position in the local transverse basis (t1/t2), matching the
        # angular offsets below, so the position-angle correlation is direction-independent
        # (#72). zg stays on the fixed source plane so the phase space remains planar at +D.
        xg = float(sampler.xbm[idx] + x_local * t1[0] + y_local * t2[0])
        yg = float(sampler.ybm[idx] + x_local * t1[1] + y_local * t2[1])
        zg = z_plane

        vx = float(v0[0] + xprim * t1[0] + yprim * t2[0])
        vy = float(v0[1] + xprim * t1[1] + yprim * t2[1])
        vz = float(v0[2] + xprim * t1[2] + yprim * t2[2])

        invn = 1.0 / np.sqrt(vx * vx + vy * vy + vz * vz)
        vx *= invn
        vy *= invn
        vz *= invn

        if rot180x:
            # Rigid 180-deg rotation about X (see numpy path / #71): +Z travel, Y flipped.
            yg = -yg
            zg = -zg
            vy = -vy
            vz = -vz

        Emean = float(sampler.Emean[k])
        Esig = float(sampler.Esig[k])
        ekin = Emean + Esig * float(zE)
        if ekin < 0.0:
            ekin = 0.0

        fp1, fp2, ekin_signed = _mcpl_app_pack(vx, vy, vz, ekin)

        _particle_struct.pack_into(
            out, off,
            np.float32(xg * 0.1), np.float32(yg * 0.1), np.float32(zg * 0.1),  # mm to cm
            np.float32(fp1), np.float32(fp2), np.float32(ekin_signed),
            np.float32(0.0),
            int(pdg),
        )
        off += _particle_struct.size

    return out


def _sample_mcpl_buffer_fused_numpy(
    sampler: FieldSampler,
    cache: BeamCache,
    n: int,
    *,
    rng: np.random.Generator,
    pdg: int = PDG_PROTON,
    rot180x: bool = False,
) -> bytes:
    """
    Vectorized MCPL buffer generation (pure NumPy).

    Produces exactly n records (32 bytes each) as bytes ready for f.write().
    """

    # --- sample spot indices proportional to MU ---
    u = rng.random(n, dtype=np.float64) * sampler.total_n
    idxs = np.searchsorted(sampler.cum_n, u, side="right").astype(np.int64, copy=False)

    # idx has the length n, corresponding to the number of particles to sample

    # --- random normals: z0,z1,z2,z3,zE ---
    Z = rng.standard_normal((n, 5), dtype=np.float32)
    z0, z1, z2, z3, zE = (Z[:, 0], Z[:, 1], Z[:, 2], Z[:, 3], Z[:, 4])

    # --- gather per-particle spot + energy-bin data ---
    k = sampler.idxE[idxs].astype(np.int64, copy=False)

    # Cholesky factors per particle: shape (n,2,2)
    Lx = cache.Lx[k]
    Ly = cache.Ly[k]

    # spot centers at beam-model plane
    xbm = sampler.xbm[idxs]
    ybm = sampler.ybm[idxs]
    z_plane = np.float32(sampler.z_plane)

    # basis vectors per particle: shape (n,3)
    v0 = sampler.v0[idxs]
    t1 = sampler.t1[idxs]
    t2 = sampler.t2[idxs]

    # --- sample correlated phase space in x and y ---
    # x_local = L00*z0
    x_local = Lx[:, 0, 0] * z0
    # xprim  = L10*z0 + L11*z1
    xprim = Lx[:, 1, 0] * z0 + Lx[:, 1, 1] * z1

    y_local = Ly[:, 0, 0] * z2
    yprim = Ly[:, 1, 0] * z2 + Ly[:, 1, 1] * z3

    # --- positions at the fixed beam-model plane (z = z_plane), x/y in the local basis ---
    # The transverse x/y offsets must use the SAME frame (t1/t2) as the angular offsets
    # below; applying them in global x/y instead inverts the position-angle (Twiss)
    # correlation whenever t1/t2 flip sign relative to the global axes -- which they do for
    # the -Z beam direction (t1 = -x_hat), breaking the X plane only (#72). zg is pinned to
    # the source plane so the phase space stays planar at +D (per the docs/logs framing).
    xg = (xbm + x_local * t1[:, 0] + y_local * t2[:, 0]) * np.float32(0.1)   # mm -> cm
    yg = (ybm + x_local * t1[:, 1] + y_local * t2[:, 1]) * np.float32(0.1)
    zg = np.full(n, z_plane * np.float32(0.1), dtype=np.float32)

    # --- directions: v = v0 + xprim*t1 + yprim*t2, then normalize ---
    # compute components (all float32)
    vx = v0[:, 0] + xprim * t1[:, 0] + yprim * t2[:, 0]
    vy = v0[:, 1] + xprim * t1[:, 1] + yprim * t2[:, 1]
    vz = v0[:, 2] + xprim * t1[:, 2] + yprim * t2[:, 2]

    invn = np.reciprocal(np.sqrt(vx * vx + vy * vy + vz * vz, dtype=np.float32))
    vx *= invn
    vy *= invn
    vz *= invn

    if rot180x:
        # Rigid 180-deg rotation about X: (x,y,z)->(x,-y,-z), (vx,vy,vz)->(vx,-vy,-vz).
        # Reverses the beam to +Z travel for downstream codes that expect it; being a
        # proper rotation it preserves all beam optics (#71). Y sign is flipped.
        yg = -yg
        zg = -zg
        vy = -vy
        vz = -vz

    # --- energy sampling ---
    Emean = sampler.Emean[k]
    Esig = sampler.Esig[k]
    ekin = Emean + Esig * zE
    ekin = np.maximum(ekin, np.float32(0.0))

    # --- APP packing (vectorized) ---
    ax = np.abs(vx)
    ay = np.abs(vy)
    az = np.abs(vz)

    # default init
    fp1 = np.empty(n, dtype=np.float32)
    fp2 = np.empty(n, dtype=np.float32)
    ekin_signed = ekin.copy()

    # avoid division by zero (should not happen for vz in your geometry, but safe)
    inv_vz = np.empty(n, dtype=np.float32)
    np.divide(np.float32(1.0), vz, out=inv_vz, where=vz != 0.0)
    inv_vz[vz == 0.0] = np.float32(np.inf)

    m0 = (az >= ax) & (az >= ay)             # dominant z
    m1 = (ax >= ay) & (ax > az)              # dominant x
    m2 = ~(m0 | m1)                          # dominant y

    # m0: fp1=vx, fp2=vy, sign on ekin by vz
    fp1[m0] = vx[m0]
    fp2[m0] = vy[m0]
    ekin_signed[m0 & (vz < 0.0)] *= np.float32(-1.0)

    # m1: fp1=1/vz, fp2=vy, sign on ekin by vx
    fp1[m1] = inv_vz[m1]
    fp2[m1] = vy[m1]
    ekin_signed[m1 & (vx < 0.0)] *= np.float32(-1.0)

    # m2: fp1=vx, fp2=1/vz, sign on ekin by vy
    fp1[m2] = vx[m2]
    fp2[m2] = inv_vz[m2]
    ekin_signed[m2 & (vy < 0.0)] *= np.float32(-1.0)

    # --- pack into MCPL record struct (32 bytes each) via structured dtype ---
    rec_dtype = np.dtype([
        ("x", "<f4"), ("y", "<f4"), ("z", "<f4"),
        ("fp1", "<f4"), ("fp2", "<f4"), ("ekin_signed", "<f4"),
        ("time", "<f4"), ("pdg", "<i4"),
    ])

    rec = np.empty(n, dtype=rec_dtype)
    rec["x"] = xg
    rec["y"] = yg
    rec["z"] = zg
    rec["fp1"] = fp1
    rec["fp2"] = fp2
    rec["ekin_signed"] = ekin_signed.astype(np.float32, copy=False)
    rec["time"] = np.float32(0.0)
    rec["pdg"] = np.int32(pdg)

    return rec.tobytes(order="C")


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
