import subprocess
import sys
from pathlib import Path

import streamlit as st

from dicomexport.gui.utils import list_files

# Paths relative to the project root (three levels up from dicomexport/gui/)
PROJECT_ROOT = Path(__file__).parent.parent.parent
BEAM_MODELS_DIR = PROJECT_ROOT / "res" / "beam_models"
SPR_TABLES_DIR = PROJECT_ROOT / "res" / "spr_tables"


beam_models = list_files(BEAM_MODELS_DIR, [".csv"])
spr_tables = list_files(SPR_TABLES_DIR, [".csv", ".txt"])

st.title("DICOM Export")
st.info("Tip: in Windows Explorer, click the address bar to copy a folder path, then paste it here.")

study_dir = st.text_input("Study directory", placeholder="C:\\path\\to\\study")

if beam_models:
    beam_model_name = st.selectbox("Beam model", options=list(beam_models.keys()))
    # Path object comes directly from the pre-scanned res/ directory, not user input
    beam_model_path: Path | None = beam_models[beam_model_name]
else:
    st.warning(f"No beam model CSVs found in {BEAM_MODELS_DIR}")
    _bm_str = st.text_input("Beam model CSV", placeholder="C:\\path\\to\\beam_model.csv")
    beam_model_path = Path(_bm_str).resolve(strict=False) if _bm_str else None

if spr_tables:
    spr_table_name = st.selectbox("SPR-to-material table", options=list(spr_tables.keys()))
    # Path object comes directly from the pre-scanned res/ directory, not user input
    spr_table_path: Path | None = spr_tables[spr_table_name]
    _spr_str: str | None = None
else:
    st.warning(f"No SPR tables found in {SPR_TABLES_DIR}")
    _spr_str = st.text_input("SPR-to-material table (relative to study directory)", placeholder="spr_table.txt")
    spr_table_path: Path | None = None

with st.expander("Advanced options"):
    output_base = st.text_input("Output filename", value="topas.txt")
    bm_position = st.number_input("Beam model position (mm)", value=500.0)
    field_nr = st.number_input("Field number (0 = all)", value=0, step=1)
    nstat = st.number_input("Target protons (nstat)", value=1_000_000, step=100_000)

if st.button("Run export", type="primary"):
    # study_dir is intentionally user-provided: the user selects their DICOM study folder
    study_path = Path(study_dir.strip()).resolve(strict=False) if study_dir else None

    errors = []
    if not study_path or not study_path.is_dir():
        errors.append(f"Study directory not found: {study_dir!r}")

    # If no bundled SPR tables are available, interpret the user-provided path
    # as relative to the study directory and ensure it does not escape it.
    if not spr_tables:
        if not _spr_str:
            spr_table_path = None
        else:
            # Disallow absolute paths for SPR table when using manual input
            candidate = Path(_spr_str)
            if candidate.is_absolute():
                errors.append("Absolute paths are not allowed for the SPR-to-material table; "
                              "please provide a path relative to the study directory.")
                spr_table_path = None
            elif study_path and study_path.is_dir():
                raw_spr_path = (study_path / candidate).resolve(strict=False)
                try:
                    raw_spr_path.relative_to(study_path)
                except ValueError:
                    errors.append("SPR-to-material table must be located inside the study directory.")
                    spr_table_path = None
                else:
                    spr_table_path = raw_spr_path
            else:
                spr_table_path = None

    if not beam_model_path or not beam_model_path.is_file():
        errors.append(f"Beam model file not found: {beam_model_path!r}")
    if not spr_table_path or not spr_table_path.is_file():
        errors.append(f"SPR table file not found: {spr_table_path!r}")

    if errors:
        for e in errors:
            st.error(e)
    else:
        dicomexport_bin = Path(sys.executable).parent / "dicomexport"
        args = [
            str(dicomexport_bin),
            str(study_path),
            output_base,
            "-b", str(beam_model_path),
            "-s", str(spr_table_path),
            "-p", str(bm_position),
            "-f", str(int(field_nr)),
            "-N", str(int(nstat)),
        ]
        with st.spinner("Running..."):
            result = subprocess.run(args, capture_output=True, text=True)

        if result.returncode == 0:
            st.success("Export completed.")
        else:
            st.error(f"Export failed (exit code {result.returncode}).")

        if result.stdout:
            st.subheader("Output")
            st.text(result.stdout)
        if result.stderr:
            st.subheader("Log")
            st.text(result.stderr)
