import argparse

import pytest

from dicomexport.model_ct import CTModel, Image
from dicomexport.topas_text import TopasText, WORLD_MARGIN
from dicomexport.topas_version import EMITTANCE_PARAMETER_NAMES_SINCE, parse_topas_version


def _make_ct(columns: int, rows: int, n_slices: int,
             dx: float, dy: float, dz: float,
             ipp: tuple) -> CTModel:
    """Build a CTModel with the given voxel grid, with the first voxel centre at ipp."""
    images = []
    for i in range(n_slices):
        img = Image(pixel_spacing=(dy, dx), rows=rows, columns=columns,
                    image_position_patient=(ipp[0], ipp[1], ipp[2] + i * dz))
        img.slice_position = ipp[2] + i * dz
        images.append(img)
    return CTModel(images=images)


def _headphantom_ct() -> CTModel:
    return _make_ct(columns=512, rows=512, n_slices=177,
                    dx=0.5859375, dy=0.5859375, dz=1.5,
                    ipp=(-149.70703125, -316.20703125, -139.0))


def _issue61_ct() -> CTModel:
    """The 788-slice brain CT from issue #61, which aborted TOPAS on a geometry overlap."""
    dx = dy = 0.6836
    dz = 1.2
    # Choose ipp so that the CT centre lands on the (0, -240, -947.6) mm reported by TOPAS.
    ipp = (0.0 - 0.5 * 511 * dx,
           -240.0 - 0.5 * 511 * dy,
           -947.6 - 0.5 * (788 * dz - dz))
    return _make_ct(columns=512, rows=512, n_slices=788, dx=dx, dy=dy, dz=dz, ipp=ipp)


class TestDicomOrigin:
    def test_headphantom_origin(self):
        assert _headphantom_ct().dicom_origin == pytest.approx((0.0, -166.5, -7.0))

    def test_issue61_origin(self):
        assert _issue61_ct().dicom_origin == pytest.approx((0.0, -240.0, -947.6))

    def test_variables_emits_dicom_origin(self):
        """The DicomOrigin values must reach the input file.

        TOPAS defines them itself, but too late for its own geometry overlap check, which
        then sees the patient at -IsoCenter and can abort on a spurious overlap (issue #61).
        """
        from dicomexport.model_plan import Field, Layer

        field = Field(number=1, layers=[Layer(isocenter=(0.0, -170.16, -2.12))])
        text = TopasText.variables(field, _headphantom_ct().dicom_origin)

        assert "dc:Ge/Patient/DicomOriginX           = 0.0000 mm" in text
        assert "dc:Ge/Patient/DicomOriginY           = -166.5000 mm" in text
        assert "dc:Ge/Patient/DicomOriginZ           = -7.0000 mm" in text


class TestWorldHalfLengths:
    def test_world_contains_patient_box(self):
        """The world must contain the patient box wherever the isocenter puts it."""
        ct = _issue61_ct()
        isocenter = (25.0, -250.0, -605.0)
        hl = TopasText.world_half_lengths(ct, isocenter, beam_reach=500.0)

        # Patient box centre in world coordinates, and its extent.
        centre = [o - i for o, i in zip(ct.dicom_origin, isocenter)]
        assert centre == pytest.approx([-25.0, 10.0, -342.6])

        for c, half, h in zip(centre, ct.half_widths, hl):
            assert abs(c) + half <= h

        assert hl[2] == pytest.approx(342.6 + 472.8 + WORLD_MARGIN)

    def test_world_contains_beam_line(self):
        """With a small CT the beam line, not the patient, sets the world size."""
        ct = _headphantom_ct()
        hl = TopasText.world_half_lengths(ct, (0.0, -170.16, -2.12), beam_reach=500.0)
        assert hl == pytest.approx((500.0 + WORLD_MARGIN,) * 3)

    def test_world_without_ct(self):
        hl = TopasText.world_half_lengths(beam_reach=500.0)
        assert hl == pytest.approx((500.0 + WORLD_MARGIN,) * 3)

    def test_world_setup_emits_half_lengths(self):
        text = TopasText.world_setup((1000.0, 1000.0, 1315.4))
        assert "d:Ge/World/HLX             = 1000.00 mm" in text
        assert "d:Ge/World/HLZ             = 1315.40 mm" in text


class TestDoseCubeBitDepth:
    """At 16 bits TOPAS writes every voxel below ~1.5e-5 of the peak as 0 (issue #111)."""

    def test_default_is_32_bit(self):
        assert 'b:Sc/Dose/DICOMOutput32BitsPerPixel  = "T"' in TopasText.scorer_setup_dicom()

    def test_16_bit_on_request(self):
        text = TopasText.scorer_setup_dicom(dose_cube_16bit=True)
        assert 'b:Sc/Dose/DICOMOutput32BitsPerPixel  = "F"' in text
        assert '"T"' not in text


class TestSetupThreads:
    """Ts/NumberOfThreads is a verbatim pass-through of the TOPAS surface (issue #85).

    TOPAS resolves non-positive values as `cores + nr_threads` on the machine that RUNS
    the file (TsSequenceManager.cc), so no value may be clamped or resolved at export time.
    """

    def test_default_is_all_cores(self):
        assert "i:Ts/NumberOfThreads                    = 0" in TopasText.setup()

    @pytest.mark.parametrize("nr_threads", [0, -1, 1, 4, 28])
    def test_value_reaches_the_input_file(self, nr_threads):
        text = TopasText.setup(nr_threads=nr_threads)
        assert f"i:Ts/NumberOfThreads                    = {nr_threads}" in text


_EMITTANCE_NAMES = ("So/Field/EmittanceParticle", "So/Field/EmittanceEnergy",
                    "So/Field/EmittanceEnergySpread")
_BEAM_NAMES = ("So/Field/BeamParticle", "So/Field/BeamEnergy", "So/Field/BeamEnergySpread")


class TestEmittanceSourceNames:
    """Particle/energy/spread names of the emittance source depend on the TOPAS version (#95).

    OpenTOPAS 4.2 introduced the Emittance* names (Beam* still accepted, with a warning);
    TOPAS 3.9 to 4.1 only know Beam* and abort on Emittance*.
    """

    def test_default_uses_emittance_names(self):
        text = TopasText.field_beam_timefeature()
        assert 's:So/Field/EmittanceParticle         = "proton"' in text
        assert "d:So/Field/EmittanceEnergy           = Tf/Energy/Value MeV" in text
        assert "u:So/Field/EmittanceEnergySpread     = Tf/EnergySpread/Value" in text
        for name in _BEAM_NAMES:
            assert name not in text

    @pytest.mark.parametrize("version", [(4, 2), (4, 3), (5, 0)])
    def test_new_topas_uses_emittance_names(self, version):
        text = TopasText.field_beam_timefeature(topas_version=version)
        for name in _EMITTANCE_NAMES:
            assert name in text
        for name in _BEAM_NAMES:
            assert name not in text

    @pytest.mark.parametrize("version", [(3, 9), (4, 0), (4, 1)])
    def test_old_topas_uses_beam_names(self, version):
        text = TopasText.field_beam_timefeature(topas_version=version)
        assert 's:So/Field/BeamParticle              = "proton"' in text
        assert "d:So/Field/BeamEnergy                = Tf/Energy/Value MeV" in text
        assert "u:So/Field/BeamEnergySpread          = Tf/EnergySpread/Value" in text
        for name in _EMITTANCE_NAMES:
            assert name not in text

    @pytest.mark.parametrize("version", [(3, 9), (4, 3)])
    def test_source_type_and_shape_do_not_depend_on_version(self, version):
        text = TopasText.field_beam_timefeature(topas_version=version)
        assert 's:So/Field/Type                      = "Emittance"' in text
        assert 's:So/Field/Distribution              = "BiGaussian"' in text
        assert "u:So/Field/CorrelationX              = Tf/CorrelationX/Value" in text


class TestParseTopasVersion:

    @pytest.mark.parametrize("text, expected", [
        ("3.9", (3, 9)), ("4.2", (4, 2)), ("4.2.3", (4, 2)), ("4.2.p3", (4, 2)), ("4.10", (4, 10)),
    ])
    def test_accepts(self, text, expected):
        assert parse_topas_version(text) == expected

    @pytest.mark.parametrize("text", ["", "4", "foo", "4.x", "v4.2", "4.2.3.1"])
    def test_rejects(self, text):
        with pytest.raises(argparse.ArgumentTypeError):
            parse_topas_version(text)

    def test_version_compares_numerically(self):
        # (4, 10) must count as newer than (4, 2), which a string compare would get wrong.
        assert parse_topas_version("4.10") >= EMITTANCE_PARAMETER_NAMES_SINCE


class TestPatientDicomDirectory:
    """TOPAS reads the CT series from DicomDirectory without descending into subdirectories."""

    def test_points_at_ct_directory_not_rtdose_directory(self, tmp_path):
        ct_dir = tmp_path / "CT"
        ct_dir.mkdir()
        rd_path = tmp_path / "RD.plan.dcm"
        rd_path.touch()

        text = TopasText.geometry_patient_dicom(rd_path, ct_dir)

        assert f's:Ge/Patient/DicomDirectory          = "{ct_dir.as_posix()}"' in text
        assert f's:Ge/Patient/CloneRTDoseGridFrom     = "{rd_path.as_posix()}"' in text
        # Paths emitted into the TOPAS file must use forward slashes (Windows portability).
        assert "\\" not in text

    def test_falls_back_to_rtdose_directory(self, tmp_path):
        rd_path = tmp_path / "RD.plan.dcm"
        rd_path.touch()

        text = TopasText.geometry_patient_dicom(rd_path)

        assert f's:Ge/Patient/DicomDirectory          = "{tmp_path.as_posix()}"' in text

    def test_relative_paths_pass_through_verbatim(self):
        # Relative-in -> relative-out keeps the study directory relocatable (see #63):
        # no .resolve()-to-absolute step, so no absolute path is baked into the output.
        from pathlib import Path

        rd_path = Path("../dicom/RD.plan.dcm")
        ct_dir = Path("../dicom")

        text = TopasText.geometry_patient_dicom(rd_path, ct_dir)

        assert 's:Ge/Patient/DicomDirectory          = "../dicom"' in text
        assert 's:Ge/Patient/CloneRTDoseGridFrom     = "../dicom/RD.plan.dcm"' in text
