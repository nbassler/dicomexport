"""
Spotlist text export utilities for proton (or ion) treatment plans.

This module converts a :class:`dicomexport.model_plan.Plan` object into a
plain-text "spotlist" file suitable for use with downstream dose engines
or beam delivery simulations.

The main public entry point is :func:`export_spotlist`, which:

- Selects fields from the input plan (optionally restricted by field list).
- Builds a per-spot :class:`pandas.DataFrame` with geometric and beam
  parameters.
- Adds derived beam parameters needed for various spotlist formats
  (e.g. FWHM from sigma, divergences, correlations).
- Writes the result to disk as a space-separated text file with a
  configurable number of columns, as defined in ``SPOTLIST_EXPORT_COLS``.
"""

from __future__ import annotations
from dicomexport.model_plan import Plan
# from dicomexport.beam_model import BeamModel
from dicomexport.__version__ import __version__

import logging

import numpy as np
import pandas as pd

from pathlib import Path

FWHM_TO_SIGMA = 1.0 / (2.0 * np.sqrt(2.0 * np.log(2.0)))  # ≈ 1/2.35482
SIGMA_TO_FWHM = 2.0 * np.sqrt(2.0 * np.log(2.0))  # 2.35482...


logger = logging.getLogger(__name__)


SPOTLIST_EXPORT_COLS = {
    5:  ["E_GeV", "X_cm", "Y_cm", "FWHMxy_cm", "Weight"],
    6:  ["E_GeV", "X_cm", "Y_cm", "FWHMx_cm", "FWHMy_cm", "Weight"],
    7:  ["E_GeV", "dE_GeV", "X_cm", "Y_cm", "FWHMx_cm", "FWHMy_cm", "Weight"],
    9:  ["E_GeV", "dE_GeV", "X_cm", "Y_cm", "FWHMx_cm", "FWHMy_cm", "SigXpr_mrad", "SigYpr_mrad", "Weight"],
    11: ["E_GeV", "dE_GeV", "X_cm", "Y_cm", "FWHMx_cm", "FWHMy_cm", "SigXpr_mrad", "SigYpr_mrad", "CorX", "CorY", "Weight"],
}

SPOTLIST_COLUMN_LABELS = {
    "E_GeV":        "E [GeV or GeV/n]",
    "dE_GeV":       "dE [GeV or GeV/n]",
    "X_cm":         "X [cm]",
    "Y_cm":         "Y [cm]",
    "FWHMx_cm":     "FWHMx [cm]",
    "FWHMy_cm":     "FWHMy [cm]",
    "FWHMxy_cm":    "FWHMxy [cm]",
    "SigXpr_mrad":  "SigXpr [mrad]",
    "SigYpr_mrad":  "SigYpr [mrad]",
    "CorX":         "CorX",
    "CorY":         "CorY",
    "Weight":       "Weight [primary particle count]",
}


# ---- public API ----
def export_spotlist(

    plan: Plan,
    output_path: str,
    *,
    field_list: list[int] | None = None,
    col_count: int = 11,
) -> None:
    """
    Export spot list data from a treatment plan to file(s).

    Exports spot list information from a Plan object to one or more output files,
    with one file generated per treatment field. The output format and content are
    determined by the specified column count and export column configuration.

    Args:
        plan: The treatment plan object containing field and spot data.
        output_path: Base path for output file(s). Individual field files will be
            named using the pattern: {stem}_field{dicom_field_number:02d}{suffix}
        field_list: Optional list of 1-based field numbers to export. If None,
            all fields in the plan are exported. Defaults to None.
        col_count: Number of columns in the output file format. Must be a valid
            value supported by the spotlist header builder. Defaults to 11.

    Returns:
        None

    Raises:
        ValueError: If col_count is not a valid spotlist column count.
        IndexError: If field_list contains invalid field numbers.

    Side Effects:
        Writes one or more spotlist files to disk at the specified output_path
        location(s). Logs information about each file written.
    """

    # Build canonical spot table from plan (assumes beam model already applied)
    df = _plan_to_spot_dataframe(plan)

    # Add derived export columns (GeV/cm/FWHM/mrad + Weight)
    df = _add_spotlist_export_columns(df)

    # Optional subset of fields (expects 1-based field numbers as in your CLI)
    if field_list is not None:
        df = df[df["field"].isin(field_list)]

    base = Path(output_path)

    # One output file per field (using DICOM field.number in filename)
    for field_idx in sorted(df["field"].unique()):
        dicom_field_number = plan.fields[field_idx - 1].number
        out_path = base.with_name(f"{base.stem}_field{dicom_field_number:02d}{base.suffix}")

        logger.info("Writing spotlist: %s", out_path)

        field_obj = plan.fields[field_idx - 1]
        header_field = _build_spotlist_header(
            col_count,
            __version__,
            field_no=field_obj.number,
            field_name=field_obj.name,
            n_spots=field_obj.n_spots,
        )
        _write_spotlist(df[df["field"] == field_idx], out_path, col_count=col_count, header=header_field)


def _write_spotlist(df: pd.DataFrame, out_path: Path, *, col_count: int, header: str) -> None:
    cols = SPOTLIST_EXPORT_COLS[col_count]

    with open(out_path, "w", encoding="utf-8") as f:
        f.write(header)
        df.loc[:, cols].to_csv(
            f,
            sep=" ",
            header=False,
            index=False,
            float_format="%.6g",
            lineterminator="\n",
        )


def _plan_to_spot_dataframe(plan) -> pd.DataFrame:
    """
    Canonical internal spot table (units: MeV, mm, rad).
    One row per spot.
    """
    rows = []
    bm = getattr(plan, "beam_model", None)
    if bm is None:
        raise ValueError(
            "plan.beam_model must be set before converting plan to a spot dataframe; "
            "cannot compute particles per MU without a beam model."
        )

    for field_idx, myfield in enumerate(plan.fields, start=1):
        for layer_idx, layer in enumerate(myfield.layers, start=1):
            if layer.n_spots == 0:
                continue

            # Energies in MeV
            E_nom = float(layer.energy_nominal)
            E_meas = float(layer.energy_measured) if layer.energy_measured else np.nan
            dE = float(layer.espread) if layer.espread else np.nan

            # Spot size: in plan model this is FWHM in mm (from beam model application)
            # Convert to sigma in mm for canonical storage.
            fwhm_x_mm, fwhm_y_mm = layer.spot_size if layer.spot_size else (np.nan, np.nan)
            sx_mm = float(fwhm_x_mm) * FWHM_TO_SIGMA if np.isfinite(fwhm_x_mm) else np.nan
            sy_mm = float(fwhm_y_mm) * FWHM_TO_SIGMA if np.isfinite(fwhm_y_mm) else np.nan

            # Divergence/correlation (rad, dimensionless) from beam model if present
            if bm is not None and getattr(bm, "has_divergence", False):
                sxpr_rad = float(bm.f_divx(E_nom))
                sypr_rad = float(bm.f_divy(E_nom))
                cor_x = float(bm.f_corx(E_nom))
                cor_y = float(bm.f_cory(E_nom))
            else:
                # No divergence/correlation available from beam model: use explicit 0.0
                # instead of NaN to avoid empty fields in fixed-column CSV exports.
                sxpr_rad = 0.0
                sypr_rad = 0.0
                cor_x = 0.0
                cor_y = 0.0

            for spot_idx, spot in enumerate(layer.spots, start=1):
                rows.append({
                    # identifiers / provenance
                    "field": field_idx,
                    "layer": layer_idx,
                    "spot": spot_idx,
                    "field_name": getattr(myfield, "name", ""),

                    # energies
                    "E_nom_MeV": E_nom,
                    "E_MeV": E_meas,
                    "dE_MeV": dE,

                    # positions (mm)
                    "x_mm": float(spot.x),
                    "y_mm": float(spot.y),

                    # spot widths (sigma, mm)
                    "sx_mm": sx_mm,
                    "sy_mm": sy_mm,

                    # divergence (rad) + correlation (dimensionless)
                    "sxpr_rad": sxpr_rad,
                    "sypr_rad": sypr_rad,
                    "cor_x": cor_x,
                    "cor_y": cor_y,

                    # weight in MU (canonical)
                    "mu": float(spot.mu),
                    "particles": float(spot.mu) * float(bm.f_ppmu(E_nom)),
                })

    df = pd.DataFrame.from_records(rows)

    # A couple of helpful derived canonical columns:
    if not df.empty:
        df["mu_scaled"] = df["mu"] * float(getattr(plan, "scaling", 1.0))
        # (above line optional; you might instead apply scaling later per exporter)

    return df


def _add_spotlist_export_columns(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()

    # energy
    E_MeV = out["E_MeV"].where(out["E_MeV"].notna(), out["E_nom_MeV"])
    dE_MeV = out["dE_MeV"].where(out["dE_MeV"].notna(), 0.0)
    out["E_GeV"] = E_MeV / 1000.0
    out["dE_GeV"] = dE_MeV / 1000.0

    # positions
    out["X_cm"] = out["x_mm"] / 10.0
    out["Y_cm"] = out["y_mm"] / 10.0

    # widths: export as FWHM in cm
    out["FWHMx_cm"] = (out["sx_mm"] * SIGMA_TO_FWHM) / 10.0
    out["FWHMy_cm"] = (out["sy_mm"] * SIGMA_TO_FWHM) / 10.0
    out["FWHMxy_cm"] = 0.5 * (out["FWHMx_cm"] + out["FWHMy_cm"])  # or choose a different convention

    # divergence: export as mrad
    out["SigXpr_mrad"] = out["sxpr_rad"] * 1000.0
    out["SigYpr_mrad"] = out["sypr_rad"] * 1000.0

    # correlation naming
    out["CorX"] = out["cor_x"]
    out["CorY"] = out["cor_y"]

    # weight should ideally be the total number of particles to get the right dose
    out["Weight"] = out["particles"]

    return out


def _build_spotlist_header(
    col_count: int,
    version: str,
    *,
    field_no: int | None = None,
    field_name: str | None = None,
    n_spots: int | None = None,


) -> str:
    try:
        cols = SPOTLIST_EXPORT_COLS[col_count]
    except KeyError:
        raise ValueError(f"Unsupported spotlist column count: {col_count}")

    labels = [SPOTLIST_COLUMN_LABELS[c] for c in cols]
    col_desc = ", ".join(labels)

    lines = [
        f"# DICOM-RT Ion plan spot list exported by dicomexport {version}",
    ]

    # Field metadata comes early (what you want)
    if field_no is not None:
        lines.append(f"# FieldNumber: {field_no}")
    if field_name is not None:
        lines.append(f"# FieldName: {field_name}")
    if n_spots is not None:
        lines.append(f"# Spots: {n_spots}")

    lines += [
        "#",
        f"# Columns ({len(cols)}):",
        f"#   {col_desc}",
    ]

    if "SigXpr_mrad" in cols:
        lines.append("#   SigXpr, SigYpr : RMS angular divergence (x', y') in mrad")

    if "CorX" in cols:
        lines.append("#   CorX, CorY     : Correlation coefficients rho(x,x') and rho(y,y')")

    return "\n".join(lines) + "\n"
