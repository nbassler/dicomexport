"""Fields are selected and named by DICOM BeamNumber, never by plan position (issue #96)."""
import logging
from pathlib import Path

import pytest

import dicomexport.main as study
import dicomexport.main_plan_export as plan_export
from dicomexport.model_plan import Field, Plan
from tests.dicom_fixtures import make_ccb_style_plan

SOURCE_PLAN = Path("res") / "test_plans" / "temp_160MeV_10x10.dcm"
BEAM_MODEL = "res/beam_models/DCPT_beam_model__v2.csv"
SPR_TABLE = "res/spr_tables/SPRtoMaterial__Brain.txt"
STUDY = "res/test_studies/DCPT_headphantom/"

# BeamNumbers that are neither 1..N nor equal to their position in the plan.
SPARSE_NUMBERS = (3, 7, 12)


def _plan(*numbers):
    return Plan(fields=[Field(number=n, name=f"Beam{n}") for n in numbers])


class TestSelectFields:

    def test_none_selects_every_field_in_plan_order(self):
        plan = _plan(12, 3, 7)
        assert [f.number for f in plan.select_fields(None)] == [12, 3, 7]

    def test_selects_by_beam_number_not_position(self):
        plan = _plan(*SPARSE_NUMBERS)
        assert [f.number for f in plan.select_fields([7])] == [7]
        assert [f.number for f in plan.select_fields([12, 3])] == [3, 12]

    def test_unknown_beam_number_lists_the_valid_ones(self):
        with pytest.raises(ValueError, match=r"BeamNumber 2 .*Valid BeamNumbers: 3, 7, 12"):
            _plan(*SPARSE_NUMBERS).select_fields([2])

    @pytest.mark.parametrize("number, label", [(1, "field01"), (12, "field12"), (123, "field123")])
    def test_label_is_the_zero_padded_beam_number(self, number, label):
        assert Field(number=number).label == label


def test_pld_field_is_beam_number_1(tmp_path):
    """A PLD holds one field and no beam number; it used to come out as field00."""
    from dicomexport.import_plan_pld import load_plan_pld
    pld = tmp_path / "plan.pld"
    pld.write_text("Beam,ID,Name,In,First,Plan,LAO 45,100.0,1.0,1\n"
                   "Layer,3.0,150.0,100.0,1,0\n"
                   "Element,0.0,0.0,100.0,0\n")
    plan = load_plan_pld(pld)
    assert [(f.number, f.name, f.label) for f in plan.fields] == [(1, "LAO 45", "field01")]


@pytest.fixture
def sparse_plan(tmp_path):
    return make_ccb_style_plan(SOURCE_PLAN, tmp_path / "sparse.dcm",
                               ref_order=SPARSE_NUMBERS, with_delivery=SPARSE_NUMBERS)


class TestPlanExport:

    @pytest.mark.parametrize("fmt, suffix", [("topas", ".txt"), ("spotlist", ".txt"), ("mcpl", ".mcpl")])
    def test_f_selects_the_beam_number(self, tmp_path, sparse_plan, fmt, suffix):
        out = tmp_path / f"out{suffix}"
        assert plan_export.main([str(sparse_plan), str(out), "-b", BEAM_MODEL, "-f", "7",
                                 "--export-fmt", fmt, "-N", "10000"]) == 0
        assert sorted(p.name for p in tmp_path.glob(f"out_field*{suffix}")) == [f"out_field07{suffix}"]

    @pytest.mark.parametrize("fmt, suffix", [("topas", ".txt"), ("spotlist", ".txt"), ("mcpl", ".mcpl")])
    def test_negative_beam_number_is_selected_like_any_other(self, tmp_path, fmt, suffix):
        """DICOM only requires BeamNumbers to be unique; every format must honour -f the same way."""
        import pydicom
        plan = make_ccb_style_plan(SOURCE_PLAN, tmp_path / "negative.dcm",
                                   ref_order=(-3, 7), with_delivery=(-3, 7))
        # The fixture derives the meterset from the number (1000 * n); keep it positive.
        ds = pydicom.dcmread(plan)
        for ref in ds.FractionGroupSequence[0].ReferencedBeamSequence:
            ref.BeamMeterset = abs(ref.BeamMeterset)
        ds.save_as(plan)
        out = tmp_path / f"out{suffix}"
        assert plan_export.main([str(plan), str(out), "-b", BEAM_MODEL, "--field=-3",
                                 "--export-fmt", fmt, "-N", "10000"]) == 0
        assert sorted(p.name for p in tmp_path.glob(f"out_field*{suffix}")) == [f"out_field-3{suffix}"]

    def test_header_carries_beam_number_and_name(self, tmp_path, sparse_plan):
        out = tmp_path / "out.txt"
        assert plan_export.main([str(sparse_plan), str(out), "-b", BEAM_MODEL, "-f", "12"]) == 0
        text = (tmp_path / "out_field12.txt").read_text()
        assert "# BEAM_NUMBER: 12\n" in text
        assert "# BEAM_NAME: Beam12\n" in text

    def test_all_fields_are_named_by_beam_number(self, tmp_path, sparse_plan):
        assert plan_export.main([str(sparse_plan), str(tmp_path / "out.txt"), "-b", BEAM_MODEL]) == 0
        assert sorted(p.name for p in tmp_path.glob("out_field*.txt")) == [
            "out_field03.txt", "out_field07.txt", "out_field12.txt"]

    def test_unknown_beam_number_fails_without_output(self, tmp_path, sparse_plan, caplog):
        with caplog.at_level(logging.ERROR):
            rc = plan_export.main([str(sparse_plan), str(tmp_path / "out.txt"), "-b", BEAM_MODEL, "-f", "2"])
        assert rc == 2
        assert "Valid BeamNumbers: 3, 7, 12" in caplog.text
        assert not list(tmp_path.glob("out_field*"))


class TestStudyExport:
    """The study CLI used to index plan.fields[-f], so -f 1 exported field 2 (issue #96)."""

    @pytest.mark.parametrize("beam", [1, 3])
    def test_f_selects_the_beam_number(self, tmp_path, beam):
        out = tmp_path / "topas.txt"
        assert study.main(["-b", BEAM_MODEL, "-s", SPR_TABLE, "-f", str(beam), STUDY, str(out)]) == 0
        assert sorted(p.name for p in tmp_path.glob("topas_field*.txt")) == [f"topas_field{beam:02d}.txt"]
        text = (tmp_path / f"topas_field{beam:02d}.txt").read_text()
        assert f"# BEAM_NUMBER: {beam}\n" in text
        assert f"# BEAM_NAME: Field {beam}\n" in text

    def test_dose_output_has_the_same_name_as_the_input_file(self, tmp_path):
        out = tmp_path / "topas.txt"
        assert study.main(["-b", BEAM_MODEL, "-s", SPR_TABLE, "-f", "2", STUDY, str(out)]) == 0
        text = (tmp_path / "topas_field02.txt").read_text()
        assert 's:Sc/Dose/OutputFile                 = "topas_field02"' in text

    def test_unknown_beam_number_fails_without_output(self, tmp_path, caplog):
        with caplog.at_level(logging.ERROR):
            rc = study.main(["-b", BEAM_MODEL, "-s", SPR_TABLE, "-f", "4", STUDY, str(tmp_path / "topas.txt")])
        assert rc == 2
        assert "Valid BeamNumbers: 1, 2, 3" in caplog.text
        assert not list(tmp_path.glob("topas_field*"))
