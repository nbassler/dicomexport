from pathlib import Path

import pytest

from dicomexport.model_rtstruct import RTStruct
from dicomexport.import_rtstruct import load_rs

CT_TEST_DIR = Path("res") / "test_studies" / "DCPT_headphantom"
CT_TEST_FILE = CT_TEST_DIR / "RS.1.2.246.352.205.5439556202947041733.367077883804944283.dcm"

PT_NAME = "E2E_test^ProcedureGroup1"
PT_ID = "E2E_test_PG1_1"
N_ROIS = 11
ROI_NAME = "BODY"


class TestRTStruct:
    def test_rts_initialization(self):
        rts = RTStruct()
        assert isinstance(rts, RTStruct)
        assert rts.patient_id == ""
        assert rts.patient_name == ""

    def test_rts_load_file(self):
        rts = load_rs(CT_TEST_FILE)
        assert isinstance(rts, RTStruct)
        assert rts.patient_name == PT_NAME
        assert rts.patient_id == PT_ID
        assert rts.n_rois == N_ROIS
        assert rts.rois[0].roi_name == ROI_NAME

    def test_rts_load_directory(self):
        rts = load_rs(CT_TEST_DIR)
        assert isinstance(rts, RTStruct)
        assert rts.patient_name == PT_NAME
        assert rts.patient_id == PT_ID
        assert rts.n_rois == N_ROIS
        assert rts.rois[0].roi_name == ROI_NAME

    def test_rts_multiple_raises(self, tmp_path):
        (tmp_path / "RS001.dcm").touch()
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "RS002.dcm").touch()
        with pytest.raises(ValueError, match="Multiple RTSTRUCT"):
            load_rs(tmp_path)
