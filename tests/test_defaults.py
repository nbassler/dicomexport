"""The shipped defaults directory (issue #112): its layout, and that the wheel carries all of it."""
import sys
import tomllib
from pathlib import Path

from dicomexport.config import BEAM_MODELS, CT_TO_MATERIAL, DEFAULTS_DIR, MATERIALS, RANGE_SHIFTERS, shipped_defaults_dir

REPO = Path(__file__).parent.parent
PACKAGE = REPO / "dicomexport"


def test_defaults_dir_is_inside_the_package():
    assert DEFAULTS_DIR == (PACKAGE / "defaults").resolve()


def test_layout():
    assert sorted(p.name for p in (DEFAULTS_DIR / BEAM_MODELS).glob("*.csv")) == [
        "DCPT_beam_model__v2.csv", "DCPT_beam_model__v5.csv"]
    assert sorted(p.name for p in (DEFAULTS_DIR / CT_TO_MATERIAL).glob("*.txt")) == ["HUtoMaterialSchneider.txt"]
    assert (DEFAULTS_DIR / RANGE_SHIFTERS).is_file()
    assert (DEFAULTS_DIR / MATERIALS).is_file()


def test_every_shipped_file_is_package_data():
    """A file the package-data patterns miss is silently absent from the wheel."""
    pyproject = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))
    patterns = pyproject["tool"]["setuptools"]["package-data"]["dicomexport"]
    packaged = {p for pattern in patterns for p in PACKAGE.glob(pattern) if p.is_file()}
    shipped = {p for p in (PACKAGE / "defaults").rglob("*") if p.is_file()}
    assert shipped - packaged == set()


def test_frozen_build_reads_defaults_beside_the_executable(monkeypatch, tmp_path):
    """Not from PyInstaller's temporary unpack directory, which is deleted on exit.

    A table listed from there would be written into TOPAS includeFile and vanish with it.
    """
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "dicomexport.exe"))
    assert shipped_defaults_dir() == tmp_path.resolve() / "defaults"
