"""The shipped defaults directory (issue #112): its layout, and that the wheel carries all of it."""
import tomllib
from pathlib import Path

from dicomexport.config import BEAM_MODELS, CT_TO_MATERIAL, DEFAULTS_DIR, RANGE_SHIFTERS

REPO = Path(__file__).parent.parent
PACKAGE = REPO / "dicomexport"


def test_defaults_dir_is_inside_the_package():
    assert DEFAULTS_DIR == (PACKAGE / "defaults").resolve()


def test_layout():
    assert sorted(p.name for p in (DEFAULTS_DIR / BEAM_MODELS).glob("*.csv")) == [
        "DCPT_beam_model__v2.csv", "DCPT_beam_model__v5.csv"]
    assert sorted(p.name for p in (DEFAULTS_DIR / CT_TO_MATERIAL).glob("*.txt")) == ["HUtoMaterialSchneider.txt"]
    assert (DEFAULTS_DIR / RANGE_SHIFTERS).is_file()


def test_every_shipped_file_is_package_data():
    """A file the package-data patterns miss is silently absent from the wheel."""
    pyproject = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))
    patterns = pyproject["tool"]["setuptools"]["package-data"]["dicomexport"]
    packaged = {p for pattern in patterns for p in PACKAGE.glob(pattern) if p.is_file()}
    shipped = {p for p in (PACKAGE / "defaults").rglob("*") if p.is_file()}
    assert shipped - packaged == set()
