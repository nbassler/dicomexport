from pathlib import Path

import pytest

from dicomexport.model_rtstruct import RTStruct
from dicomexport.import_rtstruct import load_rs
from dicomexport.dicom_scan import RTSTRUCT, scan_study
from tests.dicom_fixtures import write_dicom

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
        write_dicom(tmp_path / "RS001.dcm", "RTSTRUCT")
        sub = tmp_path / "sub"
        sub.mkdir()
        write_dicom(sub / "RS002.dcm", "RTSTRUCT")
        with pytest.raises(ValueError, match="Multiple RTSTRUCT"):
            load_rs(tmp_path)

    def test_rts_found_by_modality_not_filename(self, tmp_path):
        """A structure set under any name must be found; CT files must not confuse it."""
        expected = write_dicom(tmp_path / "1.2.840.113619.99", "RTSTRUCT")
        write_dicom(tmp_path / "CT001.dcm", "CT", instance_number=1)

        # Assert on selection rather than on how far parsing gets, so the test does
        # not break when RTSTRUCT parsing changes. The old RS*.dcm glob found nothing
        # in this layout.
        assert scan_study(tmp_path).get(RTSTRUCT) == [expected]

    def test_rts_load_does_not_report_missing_file(self, tmp_path):
        """Whatever else fails on a stub, it must not be 'no RTSTRUCT found'."""
        write_dicom(tmp_path / "1.2.840.113619.99", "RTSTRUCT")
        with pytest.raises(Exception) as exc:
            load_rs(tmp_path)
        assert not isinstance(exc.value, FileNotFoundError)

    def test_rts_none_found_raises(self, tmp_path):
        write_dicom(tmp_path / "CT001.dcm", "CT", instance_number=1)
        with pytest.raises(FileNotFoundError, match="No RTSTRUCT files found"):
            load_rs(tmp_path)
