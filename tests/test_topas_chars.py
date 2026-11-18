"""Paths and names written as TOPAS values must be readable by TOPAS (issue #130)."""
import os
from pathlib import Path

import pytest

from dicomexport.config import DEFAULTS_DIR, find_config_dir, init_config_dir
from dicomexport.export_study_topas import check_topas_values, export_study_topas
from dicomexport.import_ct import load_ct
from dicomexport.import_plan import load_plan
from dicomexport.import_rtstruct import load_rs
from dicomexport.material_override import MaterialOverride
from dicomexport.model_ct import CTModel
from dicomexport.model_rtstruct import RTStruct
from dicomexport.main import main as study_main
from dicomexport.topas_chars import check_include_path, check_topas_value, unsafe_char

STUDY = Path(__file__).parent.parent / "res" / "test_studies" / "DCPT_headphantom"


@pytest.mark.parametrize("text", ["a=b", "a#b", "a?b", "a'b", "a`b", 'a"b', "a\u2013b", "a\u201cb", "a\nb"])
def test_unsafe(text):
    assert unsafe_char(text) == text[1]


@pytest.mark.parametrize("text", ["/data/study 1/RD.dcm", "C:/Users/x/study-1", "G4_A-150_TISSUE", "Markør"])
def test_safe(text):
    assert unsafe_char(text) is None


def test_the_message_names_what_and_the_character():
    with pytest.raises(ValueError, match="TOPAS cannot read the RTDOSE file /x#1/RD.dcm.*'#'"):
        check_topas_value("/x#1/RD.dcm", "RTDOSE file")


def test_an_S_path_is_not_checked(tmp_path):
    """-S writes the path only into comment lines."""
    f = tmp_path / "x#1.txt"
    f.write_text("d:Ma/X/Density = 1 g/cm3\n")
    assert find_config_dir().include(str(f), inline=True).inline


def test_the_output_name(tmp_path, caplog):
    assert study_main([str(STUDY), str(tmp_path / "run=2.txt"), "-f", "1", "-N", "1000", "--batches", "1"]) == 2
    assert "output name" in caplog.text
    assert not list(tmp_path.iterdir())


def test_the_study_directory(tmp_path, caplog):
    link = tmp_path / "study#1"
    try:
        os.symlink(STUDY, link, target_is_directory=True)
    except OSError:
        pytest.skip("cannot create a symbolic link here")
    assert study_main([str(link), str(tmp_path / "topas.txt"), "-f", "1", "-N", "1000", "--batches", "1"]) == 2
    assert "CT directory (DicomDirectory)" in caplog.text
    assert not list(tmp_path.glob("topas*"))


ARGS = ["-f", "1", "-N", "1000", "--batches", "1"]


@pytest.mark.parametrize("path", ["calibration table.txt", "/x/my tables/HU.txt"])
def test_includefile_is_split_at_whitespace(path):
    """includeFile is not quoted: TOPAS splits it into several files at whitespace."""
    with pytest.raises(ValueError, match="splits includeFile at whitespace.*-S"):
        check_include_path(path)


def test_includefile_is_not_split_at_a_non_breaking_space():
    """G4Tokenizer splits at space, tab and newline only; OpenTOPAS 4.3.0 opens such a file."""
    check_include_path("/x/calibration\u00a0table.txt")


def test_an_s_path(tmp_path, caplog):
    table = tmp_path / "calibration table.txt"
    table.write_bytes((DEFAULTS_DIR / "ct_to_material" / "HUtoMaterialSchneider.txt").read_bytes())
    assert study_main([str(STUDY), str(tmp_path / "topas.txt"), *ARGS, "-s", str(table)]) == 2
    assert "splits includeFile at whitespace" in caplog.text
    assert not list(tmp_path.glob("topas*"))


def test_the_default_table_of_a_configuration_directory(tmp_path, caplog):
    """No -s or -S: the directory's only table is included by path, and checked the same way."""
    site = tmp_path / "site#1"
    init_config_dir(site)
    assert study_main([str(STUDY), str(tmp_path / "topas.txt"), *ARGS, "--config-dir", str(site),
                       "-b", "DCPT_beam_model__v5"]) == 2
    assert "-s path (includeFile)" in caplog.text and "'#'" in caplog.text
    assert not list(tmp_path.glob("topas*"))


def test_the_rtstruct_path_of_an_override():
    rs = RTStruct(file_path=Path("study/RS=1.dcm"))
    with pytest.raises(ValueError, match=r"RTSTRUCT path \(DicomRTStructFile\).*'='"):
        check_topas_values(CTModel(), rs, None, material_overrides=[MaterialOverride("BODY", "G4_WATER")])


def test_a_direct_call_of_the_exporter_is_checked_too(tmp_path):
    """Not only the CLI: export_study_topas() refuses before it writes anything."""
    ct, rs, plan = load_ct(STUDY), load_rs(STUDY), load_plan(STUDY)
    with pytest.raises(ValueError, match=r"output name \(Sc/Dose/OutputFile\) from=api"):
        export_study_topas(ct, rs, plan, tmp_path / "from=api.txt", field_nr=1,
                           dose_path=next(STUDY.glob("RD*.dcm")))
    assert not list(tmp_path.iterdir())
