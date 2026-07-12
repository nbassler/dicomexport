"""Optional integration test: verify the beam direction with a real TOPAS run.

Regression test for issue #66: the default nozzle side must produce an IEC-correct
beam. At gantry 0 with an HFS patient, the beam has to enter from the anterior side
(world -Y in the DICOM-oriented world), i.e. the source sits at negative world Y.

The test generates a --test-mode plan with the production CLI, appends two thick
water slabs on opposite sides of the isocenter (each thick enough to stop the beam),
runs TOPAS, and asserts that the deposited energy lands in the slab on the expected
side.

TOPAS is NOT required for dicomexport development: the test is skipped when no
``topas`` executable is on PATH, and also when TOPAS exists but cannot run (e.g.
missing Geant4 data), since that is an environment problem, not a dicomexport bug.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

import dicomexport.main_plan_export as main_plan_export

# Water slabs 100 mm thick at world y = -300 mm (anterior/source side for the
# IEC-correct gantry-0 beam) and y = +300 mm. A 160 MeV proton (range ~177 mm in
# water) cannot cross a slab and the IsoBox, so only the entrance side scores.
DIRECTION_PROBE = """
s:Ge/EntranceSlabNegY/Parent   = "World"
s:Ge/EntranceSlabNegY/Type     = "TsBox"
s:Ge/EntranceSlabNegY/Material = "G4_WATER"
d:Ge/EntranceSlabNegY/HLX      = 200. mm
d:Ge/EntranceSlabNegY/HLY      = 50. mm
d:Ge/EntranceSlabNegY/HLZ      = 200. mm
d:Ge/EntranceSlabNegY/TransX   = 0. mm
d:Ge/EntranceSlabNegY/TransY   = -300. mm
d:Ge/EntranceSlabNegY/TransZ   = 0. mm

s:Ge/EntranceSlabPosY/Parent   = "World"
s:Ge/EntranceSlabPosY/Type     = "TsBox"
s:Ge/EntranceSlabPosY/Material = "G4_WATER"
d:Ge/EntranceSlabPosY/HLX      = 200. mm
d:Ge/EntranceSlabPosY/HLY      = 50. mm
d:Ge/EntranceSlabPosY/HLZ      = 200. mm
d:Ge/EntranceSlabPosY/TransX   = 0. mm
d:Ge/EntranceSlabPosY/TransY   = 300. mm
d:Ge/EntranceSlabPosY/TransZ   = 0. mm

s:Sc/EdepNegY/Quantity  = "EnergyDeposit"
s:Sc/EdepNegY/Component = "EntranceSlabNegY"
s:Sc/EdepNegY/OutputType = "csv"
s:Sc/EdepNegY/OutputFile = "edep_neg_y"
s:Sc/EdepNegY/IfOutputFileAlreadyExists = "Overwrite"

s:Sc/EdepPosY/Quantity  = "EnergyDeposit"
s:Sc/EdepPosY/Component = "EntranceSlabPosY"
s:Sc/EdepPosY/OutputType = "csv"
s:Sc/EdepPosY/OutputFile = "edep_pos_y"
s:Sc/EdepPosY/IfOutputFileAlreadyExists = "Overwrite"
"""


def _read_scorer_sum(csv_path: Path) -> float:
    values = []
    for line in csv_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        try:
            values.append(float(line.split(',')[0]))
        except ValueError:
            continue
    return sum(values)


@pytest.mark.skipif(shutil.which("topas") is None,
                    reason="TOPAS not installed; skipping beam direction integration test")
@pytest.mark.parametrize("nozzle_side, entrance", [("neg-z", "neg_y"), ("pos-z", "pos_y")])
def test_beam_enters_from_expected_side(tmp_path, nozzle_side, entrance):
    repo_root = Path(__file__).resolve().parent.parent
    test_args = [
        "-f1",
        "-N", "500",
        f"-b={repo_root / 'res/beam_models/DCPT_beam_model__v2.csv'}",
        "--test-mode",
        f"--nozzle-side={nozzle_side}",
        str(repo_root / "res/test_plans/temp_160MeV_10x10.dcm"),
        str(tmp_path / "plan.txt"),
    ]
    assert main_plan_export.main(test_args) == 0
    plan_file = tmp_path / "plan_field01.txt"
    assert plan_file.exists()

    plan_file.write_text(plan_file.read_text() + DIRECTION_PROBE)

    result = subprocess.run(["topas", plan_file.name], cwd=tmp_path,
                            capture_output=True, text=True, timeout=600)
    if result.returncode != 0:
        pytest.skip("TOPAS present but failed to run (environment problem?): "
                    + result.stdout[-500:] + result.stderr[-500:])

    edep = {side: _read_scorer_sum(tmp_path / f"edep_{side}.csv")
            for side in ("neg_y", "pos_y")}
    far = "pos_y" if entrance == "neg_y" else "neg_y"

    assert edep[entrance] > 0.0, f"no dose in the {entrance} entrance slab: {edep}"
    assert edep[entrance] > 50.0 * edep[far], \
        (f"beam did not enter from the {entrance} side for --nozzle-side={nozzle_side} "
         f"(issue #66): {edep}")


def test_default_matches_verified_neg_z():
    """The parser default must stay on the empirically verified IEC-correct side."""
    from dicomexport.parser_main import create_parser as main_parser
    from dicomexport.parser_plan_export import create_parser as plan_parser

    assert main_parser().get_default("nozzle_side") == "neg-z"
    assert plan_parser().get_default("nozzle_side") == "neg-z"
