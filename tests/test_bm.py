import pytest
import numpy as np
from pathlib import Path

from dicomexport.beam_model import BeamModel, get_fwhm

# Minimal 6-column beam model data (two rows so cubic interp doesn't break on first test)
_BM_6COL_DATA = """\
#"Test model"
#"BMODPOS {pos}"
70,71.38,1.23,2106924,4.472,3.629
90,90.94,1.18,2500367,3.983,3.29
110,110.76,1.08,2854807,3.778,3.072
130,130.56,0.89,3204641,3.78,2.875
150,150.4,0.73,3519991,3.886,2.802
"""

beam_models_dir = Path("res") / "beam_models"


class TestBeamModel:

    def setup_method(self):
        beam_model_files = sorted(beam_models_dir.glob("*.csv"))
        if not beam_model_files:
            pytest.skip("No beam model files found in the directory.")
        self.beam_models = [
            BeamModel(path_bm, beam_model_position=500.0)
            for path_bm in beam_model_files
            if path_bm.is_file()
        ]

    def test_fwhm_calculation(self):
        assert get_fwhm(1.0) == pytest.approx(2.354820045, abs=1e-5)

    def test_beam_model_integrity(self):
        for bm in self.beam_models:
            assert isinstance(bm.data, np.ndarray)
            assert bm.data.shape[0] > 0, "Beam model data is empty."

            for attr in ['f_sx', 'f_sy', 'f_e']:
                interpolator = getattr(bm, attr, None)
                assert interpolator is not None, f"{attr} is missing."
                assert callable(interpolator), f"{attr} is not callable."

            sx_val = bm.f_sx(150.0)
            sy_val = bm.f_sy(150.0)
            e_val = bm.f_e(150.0)
            assert 0.0 < sx_val < 20.0, f"f_sx returned unrealistic value: {sx_val}"
            assert 0.0 < sy_val < 20.0, f"f_sy returned unrealistic value: {sy_val}"
            assert 70.0 < e_val < 230.0, f"f_e returned unrealistic value: {e_val}"


class TestBeamModelPosition:

    def test_v2_bmodpos_from_file(self):
        bm = BeamModel(beam_models_dir / "DCPT_beam_model__v2.csv")
        assert bm.beam_model_position == pytest.approx(500.0)

    def test_v5_bmodpos_from_file(self):
        bm = BeamModel(beam_models_dir / "DCPT_beam_model__v5.csv")
        assert bm.beam_model_position == pytest.approx(600.0)

    def test_no_bmodpos_uses_default(self):
        bm = BeamModel(beam_models_dir / "bm_test_6col.csv")
        assert bm.beam_model_position == pytest.approx(500.0)

    def test_cli_override(self):
        bm = BeamModel(beam_models_dir / "DCPT_beam_model__v5.csv", beam_model_position=700.0)
        assert bm.beam_model_position == pytest.approx(700.0)

    @pytest.mark.parametrize("bad_unit", ["cm", "m", "µm", "um"])
    def test_bad_unit_raises(self, tmp_path, bad_unit):
        f = tmp_path / "bad_unit.csv"
        f.write_text(_BM_6COL_DATA.format(pos=f"600.0 {bad_unit}"))
        with pytest.raises(ValueError, match="BMODPOS unit must be 'mm'"):
            BeamModel(f)

    def test_missing_unit_raises(self, tmp_path):
        f = tmp_path / "no_unit.csv"
        f.write_text(_BM_6COL_DATA.format(pos="600.0"))
        with pytest.raises(ValueError, match="BMODPOS unit must be 'mm'"):
            BeamModel(f)

    @pytest.mark.parametrize("bad_pos", [0.0, -1.0, -500.0])
    def test_nonpositive_position_raises(self, tmp_path, bad_pos):
        f = tmp_path / "bad_pos.csv"
        f.write_text(_BM_6COL_DATA.format(pos=f"{bad_pos} mm"))
        with pytest.raises(ValueError, match="distance upstream of isocenter"):
            BeamModel(f)
