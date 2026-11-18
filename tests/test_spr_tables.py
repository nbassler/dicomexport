"""Shipped CT-number-to-material tables must not make TOPAS index DensityCorrection out of bounds.

This checks the tables in res/spr_tables/ and dicomexport/defaults/ct_to_material/ as data.
dicomexport itself never parses these files: it passes them to TOPAS (see CONTRIBUTING.md,
"Design principles"). Validation for tables supplied by users belongs to the front end
(Eurados/pregdos#131).

What TOPAS does, from OpenTOPAS 4.3.0 geometry/TsImagingToMaterialSchneider.cc:

- MinImagingValue defaults to -1000 when the table does not set it (lines 90-93).
- It aborts unless len(DensityCorrection) == sections[-1] - sections[0] (lines 52-56), where
  sections is SchneiderHounsfieldUnitSections.
- A voxel value is clamped to [sections[0], sections[-1] - 1] (lines 169-188), and the
  correction is then read as DensityCorrection[value - MinImagingValue] (line 222), with no
  bounds check.

Together these leave MinImagingValue == sections[0] as the only valid setting. A table that
breaks it does not abort: TOPAS reads outside the vector and carries on (issue #99).
"""
import re
from pathlib import Path

import pytest

REPO = Path(__file__).parent.parent
SPR_TABLE_DIR = REPO / "res" / "spr_tables"
# The test tables, and the ones dicomexport ships (issue #112).
TABLES = sorted(SPR_TABLE_DIR.glob("*.txt")) + sorted((REPO / "dicomexport" / "defaults" / "ct_to_material").glob("*.txt"))

TOPAS_DEFAULT_MIN_IMAGING_VALUE = -1000

# "<type>:<name> =". The value runs until the next parameter, so vectors may continue over
# several lines, as they do in OpenTOPAS's own HUtoMaterialSchneider.txt.
_PARAMETER = re.compile(r"^\s*([a-z]+):(\S+?)\s*=", re.MULTILINE)


def _parameters(text: str) -> dict[str, list[str]]:
    """Map each parameter name to the whitespace-separated tokens of its value."""
    text = "\n".join(line.split("#", 1)[0] for line in text.splitlines())
    matches = list(_PARAMETER.finditer(text))
    params = {}
    for match, following in zip(matches, matches[1:] + [None]):
        name = match.group(2)
        assert name not in params, f"{name} is defined twice"
        params[name] = text[match.end():following.start() if following else len(text)].split()
    return params


def _vector(params: dict[str, list[str]], name: str) -> list[float]:
    """A TOPAS vector: a count, that many numbers, and at most one unit."""
    assert name in params, f"{name} is missing"
    tokens = params[name]
    count = int(tokens[0])
    values, rest = tokens[1:1 + count], tokens[1 + count:]
    assert len(values) == count, f"{name} declares {count} values but has {len(values)}"
    assert len(rest) <= 1, f"{name} has {len(rest)} tokens after its {count} values: {rest[:5]}"
    return [float(v) for v in values]


def index_problems(text: str) -> list[str]:
    """Return why TOPAS would read DensityCorrection out of bounds, or abort, with this table."""
    params = _parameters(text)
    converter = params.get("Ge/Patient/ImagingToMaterialConverter", [])
    if converter != ['"Schneider"']:
        return [f"ImagingToMaterialConverter is {' '.join(converter) or 'missing'}, not \"Schneider\""]

    corrections = _vector(params, "Ge/Patient/DensityCorrection")
    sections = _vector(params, "Ge/Patient/SchneiderHounsfieldUnitSections")
    min_value = (int(params["Ge/Patient/MinImagingValue"][0]) if "Ge/Patient/MinImagingValue" in params
                 else TOPAS_DEFAULT_MIN_IMAGING_VALUE)

    problems = []
    if len(corrections) != sections[-1] - sections[0]:
        problems.append(f"DensityCorrection has {len(corrections)} entries but the sections span "
                        f"{sections[-1] - sections[0]:g}; TOPAS aborts")
    lowest, highest = sections[0] - min_value, sections[-1] - 1 - min_value
    if lowest < 0:
        problems.append(f"sections start at {sections[0]:g} but MinImagingValue is {min_value}: "
                        f"index {lowest:g} reads before DensityCorrection")
    if highest >= len(corrections):
        problems.append(f"sections end at {sections[-1]:g} but MinImagingValue is {min_value}: "
                        f"index {highest:g} reads past the {len(corrections)} entries of DensityCorrection")
    return problems


def test_tables_are_found():
    assert TABLES, f"no tables found in {SPR_TABLE_DIR}"


@pytest.mark.parametrize("table", TABLES, ids=lambda p: p.name)
def test_shipped_table_keeps_density_correction_in_bounds(table):
    assert index_problems(table.read_text(encoding="utf-8")) == []


def test_check_catches_the_table_as_it_was_before_issue_99():
    """Without MinImagingValue, the brain table read DensityCorrection[-24] for its lowest values."""
    text = (SPR_TABLE_DIR / "SPRtoMaterial__Brain.txt").read_text(encoding="utf-8")
    unfixed = re.sub(r"^i:Ge/Patient/MinImagingValue\s*=.*$", "", text, flags=re.MULTILINE)
    assert unfixed != text

    problems = index_problems(unfixed)

    assert len(problems) == 1
    assert "start at -1024 but MinImagingValue is -1000" in problems[0]
    assert "index -24" in problems[0]
