import pytest
import numpy as np
from pathlib import Path

from dicomexport.beam_model import BeamModel, get_fwhm

# Minimal 6-column beam model data (>=4 rows required for cubic interpolation)
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


# Minimal 10-column beam model data; {cx}/{cy} are the correlation coefficients.
_BM_10COL_DATA = """\
#"Test model"
#"BMODPOS 500.0 mm"
70,71.38,1.23,2106924,4.472,3.629,0.0061,0.0056,{cx},{cy}
90,90.94,1.18,2500367,3.983,3.29,0.0058,0.0053,{cx},{cy}
110,110.76,1.08,2854807,3.778,3.072,0.0055,0.0050,{cx},{cy}
130,130.56,0.89,3204641,3.78,2.875,0.0052,0.0047,{cx},{cy}
150,150.4,0.73,3519991,3.886,2.802,0.0049,0.0044,{cx},{cy}
"""


class TestCorrelationBounds:
    """Columns 9/10 are dimensionless correlation coefficients and must be in [-1, 1]."""

    def test_shipped_models_are_in_range(self):
        for name in ("DCPT_beam_model__v2.csv", "DCPT_beam_model__v5.csv"):
            bm = BeamModel(beam_models_dir / name)
            for col in (8, 9):
                assert np.all(np.abs(bm.data[:, col]) <= 1.0)

    @pytest.mark.parametrize("cx,cy", [(1.5, 0.3), (0.3, 1.5), (-1.5, 0.3), (0.3, -1.5)])
    def test_out_of_range_raises(self, tmp_path, cx, cy):
        f = tmp_path / "bad_cor.csv"
        f.write_text(_BM_10COL_DATA.format(cx=cx, cy=cy))
        with pytest.raises(ValueError, match="must be a correlation coefficient in"):
            BeamModel(f)

    def test_error_names_the_offending_column(self, tmp_path):
        f = tmp_path / "bad_cory.csv"
        f.write_text(_BM_10COL_DATA.format(cx=0.3, cy=2.0))
        with pytest.raises(ValueError, match=r"cor\(y y'\)"):
            BeamModel(f)

    @pytest.mark.parametrize("rho", [1.0, -1.0, 0.999999, 1.0 + 1e-9])
    def test_boundary_values_accepted(self, tmp_path, rho):
        """|rho| == 1 is degenerate but legal; float noise past it must not hard-fail."""
        f = tmp_path / "edge_cor.csv"
        f.write_text(_BM_10COL_DATA.format(cx=rho, cy=rho))
        bm = BeamModel(f)
        assert bm.has_divergence

    def test_covariance_sized_values_still_load(self, tmp_path):
        """A legacy file holding covariances (~0.02) is inside [-1, 1] and must not break."""
        f = tmp_path / "cov_cor.csv"
        f.write_text(_BM_10COL_DATA.format(cx=0.024, cy=0.019))
        bm = BeamModel(f)
        assert float(bm.f_corx(110.0)) == pytest.approx(0.024)
