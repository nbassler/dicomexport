"""TopasExportOptions is the single source of the TOPAS export defaults (#116)."""
import pytest

from dicomexport.parser_geo_export import create_parser as geo_parser
from dicomexport.parser_main import create_parser as main_parser
from dicomexport.parser_plan_export import create_parser as plan_parser
from dicomexport.parser_topas_options import options_from_args
from dicomexport.topas_export_options import DEFAULTS, TopasExportOptions

# Each parser with the positionals it needs to parse at all.
PARSERS = {
    "main": (main_parser, ["study_dir"]),
    "plan": (plan_parser, ["plan.dcm"]),
    "geo": (geo_parser, ["ct_dir"]),
}


def test_defaults_are_the_verified_ones():
    # neg-z is the IEC-correct side verified on OpenTOPAS 4.2.3 (#66); 32-bit cubes (#111).
    assert DEFAULTS.beam_direction == -1
    assert DEFAULTS.nozzle_side == "neg-z"
    assert DEFAULTS.dose_cube_16bit is False


@pytest.mark.parametrize("name", PARSERS)
def test_parser_defaults_give_the_dataclass_defaults(name):
    create, positionals = PARSERS[name]
    assert options_from_args(create().parse_args(positionals)) == DEFAULTS


@pytest.mark.parametrize("name", ["main", "plan"])
def test_flags_reach_the_options(name):
    create, positionals = PARSERS[name]
    args = create().parse_args(
        positionals + ["-N", "123", "--threads", "-1", "--topas-version", "3.9", "--nozzle-side", "pos-z"])
    opts = options_from_args(args)
    assert opts.nstat == 123
    assert opts.nr_threads == -1
    assert opts.topas_version == (3, 9)
    assert opts.beam_direction == 1


@pytest.mark.parametrize("name", ["main", "geo"])
def test_dose_cube_flag_reaches_the_options(name):
    create, positionals = PARSERS[name]
    assert options_from_args(create().parse_args(positionals + ["--dose-cube-16bit"])).dose_cube_16bit is True


def test_options_a_parser_does_not_offer_keep_their_default():
    # geo-export has no --nstat/--nozzle-side/--topas-version.
    opts = options_from_args(geo_parser().parse_args(["ct_dir", "--threads", "4"]))
    assert opts == TopasExportOptions(nr_threads=4)


@pytest.mark.parametrize("side, direction", [("neg-z", -1), ("pos-z", 1)])
def test_nozzle_side_round_trip(side, direction):
    assert TopasExportOptions.beam_direction_of(side) == direction
    assert TopasExportOptions(beam_direction=direction).nozzle_side == side


@pytest.mark.parametrize("bad", [0, 2, -2])
def test_rejects_invalid_beam_direction(bad):
    with pytest.raises(ValueError):
        TopasExportOptions(beam_direction=bad)


def test_is_immutable():
    with pytest.raises(AttributeError):
        DEFAULTS.nstat = 5
