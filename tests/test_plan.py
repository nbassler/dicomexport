import logging
import math
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import mcpl
import numpy as np
import pytest

from dicomexport.model_plan import Plan
from dicomexport.import_plan import load_plan
from dicomexport.import_plan_dicom import _rs_isocenter_distance, _resolve_sad
from dicomexport.beam_model import BeamModel
from dicomexport.export_plan_topas import TopasPlan
from dicomexport.export_spotlist import _plan_to_spot_dataframe, export_spotlist
from pydicom.dataset import Dataset
from pydicom.sequence import Sequence
from tests.dicom_fixtures import write_dicom

TEST_PDG_PROTON = 2212


class TestPlan:
    def test_plan_initialization(self):
        p = Plan()
        assert isinstance(p, Plan)
        assert p.scaling == 1.0
        assert p.n_fields == 0

    def test_plan_fields_list(self):
        p = Plan()
        assert isinstance(p.fields, list)
        assert len(p.fields) == 0

    def test_load_plan_multiple_raises(self, tmp_path):
        sub_a = tmp_path / "sub_a"
        sub_b = tmp_path / "sub_b"
        sub_a.mkdir()
        sub_b.mkdir()
        write_dicom(sub_a / "RN001.dcm", "RTPLAN")
        write_dicom(sub_b / "RN002.dcm", "RTPLAN")
        with pytest.raises(ValueError, match="Multiple plan files"):
            load_plan(tmp_path)

    def test_load_plan_none_found_raises(self, tmp_path):
        write_dicom(tmp_path / "CT001.dcm", "CT", instance_number=1)
        with pytest.raises(FileNotFoundError, match="No plan files found"):
            load_plan(tmp_path)

    def test_load_plan_finds_raystation_rp_prefix(self, tmp_path):
        """RayStation writes RP*.dcm, which the old RN*.dcm glob missed (#77)."""
        write_dicom(tmp_path / "RP001.dcm", "RTPLAN")
        write_dicom(tmp_path / "CT001.dcm", "CT", instance_number=1)
        # The scan selects RP001.dcm; parsing then fails on the minimal fixture,
        # which is enough to prove the file was found rather than invisible.
        with pytest.raises((KeyError, AttributeError, ValueError)):
            load_plan(tmp_path)

    def test_load_plan_still_finds_pld(self, tmp_path):
        """.pld has no Modality tag, so its glob must survive the scan change."""
        (tmp_path / "plan.pld").write_text("not really a pld\n")
        with pytest.raises(Exception) as exc:
            load_plan(tmp_path)
        assert not isinstance(exc.value, FileNotFoundError)


class TestMCPLExport:
    def test_mcpl_export_roundtrip_100(self):
        plan_path = "res/test_plans/temp_160MeV_10x10.dcm"
        bm_path = "res/beam_models/DCPT_beam_model__v2.csv"

        with tempfile.TemporaryDirectory() as td:
            out_path = os.path.join(td, "myoutput.mcpl")

            cmd = [
                sys.executable,
                "dicomexport/main_plan_export.py",
                plan_path, out_path,
                f"-b={bm_path}",
                "--export-fmt=mcpl",
                "-v", "-N=100",
            ]

            env = dict(os.environ)
            env["PYTHONPATH"] = "." + (os.pathsep + env.get("PYTHONPATH", ""))

            result = subprocess.run(
                cmd, env=env,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
            )
            if result.returncode != 0:
                pytest.fail(f"CLI failed\ncmd={cmd}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}")

            out_field = os.path.join(td, "myoutput_field01.mcpl")
            assert os.path.exists(out_field), f"Expected output file not found: {out_field}"

            particles = list(mcpl.MCPLFile(out_field).particles)
            assert len(particles) == 100

            neg_uz = 0
            for i, p in enumerate(particles):
                assert p.pdgcode == TEST_PDG_PROTON
                assert math.isfinite(p.ux) and math.isfinite(p.uy) and math.isfinite(p.uz)
                assert np.isclose(p.ux**2 + p.uy**2 + p.uz**2, 1.0), \
                    f"particle {i}: direction not unit length"
                assert math.isfinite(p.x) and math.isfinite(p.y) and math.isfinite(p.z)
                if p.uz < 0.0:
                    neg_uz += 1

            frac_neg = neg_uz / len(particles)
            assert frac_neg >= 0.99, \
                f"Too many upstream directions: {len(particles) - neg_uz}/{len(particles)} have uz >= 0 " \
                f"(frac_neg={frac_neg:.3f})"


class TestSpotlistExport:
    @pytest.mark.parametrize("col_count", [5, 6, 7, 9, 11])
    def test_spotlist_export(self, col_count):
        plan_path = "res/test_plans/temp_160MeV_10x10.dcm"
        bm_path = "res/beam_models/DCPT_beam_model__v2.csv"

        with tempfile.TemporaryDirectory() as td:
            out_path = os.path.join(td, "myspotlist.dat")

            cmd = [
                sys.executable,
                "dicomexport/main_plan_export.py",
                plan_path, out_path,
                f"-b={bm_path}",
                "--export-fmt=spotlist",
                "-v",
                f"-nc={col_count}",
            ]

            env = dict(os.environ)
            env["PYTHONPATH"] = "." + (os.pathsep + env.get("PYTHONPATH", ""))

            result = subprocess.run(
                cmd, env=env,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
            )
            if result.returncode != 0:
                pytest.fail(f"CLI failed\ncmd={cmd}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}")

            out_field = os.path.join(td, "myspotlist_field01.dat")
            assert os.path.exists(out_field), f"Expected output file not found: {out_field}"

            with open(out_field, encoding="utf-8") as f:
                data_lines = [line for line in f if not line.startswith("#") and line.strip()]

            for line in data_lines:
                cols = line.strip().split()
                assert len(cols) == col_count, \
                    f"Line has {len(cols)} columns, expected {col_count}"


class TestSpotlistExport6ColBM:
    def test_spotlist_export_6col_bm(self):
        """6-column beam model should produce an 11-column spotlist with zeros in divergence/correlation columns."""
        plan_path = "res/test_plans/temp_160MeV_10x10.dcm"
        bm_path = "res/beam_models/bm_test_6col.csv"

        with tempfile.TemporaryDirectory() as td:
            out_path = os.path.join(td, "myspotlist.dat")

            cmd = [
                sys.executable,
                "dicomexport/main_plan_export.py",
                plan_path, out_path,
                f"-b={bm_path}",
                "--export-fmt=spotlist",
                "-v", "-nc=11",
            ]

            env = dict(os.environ)
            env["PYTHONPATH"] = "." + (os.pathsep + env.get("PYTHONPATH", ""))

            result = subprocess.run(
                cmd, env=env,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
            )
            if result.returncode != 0:
                pytest.fail(f"CLI failed\ncmd={cmd}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}")

            out_field = os.path.join(td, "myspotlist_field01.dat")
            assert os.path.exists(out_field), f"Expected output file not found: {out_field}"

            with open(out_field, encoding="utf-8") as f:
                data_lines = [line for line in f if not line.startswith("#") and line.strip()]

            for line in data_lines:
                cols = line.strip().split()
                assert len(cols) == 11, f"Line has {len(cols)} columns, expected 11"
                for i in range(6, 10):
                    assert cols[i] == "0", \
                        f"Expected column {i + 1} to be 0 for 6-column beam model input"


class TestRangeShifterDistance:
    """IsocenterToRangeShifterDistance is positive upstream, but not for every vendor."""

    def test_negative_distance_is_flipped_with_warning(self, caplog):
        rss = {'IsocenterToRangeShifterDistance': -61.5}
        with caplog.at_level(logging.WARNING):
            distance = _rs_isocenter_distance(rss, field_number=2)
        assert distance == pytest.approx(61.5)
        assert "downstream of the isocenter" in caplog.text

    def test_positive_distance_is_kept_without_warning(self, caplog):
        rss = {'IsocenterToRangeShifterDistance': 275.53}
        with caplog.at_level(logging.WARNING):
            distance = _rs_isocenter_distance(rss, field_number=1)
        assert distance == pytest.approx(275.53)
        assert caplog.text == ""

    def test_missing_distance_defaults_to_zero(self):
        assert _rs_isocenter_distance({}, field_number=1) == pytest.approx(0.0)


class TestRangeShifterWET:
    """RangeShifterWaterEquivalentThickness is (300A,0366); 'WaterEquivalentThickness' is not."""

    def test_wet_is_read_from_plan(self):
        plan = load_plan(Path("res") / "test_studies" / "DCPT_headphantom")
        rs = plan.fields[0].range_shifter
        assert rs is not None
        assert rs.water_equivalent_thickness == pytest.approx(57.0)
        assert rs.isocenter_distance == pytest.approx(275.53, abs=0.01)


class TestSourceAxisDistance:
    """Issue #79: SAD must come from VirtualSourceAxisDistances, never default to 0."""

    @staticmethod
    def _beam(vsad=None, lsd=None, device_type="MAGNET"):
        """A stand-in IonBeamSequence item plus its control points."""
        beam = Dataset()
        if vsad is not None:
            beam.VirtualSourceAxisDistances = list(vsad)
        icp = Dataset()
        if lsd is not None:
            devices, settings = [], []
            for number, value in enumerate(lsd, start=1):
                device = Dataset()
                device.LateralSpreadingDeviceNumber = number
                device.LateralSpreadingDeviceType = device_type
                devices.append(device)

                setting = Dataset()
                setting.ReferencedLateralSpreadingDeviceNumber = number
                setting.IsocenterToLateralSpreadingDeviceDistance = value
                settings.append(setting)
            beam.LateralSpreadingDeviceSequence = Sequence(devices)
            icp.LateralSpreadingDeviceSettingsSequence = Sequence(settings)
        return beam, [icp]

    def test_uses_vsad_when_no_spreading_device(self):
        """The #79 case: RayStation PBS writes no lateral spreading device."""
        beam, icps = self._beam(vsad=(2216.5, 1816.0))
        assert _resolve_sad(beam, icps, field_nr=1) == pytest.approx((2216.5, 1816.0))

    def test_vsad_fallback_is_logged(self, caplog):
        beam, icps = self._beam(vsad=(2216.5, 1816.0))
        with caplog.at_level(logging.INFO):
            _resolve_sad(beam, icps, field_nr=1)
        assert "no lateral spreading device in plan" in caplog.text
        assert "VirtualSourceAxisDistances" in caplog.text

    def test_scatterer_is_not_used_as_scanning_pivot(self, caplog):
        """A SCATTERER is not a deflection point; VSAD must win."""
        beam, icps = self._beam(vsad=(2216.5, 1816.0), lsd=(1000.0, 1000.0),
                                device_type="SCATTERER")
        with caplog.at_level(logging.INFO):
            sad = _resolve_sad(beam, icps, field_nr=1)
        assert sad == pytest.approx((2216.5, 1816.0))
        assert "not a deflection magnet" in caplog.text

    def test_falls_back_to_lateral_spreading_device(self):
        """Plans predating the required tag, or with it unusable, still work."""
        beam, icps = self._beam(vsad=None, lsd=(2000.0, 2560.0))
        assert _resolve_sad(beam, icps, field_nr=1) == pytest.approx((2000.0, 2560.0))

    def test_agreeing_sources_do_not_warn(self, caplog):
        """The DCPT case: the magnet distance duplicates the required tag."""
        beam, icps = self._beam(vsad=(2000.0, 2560.0), lsd=(2000.0, 2560.0))
        with caplog.at_level(logging.WARNING):
            sad = _resolve_sad(beam, icps, field_nr=1)
        assert sad == pytest.approx((2000.0, 2560.0))
        assert "disagree" not in caplog.text

    def test_disagreeing_sources_warn_and_prefer_the_magnet(self, caplog):
        """An explicitly named deflection magnet beats the derived virtual source."""
        beam, icps = self._beam(vsad=(2216.5, 1816.0), lsd=(2000.0, 2560.0))
        with caplog.at_level(logging.WARNING):
            sad = _resolve_sad(beam, icps, field_nr=1)
        assert sad == pytest.approx((2000.0, 2560.0))
        assert "disagree" in caplog.text
        assert "Using the deflection magnets" in caplog.text

    def test_pydicom_collapses_single_valued_vsad(self):
        """Pin the pydicom behaviour the VM=1 case above relies on.

        A one-element assignment reads back as a bare float, not a length-1 sequence.
        That is what makes a malformed single-valued tag land in the "not numeric"
        branch rather than the length check, so if pydicom ever changes it this test
        fails first and explains why the other one did.
        """
        beam, _ = self._beam(vsad=(2216.5,))
        assert isinstance(beam.VirtualSourceAxisDistances, float)

        beam, _ = self._beam(vsad=(2216.5, 1816.0))
        assert len(beam.VirtualSourceAxisDistances) == 2

    def test_no_source_raises(self):
        """The #79 failure: neither source present must abort, not yield 0.0."""
        beam, icps = self._beam(vsad=None, lsd=None)
        with pytest.raises(ValueError, match="no usable source-to-axis distance"):
            _resolve_sad(beam, icps, field_nr=3)

    @pytest.mark.parametrize("bad", [(0.0, 1816.0), (2216.5, 0.0), (-1.0, -1.0)])
    def test_non_positive_vsad_is_rejected(self, bad):
        beam, icps = self._beam(vsad=bad)
        with pytest.raises(ValueError, match="no usable source-to-axis distance"):
            _resolve_sad(beam, icps, field_nr=1)

    @pytest.mark.parametrize("bad_vsad,expected_warning", [
        # Three values: read back as a MultiValue, caught by the length check.
        ((2216.5, 1816.0, 900.0), "should have 2 values"),
        # One value: pydicom collapses it to a bare float on read-back regardless of
        # being assigned as a list, so iterating it raises TypeError and the "not
        # numeric" branch catches it. See test_pydicom_collapses_single_valued_vsad.
        ((2216.5,), "not numeric"),
    ])
    def test_malformed_vsad_falls_back(self, caplog, bad_vsad, expected_warning):
        beam, icps = self._beam(vsad=bad_vsad, lsd=(2000.0, 2560.0))
        with caplog.at_level(logging.WARNING):
            sad = _resolve_sad(beam, icps, field_nr=1)
        assert sad == pytest.approx((2000.0, 2560.0))
        assert expected_warning in caplog.text

    def test_real_plan_sad_is_populated(self):
        """End-to-end: the bundled DCPT plan carries SAD on every field."""
        plan = load_plan(Path("res") / "test_plans" / "temp_160MeV_10x10.dcm")
        for field in plan.fields:
            assert field.sad == pytest.approx((2000.0, 2560.0))


class TestTopasRejectsZeroSad:
    """Defence in depth: a zero SAD must never reach the divergence maths (#79)."""

    def test_zero_sad_raises_instead_of_writing_inf(self, tmp_path):
        plan = load_plan(Path("res") / "test_plans" / "temp_160MeV_10x10.dcm")
        plan.beam_model = BeamModel(Path("res") / "beam_models" / "DCPT_beam_model__v2.csv")
        plan.apply_beammodel()
        field = plan.fields[0]
        field.sad = (0.0, 0.0)              # simulate the pre-fix state

        with pytest.raises(ValueError, match="source-to-axis distance must be finite and positive"):
            TopasPlan.time_features_string(field, plan.beam_model, nstat=1000)


class TestBackprojectionUsesSad:
    """All exporters that place spots at the beam-model plane need SAD (#79)."""

    @staticmethod
    def _plan(path):
        plan = load_plan(path)
        plan.beam_model = BeamModel(Path("res") / "beam_models" / "DCPT_beam_model__v2.csv")
        plan.apply_beammodel()
        return plan

    def test_spotlist_backprojects_from_field_sad(self):
        """Backprojection must follow Field.sad, the single source of truth."""
        plan = self._plan(Path("res") / "test_plans" / "temp_160MeV_10x10.dcm")
        field = plan.fields[0]

        df = _plan_to_spot_dataframe(plan)
        d = df[(df.field == 1) & (df.x_iso_mm.abs() > 1.0)]

        assert not d.empty
        bm = plan.beam_model
        assert bm is not None            # _plan() always attaches one
        # Backprojected positions must be scaled by (sad - D)/sad, not copied.
        expected = (field.sad[0] - bm.beam_model_position) / field.sad[0]
        assert (d.x_bm_mm / d.x_iso_mm).mean() == pytest.approx(expected, rel=1e-6)

    def test_spotlist_falls_back_to_parallel_without_sad(self, caplog):
        """PLD and RST plans carry no SAD; the parallel assumption must be announced."""
        plan = self._plan(Path("res") / "test_plans" / "temp_160MeV_10x10.dcm")
        for field in plan.fields:
            field.sad = (0.0, 0.0)

        with caplog.at_level(logging.WARNING):
            df = _plan_to_spot_dataframe(plan)

        assert "assuming parallel beam" in caplog.text
        d = df[df.field == 1]
        assert (d.x_bm_mm == d.x_iso_mm).all()

    def test_spotlist_requires_a_beam_model_position(self, tmp_path):
        """Backprojection needs D; the error must name the cause, not fail deeper in."""
        plan = self._plan(Path("res") / "test_plans" / "temp_160MeV_10x10.dcm")
        plan.beam_model = None
        with pytest.raises(ValueError, match="beam_model_position must be set"):
            export_spotlist(plan, str(tmp_path / "s.txt"))


class TestSadValidationEdgeCases:
    """Guards that a plain positivity test would miss (#79 review)."""

    def test_scatterer_alone_raises(self):
        """A scatterer is not a scanning pivot, even when there is nothing else."""
        beam, icps = TestSourceAxisDistance._beam(
            vsad=None, lsd=(1000.0, 1000.0), device_type="SCATTERER")
        with pytest.raises(ValueError, match="not a deflection magnet"):
            _resolve_sad(beam, icps, field_nr=1)

    def test_magnet_alone_is_still_accepted(self):
        """The fallback must stay open for magnets, only closed for other devices."""
        beam, icps = TestSourceAxisDistance._beam(vsad=None, lsd=(2000.0, 2560.0))
        assert _resolve_sad(beam, icps, field_nr=1) == pytest.approx((2000.0, 2560.0))

    @pytest.mark.parametrize("bad", [
        (float("nan"), 1816.0), (2216.5, float("nan")),
        (float("inf"), 1816.0), (2216.5, float("inf")),
    ])
    def test_non_finite_vsad_is_rejected(self, bad):
        """nan fails '<= 0.0' and inf passes it, so both need an explicit check."""
        beam, icps = TestSourceAxisDistance._beam(vsad=bad)
        with pytest.raises(ValueError, match="no usable source-to-axis distance"):
            _resolve_sad(beam, icps, field_nr=1)

    @pytest.mark.parametrize("bad", [(float("nan"), 2560.0), (float("inf"), 2560.0)])
    def test_non_finite_magnet_distance_is_rejected(self, bad):
        beam, icps = TestSourceAxisDistance._beam(vsad=None, lsd=bad)
        with pytest.raises(ValueError, match="no usable source-to-axis distance"):
            _resolve_sad(beam, icps, field_nr=1)

    @pytest.mark.parametrize("bad", [(float("nan"), 2560.0), (float("inf"), 2560.0)])
    def test_topas_rejects_non_finite_sad(self, bad):
        plan = load_plan(Path("res") / "test_plans" / "temp_160MeV_10x10.dcm")
        plan.beam_model = BeamModel(Path("res") / "beam_models" / "DCPT_beam_model__v2.csv")
        plan.apply_beammodel()
        field = plan.fields[0]
        field.sad = bad
        with pytest.raises(ValueError, match="must be finite and positive"):
            TopasPlan.time_features_string(field, plan.beam_model, nstat=1000)

    @pytest.mark.parametrize("bad", [(float("nan"), 2560.0), (float("inf"), 2560.0)])
    def test_spotlist_treats_non_finite_sad_as_parallel(self, bad, caplog):
        plan = load_plan(Path("res") / "test_plans" / "temp_160MeV_10x10.dcm")
        plan.beam_model = BeamModel(Path("res") / "beam_models" / "DCPT_beam_model__v2.csv")
        plan.apply_beammodel()
        for field in plan.fields:
            field.sad = bad
        with caplog.at_level(logging.WARNING):
            df = _plan_to_spot_dataframe(plan)
        assert "assuming parallel beam" in caplog.text
        assert df["x_bm_mm"].notna().all()
        assert (df["x_bm_mm"] == df["x_iso_mm"]).all()

    @pytest.mark.parametrize("bad", [0.0, -500.0, float("nan"), float("inf")])
    def test_spotlist_rejects_bad_beam_model_position(self, tmp_path, bad):
        """Must fail before announcing an export plane; nan used to slip through."""
        plan = load_plan(Path("res") / "test_plans" / "temp_160MeV_10x10.dcm")
        bm = BeamModel(Path("res") / "beam_models" / "DCPT_beam_model__v2.csv")
        plan.beam_model = bm
        plan.apply_beammodel()
        bm.beam_model_position = bad
        with pytest.raises(ValueError, match="finite positive distance"):
            export_spotlist(plan, str(tmp_path / "s.txt"))
        assert not list(tmp_path.iterdir())
