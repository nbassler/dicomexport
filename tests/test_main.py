import re
import sys
from pathlib import Path
from io import StringIO

import pytest

import dicomexport.main as study
from dicomexport.main import get_path_dicom_dose
from tests.dicom_fixtures import write_dicom

DICOM_TEST_DIR = Path("res/test_studies/DCPT_headphantom/")
BEAM_MODEL_PATH = Path("res/beam_models/DCPT_beam_model__v2.csv")
SPR_TABLE_PATH = Path("res/spr_tables/SPRtoMaterial__Brain.txt")

_TOPAS_OUTPUT_FILES = [Path(f"topas_field{i:02d}.txt") for i in range(1, 4)]


class TestDoseLookup:
    def test_dose_found_in_subdir(self, tmp_path):
        sub = tmp_path / "dose"
        sub.mkdir()
        rd_file = write_dicom(sub / "RD001.dcm", "RTDOSE")
        result = get_path_dicom_dose(tmp_path)
        assert result == rd_file

    def test_dose_not_found_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            get_path_dicom_dose(tmp_path)

    def test_dose_found_by_modality_not_filename(self, tmp_path):
        """A dose file under a non-RD name must still be found (#77)."""
        rd_file = write_dicom(tmp_path / "1.2.840.113619.42", "RTDOSE")
        write_dicom(tmp_path / "CT001.dcm", "CT", instance_number=1)
        assert get_path_dicom_dose(tmp_path) == rd_file

    def test_dose_multiple_picks_first_reproducibly(self, tmp_path):
        write_dicom(tmp_path / "RD002.dcm", "RTDOSE")
        first = write_dicom(tmp_path / "RD001.dcm", "RTDOSE")
        assert get_path_dicom_dose(tmp_path) == first
        assert get_path_dicom_dose(tmp_path) == first


class TestPregdosCLI:

    def teardown_method(self):
        for f in _TOPAS_OUTPUT_FILES:
            if f.exists():
                f.unlink()

    def test_help_flag(self):
        saved_stdout = sys.stdout
        try:
            sys.stdout = StringIO()
            with pytest.raises(SystemExit) as exc_info:
                study.main(["-h"])
            output = sys.stdout.getvalue()
        finally:
            sys.stdout = saved_stdout
        assert "usage" in output.lower()
        assert exc_info.value.code == 0

    def test_version_flag(self):
        saved_stdout = sys.stdout
        try:
            sys.stdout = StringIO()
            with pytest.raises(SystemExit) as exc_info:
                study.main(["-V"])
            output = sys.stdout.getvalue()
        finally:
            sys.stdout = saved_stdout
        assert re.search(r"\d+\.\d+(\.\d+)?([a-z0-9\.\+\-]+)?", output)
        assert exc_info.value.code == 0

    def test_main(self):
        test_args = [
            "-vv",
            "-p 500.0",
            f"-b={BEAM_MODEL_PATH}",
            f"-s={SPR_TABLE_PATH}",
            f"{DICOM_TEST_DIR}",
        ]
        assert study.main(test_args) == 0, f"CLI execution failed for {DICOM_TEST_DIR}"

        for f in _TOPAS_OUTPUT_FILES:
            assert f.exists(), f"Output file was not created: {f}"
            assert f.stat().st_size > 0, f"Output file is empty: {f}"

    def test_nstat_parameter(self):
        nstat_value = int(2e6)
        test_args = [
            "-vv",
            f"-N={nstat_value}",
            f"-b={BEAM_MODEL_PATH}",
            f"-s={SPR_TABLE_PATH}",
            f"{DICOM_TEST_DIR}",
        ]
        assert study.main(test_args) == 0, "CLI execution failed with -N parameter."

        for f in _TOPAS_OUTPUT_FILES:
            assert f.exists(), f"Output file was not created: {f}"
            content = f.read_text()
            assert f"# REQUESTED_HISTORIES: {nstat_value}" in content, \
                f"nStat value not found or incorrect in {f}."
