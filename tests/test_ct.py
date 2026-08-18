from pathlib import Path

import pytest

from dicomexport.model_ct import CTModel
from dicomexport.import_ct import load_ct, get_ct_files_sorted_by_instance_number
from tests.dicom_fixtures import (write_dicom, write_ct_series, write_dicomdir,
                                  OTHER_STUDY_UID, OTHER_SERIES_UID, OTHER_FRAME_UID)

CT_TEST_PATH = Path("res") / "test_studies" / "DCPT_headphantom"


class TestCT:
    def test_ct_initialization(self):
        ct = CTModel()
        assert isinstance(ct, CTModel)
        assert ct.patient_name == ""
        assert ct.rows == 0
        assert ct.dicom_origin == (0.0, 0.0, 0.0)
        assert ct.full_widths == (0.0, 0.0, 0.0)

    def test_ct_load(self):
        ct = load_ct(CT_TEST_PATH)
        assert isinstance(ct, CTModel)
        assert ct.images is not None
        assert ct.patient_id is not None
        assert ct.patient_name is not None

    def test_ct_extent(self):
        ct = load_ct(CT_TEST_PATH)
        assert ct.n_slices == 177
        assert ct.voxel_size == pytest.approx((0.5859375, 0.5859375, 1.5))
        assert ct.full_widths == pytest.approx((300.0, 300.0, 265.5))
        assert ct.half_widths == pytest.approx((150.0, 150.0, 132.75))

    def test_ct_dicom_origin(self):
        """The CT centre in DICOM coordinates, as TOPAS' TsDicomPatient computes it.

        Cross-checked against OpenTOPAS 4.2.3: for an isocenter of (0, -170.16, -2.12) mm
        it places this patient at "Iso Center [cm]: ( 0, 0.366, -0.488 )", i.e. at
        dicom_origin - isocenter.
        """
        ct = load_ct(CT_TEST_PATH)
        assert ct.dicom_origin == pytest.approx((0.0, -166.5, -7.0))

    def test_ct_multiple_subdirs_raises(self, tmp_path):
        write_ct_series(tmp_path / "ct_a", n=1, start=1)
        write_ct_series(tmp_path / "ct_b", n=1, start=2)
        with pytest.raises(ValueError, match="multiple subdirectories under"):
            get_ct_files_sorted_by_instance_number(tmp_path)

    def test_ct_single_subdir_found(self, tmp_path):
        sub = tmp_path / "ct_images"
        write_ct_series(sub, n=2)

        files = get_ct_files_sorted_by_instance_number(tmp_path)

        assert len(files) == 2
        assert all(f.parent == sub for f in files)

    def test_ct_sorted_by_instance_number_not_filename(self, tmp_path):
        """Filename order and InstanceNumber order disagree; InstanceNumber wins."""
        sub = tmp_path / "ct"
        sub.mkdir()
        write_dicom(sub / "aaa.dcm", "CT", instance_number=3)
        write_dicom(sub / "bbb.dcm", "CT", instance_number=1)
        write_dicom(sub / "ccc.dcm", "CT", instance_number=2)

        files = get_ct_files_sorted_by_instance_number(tmp_path)

        assert [f.name for f in files] == ["bbb.dcm", "ccc.dcm", "aaa.dcm"]

    def test_ct_missing_instance_number_raises(self, tmp_path):
        sub = tmp_path / "ct"
        sub.mkdir()
        write_dicom(sub / "CT001.dcm", "CT", instance_number=1)
        write_dicom(sub / "CT002.dcm", "CT", instance_number=None)
        with pytest.raises(AttributeError, match="InstanceNumber"):
            get_ct_files_sorted_by_instance_number(tmp_path)

    def test_ct_ignores_other_modalities(self, tmp_path):
        """A structure set named CTV.dcm must not be handed to the CT reader (#77)."""
        sub = tmp_path / "ct"
        write_ct_series(sub, n=2)
        write_dicom(sub / "CTV.dcm", "RTSTRUCT")

        files = get_ct_files_sorted_by_instance_number(tmp_path)

        assert [f.name for f in files] == ["CT001.dcm", "CT002.dcm"]

    def test_ct_finds_files_without_dcm_suffix(self, tmp_path):
        """PACS exports ship bare SOP Instance UIDs with no suffix (#77)."""
        sub = tmp_path / "ct"
        sub.mkdir()
        write_dicom(sub / "1.2.840.113619.2.55.1", "CT", instance_number=1)
        write_dicom(sub / "1.2.840.113619.2.55.2", "CT", instance_number=2)

        files = get_ct_files_sorted_by_instance_number(tmp_path)

        assert len(files) == 2

    @pytest.mark.parametrize("keep", [200, 500])
    def test_ct_truncated_slice_raises(self, tmp_path, keep):
        """A slice truncated before its Modality tag must abort, not vanish (#77)."""
        sub = tmp_path / "ct"
        write_ct_series(sub, n=2)
        real = sorted(CT_TEST_PATH.glob("CT*.dcm"))[0]
        (sub / "CT003.dcm").write_bytes(real.read_bytes()[:keep])

        with pytest.raises(ValueError, match="could not be read as DICOM"):
            get_ct_files_sorted_by_instance_number(tmp_path)

    def test_ct_dicomdir_is_not_mistaken_for_damage(self, tmp_path):
        """A DICOMDIR has no Modality by design; PACS exports routinely ship one."""
        sub = tmp_path / "ct"
        write_ct_series(sub, n=2)
        write_dicomdir(sub / "DICOMDIR")

        files = get_ct_files_sorted_by_instance_number(tmp_path)

        assert len(files) == 2

    def test_ct_two_series_in_one_directory_raises(self, tmp_path):
        """The case the parent-dir guard misses: two CT series side by side (#77)."""
        sub = tmp_path / "ct"
        write_ct_series(sub, n=2, start=1)
        write_ct_series(sub, n=2, start=3, series_uid=OTHER_SERIES_UID)

        with pytest.raises(ValueError, match="more than one CT series"):
            get_ct_files_sorted_by_instance_number(tmp_path)

    def test_ct_two_patients_raises(self, tmp_path):
        sub = tmp_path / "ct"
        write_ct_series(sub, n=2, start=1)
        write_dicom(sub / "other.dcm", "CT", instance_number=3, patient_id="SOMEONE_ELSE")

        with pytest.raises(ValueError, match="more than one patient"):
            get_ct_files_sorted_by_instance_number(tmp_path)

    def test_ct_two_studies_raises(self, tmp_path):
        sub = tmp_path / "ct"
        write_ct_series(sub, n=2, start=1)
        write_dicom(sub / "plan.dcm", "RTPLAN", study_uid=OTHER_STUDY_UID)

        with pytest.raises(ValueError, match="more than one study"):
            get_ct_files_sorted_by_instance_number(tmp_path)

    def test_ct_mismatched_frame_of_reference_raises(self, tmp_path):
        """A structure set from a different frame of reference would not line up."""
        sub = tmp_path / "ct"
        write_ct_series(sub, n=2)
        write_dicom(sub / "RS001.dcm", "RTSTRUCT", frame_uid=OTHER_FRAME_UID)

        with pytest.raises(ValueError, match="frame of reference"):
            get_ct_files_sorted_by_instance_number(tmp_path)

    def test_ct_missing_identity_tag_is_not_a_mismatch(self, tmp_path):
        """A vendor omitting FrameOfReferenceUID on RTDOSE must not trip the check."""
        sub = tmp_path / "ct"
        write_ct_series(sub, n=2)
        write_dicom(sub / "RD001.dcm", "RTDOSE", frame_uid="")

        files = get_ct_files_sorted_by_instance_number(tmp_path)

        assert len(files) == 2

    def test_ct_real_study_passes_consistency(self):
        """The bundled study must satisfy every check, not merely avoid crashing."""
        files = get_ct_files_sorted_by_instance_number(CT_TEST_PATH)
        assert len(files) == 177

    def test_ct_non_dicom_files_are_ignored(self, tmp_path):
        """Unrelated files must not trip the damaged-slice abort, whatever they are named."""
        sub = tmp_path / "ct"
        write_ct_series(sub, n=2)
        (sub / "README.md").write_text("notes")
        (sub / "beam_model.csv").write_text("70,71.38,1.23,2106924,4.472,3.629\n")
        (sub / "no_suffix_at_all").write_text("just text")
        # Named like DICOM but isn't: content decides, not the name.
        (sub / "decoy.dcm").write_text("not dicom either")

        files = get_ct_files_sorted_by_instance_number(tmp_path)

        assert len(files) == 2
