"""--spot-mode sources places and weights every spot exactly as the time feature does (#88)."""
import logging
import re

import pytest

import dicomexport.main as study
import dicomexport.main_plan_export as plan_export
from dicomexport.parser_main import create_parser as main_parser
from dicomexport.parser_plan_export import create_parser as plan_parser

BEAM_MODEL = "res/beam_models/DCPT_beam_model__v2.csv"
SPR_TABLE = "res/spr_tables/SPRtoMaterial__Brain.txt"
STUDY = "res/test_studies/DCPT_headphantom/"
PLAN = "res/test_plans/temp_sobp_10x10.dcm"

# Time-feature arrays, and how each one appears on the per-spot Group/source.
# (time-feature name, sources parameter, sign applied by Ge/BeamPosition)
SPOT_PARAMETERS = [
    ("spotPositionX", "Ge/{}/TransX", 1),
    ("spotPositionY", "Ge/{}/TransY", -1),
    ("spotAngleY", "Ge/{}/RotX", -1),
    ("BeamPositionRotY", "Ge/{}/RotY", 1),
    ("Energy", "So/{}/EmittanceEnergy", 1),
    ("EnergySpread", "So/{}/EmittanceEnergySpread", 1),
    ("SigmaX", "So/{}/SigmaX", 1),
    ("SigmaY", "So/{}/SigmaY", 1),
    ("SigmaXprime", "So/{}/SigmaXprime", 1),
    ("SigmaYprime", "So/{}/SigmaYprime", 1),
    ("CorrelationX", "So/{}/CorrelationX", 1),
    ("CorrelationY", "So/{}/CorrelationY", 1),
    ("spotWeight", "So/{}/NumberOfHistoriesInRun", 1),
]


def _time_features(text):
    out = {}
    for m in re.finditer(r"^[ud]v:Tf/(\w+)/Values\s*=\s*(\d+)\s+(.*)$", text, re.M):
        values = m.group(3).split()[:int(m.group(2))]
        out[m.group(1)] = [float(v) for v in values]
    return out


def _sources(text):
    out = {}
    for m in re.finditer(r"^\w:((?:Ge|So)/Spot\d+/\w+)\s*=\s*(\S+)", text, re.M):
        out[m.group(1)] = m.group(2)
    return out


def _assert_same_spots(timefeature_text, sources_text):
    tf, src = _time_features(timefeature_text), _sources(sources_text)
    n = len(tf["spotWeight"])
    width = max(4, len(str(n)))
    kept = 0
    for k in range(n):
        name = f"Spot{k + 1:0{width}d}"
        if round(tf["spotWeight"][k]) == 0:
            assert f"So/{name}/Type" not in src, f"{name} has 0 histories but was emitted"
            continue
        kept += 1
        for tf_name, param, sign in SPOT_PARAMETERS:
            assert float(src[param.format(name)]) == pytest.approx(sign * tf[tf_name][k], abs=1e-9), \
                f"{name}: {param.format(name)} differs from Tf/{tf_name}"
    assert kept == sum(1 for key in src if key.endswith("/NumberOfHistoriesInRun"))
    # The nozzle distance and side: one TransZ for Ge/BeamPosition, the same on every spot.
    transz = re.search(r"^d:Ge/BeamPosition/TransZ\s*=\s*(\S+) mm", timefeature_text, re.M).group(1)
    assert {v for k, v in src.items() if k.endswith("/TransZ")} == {transz}
    return kept


def _plan_files(tmp_path, *extra):
    out = {}
    for mode in ("timefeature", "sources"):
        d = tmp_path / mode
        d.mkdir()
        assert plan_export.main([PLAN, str(d / "p.txt"), "-b", BEAM_MODEL, "-N", "100000",
                                 "--spot-mode", mode, *extra]) == 0
        out[mode] = (d / "p_field01.txt").read_text()
    return out


@pytest.mark.parametrize("extra", [[], ["--nozzle-side", "pos-z"], ["--test-mode"]])
def test_plan_export_places_every_spot_identically(tmp_path, extra):
    files = _plan_files(tmp_path, *extra)
    assert _assert_same_spots(files["timefeature"], files["sources"]) > 100


def test_study_export_places_every_spot_identically(tmp_path):
    texts = {}
    for mode in ("timefeature", "sources"):
        d = tmp_path / mode
        d.mkdir()
        assert study.main(["-b", BEAM_MODEL, "-s", SPR_TABLE, "-N", "200000", "--spot-mode", mode,
                           STUDY, str(d / "topas.txt")]) == 0
        texts[mode] = {f.name: f.read_text() for f in d.glob("topas_field*.txt")}
    assert sorted(texts["sources"]) == ["topas_field01.txt", "topas_field02.txt", "topas_field03.txt"]
    for name in texts["sources"]:
        _assert_same_spots(texts["timefeature"][name], texts["sources"][name])


def test_sources_mode_has_no_time_feature(tmp_path):
    text = _plan_files(tmp_path, "--test-mode")["sources"]
    assert "Tf/" not in text
    assert "BeamPosition" not in text
    assert "So/Field" not in text


def test_progress_is_reported_per_event(tmp_path):
    """With ~1e2 events per field, the time-feature interval of 1e5 would print one line."""
    files = _plan_files(tmp_path, "--test-mode")
    assert "i:Ts/ShowHistoryCountAtInterval         = 100000" in files["timefeature"]
    interval = int(re.search(r"ShowHistoryCountAtInterval\s*=\s*(\d+)", files["sources"]).group(1))
    max_events = max(int(v) for v in re.findall(r"NumberOfHistoriesInRun\s*=\s*(\d+)", files["sources"]))
    assert 1 <= interval <= max(1, max_events // 50)


def test_spots_rounding_to_zero_are_dropped_with_a_warning(tmp_path, caplog):
    d = tmp_path / "low"
    d.mkdir()
    with caplog.at_level(logging.WARNING):
        # 6069 spots for 10k primaries: about a quarter of them round to 0.
        assert plan_export.main([PLAN, str(d / "p.txt"), "-b", BEAM_MODEL, "-N", "10000",
                                 "--spot-mode", "sources"]) == 0
    assert "round to 0 histories" in caplog.text


def test_no_spot_left_is_an_error(tmp_path):
    with pytest.raises(ValueError, match="Increase -N"):
        plan_export.main([PLAN, str(tmp_path / "p.txt"), "-b", BEAM_MODEL, "-N", "10",
                          "--spot-mode", "sources"])


def test_old_topas_gets_beam_names_per_spot(tmp_path):
    text = _plan_files(tmp_path, "--topas-version", "3.9")["sources"]
    assert "So/Spot0001/BeamParticle" in text
    assert "EmittanceParticle" not in text


@pytest.mark.parametrize("create, positionals", [(main_parser, ["s"]), (plan_parser, ["p.dcm"])])
def test_parsers_offer_both_modes(create, positionals):
    for mode in ("sources", "timefeature"):
        assert create().parse_args(positionals + ["--spot-mode", mode]).spot_mode == mode
    with pytest.raises(SystemExit):
        create().parse_args(positionals + ["--spot-mode", "bogus"])


def test_header_states_the_spot_layout(tmp_path):
    """pregdos scales its progress bar from these keys instead of parsing every source (#88)."""
    files = _plan_files(tmp_path, "--test-mode")

    def key(text, name):
        m = re.search(rf"^# {name}: (\S+)$", text, re.M)
        return m.group(1) if m else None

    weights = [int(v) for v in re.findall(r"NumberOfHistoriesInRun\s*=\s*(\d+)", files["sources"])]
    assert key(files["sources"], "SPOT_MODE") == "sources"
    assert key(files["sources"], "SPOTS") == str(len(weights))
    assert key(files["sources"], "RUNS") == "1"
    assert key(files["sources"], "HISTORIES_PER_RUN") == str(max(weights))

    n_times = re.search(r"i:Tf/NumberOfSequentialTimes\s*=\s*(\d+)", files["timefeature"]).group(1)
    assert key(files["timefeature"], "SPOT_MODE") == "timefeature"
    assert key(files["timefeature"], "SPOTS") == n_times
    assert key(files["timefeature"], "RUNS") == n_times
    assert key(files["timefeature"], "HISTORIES_PER_RUN") is None


def test_sources_is_the_default():
    """3.2x faster on the head phantom at 100k primaries / 28 threads, same dose (#88)."""
    assert main_parser().parse_args(["s"]).spot_mode == "sources"
    assert plan_parser().parse_args(["p.dcm"]).spot_mode == "sources"
