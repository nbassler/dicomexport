from pathlib import Path

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

    def test_ct_load(self):
        ct = load_ct(CT_TEST_PATH)
        assert isinstance(ct, CTModel)
        assert ct.images is not None
        assert ct.patient_id is not None
        assert ct.patient_name is not None

    def test_ct_multiple_subdirs_raises(self, tmp_path):
        sub_a = tmp_path / "ct_a"
        sub_b = tmp_path / "ct_b"
        sub_a.mkdir()
        sub_b.mkdir()
        (sub_a / "CT001.dcm").touch()
        (sub_b / "CT002.dcm").touch()
        with pytest.raises(ValueError, match="multiple subdirectories"):
            get_ct_files_sorted_by_instance_number(tmp_path)

    def test_ct_single_subdir_glob(self, tmp_path):
        sub = tmp_path / "ct_images"
        sub.mkdir()
        (sub / "CT001.dcm").touch()
        (sub / "CT002.dcm").touch()
        files = list(tmp_path.glob("**/CT*.dcm"))
        assert len(files) == 2
