import re
import sys
from pathlib import Path
from io import StringIO

import pytest

import dicomexport.main as study

DICOM_TEST_DIR = Path("res/test_studies/DCPT_headphantom/")
BEAM_MODEL_PATH = Path("res/beam_models/DCPT_beam_model__v2.csv")
SPR_TABLE_PATH = Path("res/spr_tables/SPRtoMaterial__Brain.txt")

_TOPAS_OUTPUT_FILES = [Path(f"topas_field{i:02d}.txt") for i in range(1, 4)]


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
        assert study.main(test_args) == 0, f"CLI execution failed with -N parameter."

        for f in _TOPAS_OUTPUT_FILES:
            assert f.exists(), f"Output file was not created: {f}"
            content = f.read_text()
            assert f"# REQUESTED_HISTORIES: {nstat_value}" in content, \
                f"nStat value not found or incorrect in {f}."
