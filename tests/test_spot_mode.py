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


def _plan_files(tmp_path, *extra, batches="1"):
    """Both spot modes; sources mode in one batch, so its spot weights equal the time feature's."""
    out = {}
    for mode in ("timefeature", "sources"):
        d = tmp_path / mode
        d.mkdir()
        b = ["--batches", batches] if mode == "sources" and batches is not None else []
        assert plan_export.main([PLAN, str(d / "p.txt"), "-b", BEAM_MODEL, "-N", "100000",
                                 "--spot-mode", mode, *b, *extra]) == 0
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
        batches = ["--batches", "1"] if mode == "sources" else []
        assert study.main(["-b", BEAM_MODEL, "-s", SPR_TABLE, "-N", "200000", "--spot-mode", mode,
                           *batches, STUDY, str(d / "topas.txt")]) == 0
        texts[mode] = {f.name: f.read_text() for f in d.glob("topas_field*.txt")}
    assert sorted(texts["sources"]) == ["topas_field01.txt", "topas_field02.txt", "topas_field03.txt"]
    for name in texts["sources"]:
        _assert_same_spots(texts["timefeature"][name], texts["sources"][name])


def test_one_batch_has_no_time_feature(tmp_path):
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
    assert key(files["sources"], "SIMULATED_HISTORIES") == str(sum(weights))
    assert key(files["sources"], "EVENTS_PER_RUN") == str(max(weights))

    n_times = re.search(r"i:Tf/NumberOfSequentialTimes\s*=\s*(\d+)", files["timefeature"]).group(1)
    assert key(files["timefeature"], "SPOT_MODE") == "timefeature"
    assert key(files["timefeature"], "SPOTS") == n_times
    assert key(files["timefeature"], "RUNS") == n_times
    # What pregdos computes today from the time feature: sum(Tf/spotWeight).
    tf_weights = _time_features(files["timefeature"])["spotWeight"]
    assert key(files["timefeature"], "SIMULATED_HISTORIES") == str(int(sum(tf_weights)))
    assert key(files["sources"], "SIMULATED_HISTORIES") == key(files["timefeature"], "SIMULATED_HISTORIES")
    assert key(files["timefeature"], "EVENTS_PER_RUN") is None


def test_sources_is_the_default():
    """3.2x faster on the head phantom at 100k primaries / 28 threads, same dose (#88)."""
    assert main_parser().parse_args(["s"]).spot_mode == "sources"
    assert plan_parser().parse_args(["p.dcm"]).spot_mode == "sources"


def test_negative_spot_weight_is_refused_at_import(tmp_path):
    """Every exporter would turn a negative weight into something different; refuse it."""
    import pydicom
    from dicomexport.import_plan import load_plan
    path = tmp_path / "negative.dcm"
    ds = pydicom.dcmread("res/test_plans/temp_160MeV_10x10.dcm")
    icp = ds.IonBeamSequence[0].IonControlPointSequence[0]
    weights = list(icp.ScanSpotMetersetWeights)
    weights[0] = -abs(weights[1]) - 1.0
    icp.ScanSpotMetersetWeights = weights
    ds.save_as(path)
    with pytest.raises(ValueError, match="negative ScanSpotMetersetWeights"):
        load_plan(path)


@pytest.mark.parametrize("mode", ["sources", "timefeature"])
def test_negative_spot_weight_is_refused_by_the_topas_writer(mode):
    from dicomexport.beam_model import BeamModel
    from dicomexport.export_plan_topas import TopasPlan
    from dicomexport.import_plan import load_plan
    from dicomexport.topas_export_options import TopasExportOptions
    from pathlib import Path
    plan = load_plan(Path("res/test_plans/temp_160MeV_10x10.dcm"))
    plan.beam_model = BeamModel(Path(BEAM_MODEL))
    plan.apply_beammodel()
    plan.fields[0].layers[0].spots[0].mu = -1.0
    with pytest.raises(ValueError, match="negative weight"):
        TopasPlan.generate(plan.fields[0], plan.beam_model, opts=TopasExportOptions(spot_mode=mode))


# --- batches (issue #121) -------------------------------------------------------------


def _key(text, name):
    m = re.search(rf"^# {name}: (\S+)$", text, re.M)
    return m.group(1) if m else None


def test_sources_mode_runs_ten_identical_batches_by_default(tmp_path):
    files = _plan_files(tmp_path, "--test-mode", batches=None)
    src = files["sources"]
    # The batch count is the only Tf/ parameter: nothing changes between the runs.
    assert re.findall(r"^\w+:Tf/.*$", src, re.M) == [
        f"{'i:Tf/NumberOfSequentialTimes':<44} = 10"]
    assert "BeamPosition" not in src
    per_batch = [int(v) for v in re.findall(r"NumberOfHistoriesInRun\s*=\s*(\d+)", src)]
    assert _key(src, "RUNS") == "10"
    assert _key(src, "EVENTS_PER_RUN") == str(max(per_batch))
    assert _key(src, "SPOTS") == str(len(per_batch))
    assert _key(src, "SIMULATED_HISTORIES") == str(10 * sum(per_batch))
    # Each spot gets a tenth of its time-feature weight, up to rounding to whole histories.
    tf = _time_features(files["timefeature"])["spotWeight"]
    assert sum(per_batch) * 10 == pytest.approx(sum(tf), rel=0.01)


def test_batches_split_every_spot_weight(tmp_path):
    from dicomexport.beam_model import BeamModel
    from dicomexport.export_plan_topas import TopasPlan
    from dicomexport.import_plan import load_plan
    from pathlib import Path
    plan = load_plan(Path("res/test_plans/temp_160MeV_10x10.dcm"))
    plan.beam_model = BeamModel(Path(BEAM_MODEL))
    plan.apply_beammodel()
    t = TopasPlan.spot_table(plan.fields[0], plan.beam_model, 100000)
    assert list(TopasPlan.spot_histories(t, 1)) == [int(f"{w:.0f}") for w in t.weight]
    assert list(TopasPlan.spot_histories(t, 4)) == [int(f"{w / 4:.0f}") for w in t.weight]


@pytest.mark.parametrize("create, positionals", [(main_parser, ["s"]), (plan_parser, ["p.dcm"])])
def test_parsers_offer_batches(create, positionals):
    assert create().parse_args(positionals).batches is None
    assert create().parse_args(positionals + ["--batches", "5"]).batches == 5


@pytest.mark.parametrize("bad", [["--batches", "0"], ["--spot-mode", "timefeature", "--batches", "5"]])
@pytest.mark.parametrize("entry, positionals", [(study.main, ["s", "out.txt"]), (plan_export.main, [PLAN, "out.txt"])])
def test_bad_batches_fail_at_the_command_line(entry, positionals, bad, capsys):
    with pytest.raises(SystemExit) as e:
        entry(positionals + bad)
    assert e.value.code == 2
    assert "--batches" in capsys.readouterr().err


def test_timefeature_ignores_the_batch_default():
    from dicomexport.topas_export_options import TopasExportOptions
    assert TopasExportOptions().n_batches == 10
    assert TopasExportOptions(spot_mode="timefeature").n_batches == 1
    assert TopasExportOptions(spot_mode="timefeature", batches=1).n_batches == 1
    assert TopasExportOptions(batches=3).n_batches == 3


def test_coarse_rounding_per_batch_warns(tmp_path, caplog):
    with caplog.at_level(logging.WARNING):
        assert plan_export.main([PLAN, str(tmp_path / "p.txt"), "-b", BEAM_MODEL, "-N", "100000"]) == 0
    assert "of all primaries" in caplog.text
    assert "lower --batches" in caplog.text


def test_no_spot_left_per_batch_names_batches(tmp_path):
    with pytest.raises(ValueError, match="lower --batches"):
        plan_export.main([PLAN, str(tmp_path / "p.txt"), "-b", BEAM_MODEL, "-N", "1000"])
