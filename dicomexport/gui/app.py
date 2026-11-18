import subprocess
import sys
from pathlib import Path

import streamlit as st

from dicomexport.config import ConfigError
from dicomexport.gui.utils import by_name, gui_config


def pick_file(label: str, files: dict[str, Path], default: Path | None) -> Path | None:
    options = [None, *files]
    index = options.index(default.name) if default and default.name in files else 0
    name = st.selectbox(label, options=options, index=index,
                        format_func=lambda name: name if name is not None else f"Select {label.lower()}")
    return files[name] if name is not None else None


st.title("DICOM Export")

# The configuration directory in effect (issue #112), passed on as --config-dir so the export
# also takes its range shifter catalog from it.
try:
    cfg = gui_config()
except ConfigError as e:
    st.error(str(e))
    st.stop()
st.caption(f"Configuration directory: {cfg}")

beam_models = by_name(cfg.beam_models())
ct_tables = by_name(cfg.ct_to_material_tables())
st.info("Tip: in Windows Explorer, click the address bar to copy a folder path, then paste it here.")

study_dir = st.text_input("Study directory", placeholder="C:\\path\\to\\study")

if beam_models:
    beam_model_path = pick_file("Beam model", beam_models, cfg.default_beam_model())
else:
    st.warning(f"No beam model CSVs found in {cfg.path / 'beam_models'}")
    beam_model_path = st.text_input("Beam model CSV", placeholder="C:\\path\\to\\beam_model.csv")

if ct_tables:
    ct_table_path = pick_file("CT-number-to-material table", ct_tables, cfg.default_ct_to_material_table())
else:
    st.warning(f"No CT-number-to-material tables found in {cfg.path / 'ct_to_material'}")
    ct_table_path = st.text_input("CT-number-to-material table", placeholder="C:\\path\\to\\table.txt")

with st.expander("Advanced options"):
    output_base = st.text_input("Output filename", value="topas.txt")
    bm_position = None
    if st.checkbox("Override beam model position"):
        bm_position = st.number_input("Beam model position (mm)", value=500.0)
    field_nr = st.number_input("Field BeamNumber (0 = all)", value=0, step=1)
    nstat = st.number_input("Target protons (nstat)", value=1_000_000, step=100_000)

if st.button("Run export", type="primary"):
    study_path = Path(study_dir.strip()).resolve(strict=False) if study_dir else None

    errors = []
    if not study_path or not study_path.is_dir():
        errors.append(f"Study directory not found: {study_dir!r}")
    if not beam_model_path:
        errors.append("Select a beam model or enter its path.")
    elif not Path(beam_model_path).is_file():
        errors.append(f"Beam model file not found: {beam_model_path!r}")
    if not ct_table_path:
        errors.append("Select a CT-number-to-material table or enter its path.")
    elif isinstance(ct_table_path, Path) and not ct_table_path.is_file():
        errors.append(f"CT-number-to-material table not found: {ct_table_path!r}")

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
            "-s", str(ct_table_path),
            "--config-dir", str(cfg.path),
            "-f", str(int(field_nr)),
            "-N", str(int(nstat)),
        ]
        if bm_position is not None:
            args.extend(["-p", str(bm_position)])
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
