from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from dicomexport.model_ct import CTModel
from dicomexport.import_ct import load_ct, get_ct_files_sorted_by_instance_number

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
        sub_a = tmp_path / "ct_a"
        sub_b = tmp_path / "ct_b"
        sub_a.mkdir()
        sub_b.mkdir()
        (sub_a / "CT001.dcm").touch()
        (sub_b / "CT002.dcm").touch()
        with pytest.raises(ValueError, match="multiple subdirectories under"):
            get_ct_files_sorted_by_instance_number(tmp_path)

    def test_ct_single_subdir_found(self, tmp_path):
        sub = tmp_path / "ct_images"
        sub.mkdir()
        (sub / "CT001.dcm").touch()
        (sub / "CT002.dcm").touch()

        def fake_dcmread(path, stop_before_pixels=False):
            ds = MagicMock()
            ds.InstanceNumber = int(path.stem[-1])
            return ds

        with patch("dicomexport.import_ct.pydicom.dcmread", side_effect=fake_dcmread):
            files = get_ct_files_sorted_by_instance_number(tmp_path)

        assert len(files) == 2
        assert all(f.parent == sub for f in files)
