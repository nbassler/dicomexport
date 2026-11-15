from pathlib import Path

import pytest

import dicomexport.main_geo_export as geo

DICOM_TEST_DIR = Path("res/test_studies/DCPT_headphantom/")
RS_FILE = DICOM_TEST_DIR / "RS.1.2.246.352.205.5439556202947041733.367077883804944283.dcm"


@pytest.mark.parametrize("extra_args, flag", [([], "T"), (["--dose-cube-16bit"], "F")])
def test_dose_cube_bit_depth(tmp_path, extra_args, flag):
    """geo-export writes the dose cube 32-bit unless --dose-cube-16bit is given (#111)."""
    fout = tmp_path / "geometry.txt"
    assert geo.main(extra_args + [str(DICOM_TEST_DIR), str(RS_FILE), str(fout)]) == 0
    assert f'b:Sc/Dose/DICOMOutput32BitsPerPixel  = "{flag}"' in fout.read_text()
