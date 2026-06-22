import pytest
import numpy as np
from pathlib import Path

from dicomexport.beam_model import BeamModel, get_fwhm

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
