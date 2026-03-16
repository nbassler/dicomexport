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
    beam_model = str(beam_models[beam_model_name])
else:
    st.warning(f"No beam model CSVs found in {BEAM_MODELS_DIR}")
    beam_model = st.text_input("Beam model CSV", placeholder="C:\\path\\to\\beam_model.csv")

if spr_tables:
    spr_table_name = st.selectbox("SPR-to-material table", options=list(spr_tables.keys()))
    spr_table = str(spr_tables[spr_table_name])
else:
    st.warning(f"No SPR tables found in {SPR_TABLES_DIR}")
    spr_table = st.text_input("SPR-to-material table", placeholder="C:\\path\\to\\spr_table.txt")

with st.expander("Advanced options"):
    output_base = st.text_input("Output filename", value="topas.txt")
    bm_position = st.number_input("Beam model position (mm)", value=500.0)
    field_nr = st.number_input("Field number (0 = all)", value=0, step=1)
    nstat = st.number_input("Target protons (nstat)", value=1_000_000, step=100_000)

if st.button("Run export", type="primary"):
    study_path = Path(study_dir) if study_dir else None
    beam_model_path = Path(beam_model) if beam_model else None
    spr_table_path = Path(spr_table) if spr_table else None

    errors = []
    if not study_path or not study_path.is_dir():
        errors.append(f"Study directory not found: {study_dir!r}")
    if not beam_model_path or not beam_model_path.is_file():
        errors.append(f"Beam model file not found: {beam_model!r}")
    if not spr_table_path or not spr_table_path.is_file():
        errors.append(f"SPR table file not found: {spr_table!r}")

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
