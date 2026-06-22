from pathlib import Path

from dicomexport.model_ct import CTModel
from dicomexport.import_ct import load_ct

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
