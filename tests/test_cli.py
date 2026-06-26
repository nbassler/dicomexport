import re
import sys
from pathlib import Path
from io import StringIO

import pytest

import dicomexport.main_plan_export as main_plan_export


class TestPregdosCLI:

    def test_help_flag(self):
        saved_stdout = sys.stdout
        try:
            sys.stdout = StringIO()
            with pytest.raises(SystemExit) as exc_info:
                main_plan_export.main(["-h"])
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
                main_plan_export.main(["-V"])
            output = sys.stdout.getvalue()
        finally:
            sys.stdout = saved_stdout
        assert re.search(r"\d+\.\d+(\.\d+)?([a-z0-9\.\+\-]+)?", output)
        assert exc_info.value.code == 0

    def _run_conversion_test(self, dicom_file_name: str):
        test_output_file = Path("plan_field01.txt")
        test_output_file.unlink(missing_ok=True)

        test_args = [
            "-f1",
            "-vv",
            "-b=res/beam_models/DCPT_beam_model__v2.csv",
            f"res/test_plans/{dicom_file_name}",
        ]

        assert main_plan_export.main(test_args) == 0, \
            f"CLI execution failed for {dicom_file_name}"
        assert test_output_file.exists(), \
            f"Output file was not created for {dicom_file_name}."
        assert test_output_file.stat().st_size > 0, \
            f"Output file is empty for {dicom_file_name}."

        test_output_file.unlink()

    def test_conversion_temp_160MeV(self):
        self._run_conversion_test("temp_160MeV_10x10.dcm")

    def test_conversion_temp_sobp(self):
        self._run_conversion_test("temp_sobp_10x10.dcm")

    def test_beam_direction_flag(self):
        for direction in ('pos-z', 'neg-z'):
            test_output_file = Path("plan_field01.txt")
            test_output_file.unlink(missing_ok=True)

            test_args = [
                "-f1",
                "-b=res/beam_models/DCPT_beam_model__v2.csv",
                f"--nozzle-side={direction}",
                "res/test_plans/temp_160MeV_10x10.dcm",
            ]
            assert main_plan_export.main(test_args) == 0, f"CLI failed for --beam-direction={direction}"
            assert test_output_file.exists()

            content = test_output_file.read_text()
            if direction == 'pos-z':
                assert 'TransZ             = 500.0 mm' in content, "pos-z: expected +TransZ"
            else:
                assert 'TransZ             = -500.0 mm' in content, "neg-z: expected -TransZ"
            assert 'BeamPositionRotY' in content, f"BeamPositionRotY time feature missing for {direction}"

            test_output_file.unlink()

    def test_test_mode_flag(self):
        test_output_file = Path("plan_field01.txt")
        test_output_file.unlink(missing_ok=True)

        test_args = [
            "-f1",
            "-b=res/beam_models/DCPT_beam_model__v2.csv",
            "--test-mode",
            "res/test_plans/temp_160MeV_10x10.dcm",
        ]

        assert main_plan_export.main(test_args) == 0
        assert test_output_file.exists()

        content = test_output_file.read_text()
        assert 'Ge/IsoBox' in content, "--test-mode output missing IsoBox geometry"
        assert 'Sc/IsoScore' in content, "--test-mode output missing IsoScore scorer"
        assert 'Ge/Gantry' in content, "--test-mode output missing gantry geometry"
        assert 'Ge/World' in content, "--test-mode output missing world geometry"

        test_output_file.unlink()
