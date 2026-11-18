"""The configuration directory (issue #112): which one is in effect, and what is chosen from it.

tests/conftest.py keeps every test away from the real ~/.config/dicomexport, /etc/dicomexport
and $DICOMEXPORT_CONFIG_DIR of the machine running it.
"""
import hashlib
import json
import re
import shutil
from pathlib import Path

import pytest

import dicomexport.config as config
from dicomexport.config import DEFAULTS_DIR, ENV_VAR, ConfigError, Include, find_config_dir, init_config_dir
from dicomexport.import_plan import load_plan
from dicomexport.main import main as study_main
from dicomexport.main_plan_export import main as plan_main
from dicomexport.model_plan import range_shifter_catalog_of
from tests.dicom_fixtures import make_ccb_style_plan

REPO = Path(__file__).parent.parent
STUDY = REPO / "res" / "test_studies" / "DCPT_headphantom"
PLAN = REPO / "res" / "test_plans" / "temp_160MeV_10x10.dcm"
SHIPPED_V5 = DEFAULTS_DIR / "beam_models" / "DCPT_beam_model__v5.csv"
SHIPPED_TABLE = DEFAULTS_DIR / "ct_to_material" / "HUtoMaterialSchneider.txt"


def site_dir(root: Path, beam_models=("SITE_bm.csv",), tables=("HUtoMaterialSite.txt",),
             range_shifters: str | None = "RS_SITE,30.0,Lexan\n") -> Path:
    """A minimal site configuration directory, with copies of the shipped files under new names."""
    (root / "beam_models").mkdir(parents=True)
    (root / "ct_to_material").mkdir()
    for name in beam_models:
        shutil.copy(SHIPPED_V5, root / "beam_models" / name)
    for name in tables:
        shutil.copy(SHIPPED_TABLE, root / "ct_to_material" / name)
    if range_shifters is not None:
        (root / "range_shifters.csv").write_text(range_shifters)
    return root


class TestSearchOrder:

    @pytest.fixture
    def all_present(self, tmp_path, monkeypatch):
        dirs = {name: tmp_path / name for name in ("explicit", "env", "user", "system")}
        for d in dirs.values():
            d.mkdir()
        monkeypatch.setattr(config, "user_config_dir", lambda: dirs["user"])
        monkeypatch.setattr(config, "system_config_dir", lambda: dirs["system"])
        monkeypatch.setenv(ENV_VAR, str(dirs["env"]))
        return dirs

    def test_explicit_wins(self, all_present):
        assert find_config_dir(all_present["explicit"]).path == all_present["explicit"]

    def test_then_the_environment(self, all_present):
        assert find_config_dir().path == all_present["env"]

    def test_then_the_user_directory(self, all_present, monkeypatch):
        monkeypatch.delenv(ENV_VAR)
        assert find_config_dir().path == all_present["user"]

    def test_then_the_system_directory(self, all_present, monkeypatch):
        monkeypatch.delenv(ENV_VAR)
        all_present["user"].rmdir()
        assert find_config_dir().path == all_present["system"]

    def test_then_the_shipped_defaults(self):
        cfg = find_config_dir()
        assert cfg.path == DEFAULTS_DIR
        assert cfg.is_shipped

    def test_only_one_is_in_effect(self, all_present):
        """Never merged: a file in the user directory is invisible when $ENV wins."""
        (all_present["user"] / "range_shifters.csv").write_text("RS_USER,10,Lexan\n")
        assert find_config_dir().range_shifters == all_present["env"] / "range_shifters.csv"

    @pytest.mark.parametrize("how", ["explicit", "env"])
    def test_a_named_directory_that_does_not_exist_is_an_error(self, tmp_path, monkeypatch, how):
        """A typo must never fall back to other data silently."""
        missing = tmp_path / "typo"
        if how == "env":
            monkeypatch.setenv(ENV_VAR, str(missing))
        with pytest.raises(ConfigError, match="does not exist.*--init-config"):
            find_config_dir(missing if how == "explicit" else None)


class TestChoosingABeamModel:

    def test_shipped_defaults_default_to_v5(self):
        assert find_config_dir().beam_model(None) == SHIPPED_V5

    @pytest.mark.parametrize("name", ["DCPT_beam_model__v2", "DCPT_beam_model__v2.csv"])
    def test_by_name_with_or_without_suffix(self, name):
        assert find_config_dir().beam_model(name) == DEFAULTS_DIR / "beam_models" / "DCPT_beam_model__v2.csv"

    def test_a_path_is_used_as_given(self, tmp_path, monkeypatch):
        """Relative stays relative: dicomexport writes paths verbatim (issue #63)."""
        (tmp_path / "my_bm.csv").write_text("")
        monkeypatch.chdir(tmp_path)
        assert find_config_dir().beam_model(Path("my_bm.csv")) == Path("my_bm.csv")

    def test_unknown_name_lists_what_there_is(self):
        with pytest.raises(ConfigError, match="DCPT_beam_model__v9.*DCPT_beam_model__v2.csv, DCPT_beam_model__v5.csv"):
            find_config_dir().beam_model("DCPT_beam_model__v9")

    def test_a_site_directory_with_one_beam_model_needs_no_b(self, tmp_path):
        cfg = find_config_dir(site_dir(tmp_path))
        assert cfg.beam_model(None).name == "SITE_bm.csv"

    def test_the_v5_default_never_applies_to_a_site_directory(self, tmp_path):
        """A site that copied both DCPT models must choose: dicomexport picks no calibration for it."""
        cfg = find_config_dir(site_dir(tmp_path, beam_models=("DCPT_beam_model__v2.csv", "DCPT_beam_model__v5.csv")))
        assert cfg.default_beam_model() is None
        with pytest.raises(ConfigError, match="has 2: DCPT_beam_model__v2.csv, DCPT_beam_model__v5.csv.*-b"):
            cfg.beam_model(None)

    def test_a_site_directory_without_beam_models(self, tmp_path):
        cfg = find_config_dir(site_dir(tmp_path, beam_models=()))
        with pytest.raises(ConfigError, match="has none.*-b FILE"):
            cfg.beam_model(None)


class TestIncludes:
    """-s includes a file by path, -S pastes it. The table is just the usual thing to include."""

    def test_without_s_or_S_the_only_table_is_included(self):
        assert find_config_dir().default_include() == Include(str(SHIPPED_TABLE))

    def test_two_tables_need_a_choice(self, tmp_path):
        cfg = find_config_dir(site_dir(tmp_path, tables=("HUtoMaterialA.txt", "HUtoMaterialB.txt")))
        with pytest.raises(ConfigError, match="has 2.*-s or -S NAME"):
            cfg.default_include()
        assert cfg.include("HUtoMaterialB") == Include(str(tmp_path / "ct_to_material" / "HUtoMaterialB.txt"))

    def test_a_bare_name_that_is_nowhere_is_an_error(self):
        with pytest.raises(ConfigError, match="'nonexistent'.*HUtoMaterialSchneider.txt"):
            find_config_dir().include("nonexistent")

    def test_S_reads_the_file(self, tmp_path):
        extra = tmp_path / "extra.txt"
        extra.write_text("i:Ts/Seed = 5\n")
        inc = find_config_dir().include(str(extra), inline=True)
        assert inc.inline and inc.text == "i:Ts/Seed = 5\n"
        assert inc.sha256 == hashlib.sha256(b"i:Ts/Seed = 5\n").hexdigest()

    def test_S_needs_the_file_now(self, tmp_path):
        """-s may name a file that exists only where TOPAS runs; -S has to read it."""
        with pytest.raises(ConfigError, match="-S ./node-only/extra.txt: cannot read"):
            find_config_dir().include("./node-only/extra.txt", inline=True)


class TestInitConfig:

    def test_copies_the_shipped_defaults(self, tmp_path):
        copied, skipped = init_config_dir(tmp_path / "site")
        shipped = sorted(p.relative_to(DEFAULTS_DIR) for p in DEFAULTS_DIR.rglob("*") if p.is_file())
        assert sorted(p.relative_to(tmp_path / "site") for p in copied) == shipped
        assert skipped == []

    def test_never_overwrites_a_site_file(self, tmp_path):
        """Re-running after an upgrade adds what is missing and leaves the site's edits alone."""
        site = tmp_path / "site"
        init_config_dir(site)
        (site / "range_shifters.csv").write_text("RS_SITE,30.0,Lexan\n")
        (site / "beam_models" / "DCPT_beam_model__v2.csv").unlink()

        copied, skipped = init_config_dir(site)

        assert copied == [site / "beam_models" / "DCPT_beam_model__v2.csv"]
        assert site / "range_shifters.csv" in skipped
        assert (site / "range_shifters.csv").read_text() == "RS_SITE,30.0,Lexan\n"

    def test_cli(self, tmp_path, capsys):
        assert study_main(["--init-config", str(tmp_path / "site")]) == 0
        assert (tmp_path / "site" / "range_shifters.csv").is_file()
        assert "0 skipped" in capsys.readouterr().out


class TestRangeShifters:

    def test_a_directory_without_a_catalog_has_an_empty_one(self, tmp_path):
        catalog = range_shifter_catalog_of(tmp_path)
        assert catalog == {}
        assert "does not exist" in catalog.source

    def test_the_site_catalog_replaces_the_shipped_one(self, tmp_path):
        """An ID only in the shipped catalog is unknown at a site, and the error names the site's file."""
        site = site_dir(tmp_path / "site")
        plan_path = make_ccb_style_plan(PLAN, tmp_path / "rs.dcm", ref_order=(1,), with_delivery=(1,),
                                        range_shifter_id="RS_5CM")
        with pytest.raises(ValueError, match=re.escape(str(site / "range_shifters.csv"))):
            load_plan(plan_path, rs_catalog=range_shifter_catalog_of(site))


class TestListConfig:

    def test_json(self, capsys):
        assert study_main(["--list-config", "json"]) == 0
        listing = json.loads(capsys.readouterr().out)
        assert listing["config_dir"] == str(DEFAULTS_DIR)
        assert listing["is_shipped_defaults"] is True
        assert [(b["name"], b["default"]) for b in listing["beam_models"]] == [
            ("DCPT_beam_model__v2.csv", False), ("DCPT_beam_model__v5.csv", True)]
        assert [t["name"] for t in listing["ct_to_material"]] == ["HUtoMaterialSchneider.txt"]
        assert "RS51" in listing["range_shifters"]["ids"]
        assert listing["materials"]["exists"] is False

    def test_text_names_the_directory(self, tmp_path, capsys):
        assert study_main(["--list-config", "--config-dir", str(site_dir(tmp_path))]) == 0
        out = capsys.readouterr().out
        assert f"Configuration directory: {tmp_path} (--config-dir)" in out
        assert "SITE_bm.csv  (default)" in out
        assert "RS_SITE" in out


class TestStudyExport:

    def test_runs_with_the_shipped_defaults_alone(self, tmp_path, caplog):
        """No -b, no -s: what a fresh pip install does. The header names what was used."""
        assert study_main([str(STUDY), str(tmp_path / "topas.txt"), "-f", "1", "-N", "1000"]) == 0
        text = (tmp_path / "topas_field01.txt").read_text()
        assert f"# CONFIG_DIR: {DEFAULTS_DIR} (shipped defaults)" in text
        assert f"# BEAM_MODEL: {SHIPPED_V5}" in text
        assert f"# INCLUDE: {SHIPPED_TABLE}" in text
        assert f"includeFile                          = {SHIPPED_TABLE}" in text
        assert "Using the defaults shipped with dicomexport" in caplog.text

    @pytest.mark.parametrize("table", ["../node-only/table.txt", "./HUtoMaterialSchneider.txt", "./nested//table.txt"])
    def test_explicit_table_path_is_written_verbatim(self, tmp_path, monkeypatch, table):
        monkeypatch.chdir(tmp_path)
        assert study_main([str(STUDY), "topas.txt", "-s", table, "-f", "1", "-N", "1000", "--batches", "1"]) == 0
        text = (tmp_path / "topas_field01.txt").read_text()
        assert f"includeFile                          = {table}" in text.splitlines()

    @pytest.mark.parametrize("selection", [[], ["-s", "HUtoMaterialSite"]])
    def test_table_picked_from_relative_config_is_absolute(self, tmp_path, monkeypatch, selection):
        site = site_dir(tmp_path / "site", range_shifters=(DEFAULTS_DIR / "range_shifters.csv").read_text())
        (tmp_path / "run").mkdir()
        monkeypatch.chdir(tmp_path)
        args = [str(STUDY), "run/topas.txt", "--config-dir", "site", "-f", "1", "-N", "1000", "--batches", "1"]
        assert study_main([*args, *selection]) == 0
        text = (tmp_path / "run/topas_field01.txt").read_text()
        assert f"includeFile                          = {site / 'ct_to_material' / 'HUtoMaterialSite.txt'}" in text
        assert f"# BEAM_MODEL: {site / 'beam_models' / 'SITE_bm.csv'}" in text

    def test_an_ambiguous_site_directory_is_reported_not_raised(self, tmp_path, caplog):
        """The Qt GUI calls main() in a thread: errors must come back as a code and a log line."""
        site = site_dir(tmp_path / "site", beam_models=("A.csv", "B.csv"))
        rc = study_main([str(STUDY), str(tmp_path / "topas.txt"), "--config-dir", str(site)])
        assert rc == 2
        assert "A.csv, B.csv" in caplog.text
        assert not list(tmp_path.glob("topas_field*.txt"))

    def test_a_missing_config_dir_is_reported_not_raised(self, tmp_path, caplog):
        assert study_main([str(STUDY), "--config-dir", str(tmp_path / "typo")]) == 2
        assert "does not exist" in caplog.text


class TestPlanExport:

    def test_b_may_be_omitted_with_the_shipped_defaults(self, tmp_path, caplog):
        caplog.set_level("INFO")
        out = tmp_path / "plan.txt"
        assert plan_main([str(PLAN), str(out), "--test-mode", "-N", "100000", "--batches", "1", "-f", "1"]) == 0
        assert f"Beam model: {SHIPPED_V5}" in caplog.text
        assert any(record.levelname == "WARNING" and "Using the defaults shipped with dicomexport" in record.message
                   for record in caplog.records)
        assert list(tmp_path.glob("plan_field*.txt"))

    def test_explicit_missing_beam_model_does_not_fall_back_to_a_config_name(self, tmp_path, monkeypatch, caplog):
        site = site_dir(tmp_path / "site")
        monkeypatch.chdir(tmp_path)
        assert plan_main([str(PLAN), "--config-dir", str(site), "-b", "./SITE_bm.csv"]) == 2
        assert "./SITE_bm.csv" in caplog.text
        assert not list(tmp_path.glob("plan_field*.txt"))


class TestIncludeInline:
    """-S pastes a file between marker lines; -s and -S keep their command-line order."""

    @pytest.fixture
    def extra(self, tmp_path):
        f = tmp_path / "extra.txt"
        f.write_text("i:Ts/Seed = 5\n")
        return f

    def export(self, tmp_path, *args) -> Path:
        assert study_main([str(STUDY), str(tmp_path / "topas.txt"), "-f", "1", "-N", "1000", "--batches", "1",
                           *args]) == 0
        return tmp_path / "topas_field01.txt"

    def test_the_table_pasted(self, tmp_path):
        output = self.export(tmp_path, "-S", "HUtoMaterialSchneider").read_bytes()
        payload = SHIPPED_TABLE.read_bytes()
        digest = hashlib.sha256(payload).hexdigest()
        begin = f"# BEGIN INCLUDE_INLINE: {SHIPPED_TABLE} sha256={digest}\n".encode()
        end = f"\n# END INCLUDE_INLINE: {SHIPPED_TABLE}\n".encode()
        assert begin + payload + end in output
        assert b"includeFile" not in output
        assert f"# INCLUDE_INLINE: {SHIPPED_TABLE} sha256={digest}".encode() in output.splitlines()

    @pytest.mark.parametrize("payload", [
        b"# M\xc3\xb8ller\r\niv:Review/Vector = 3 1\r\n2 3\r\n",
        b"i:Ts/Seed = 5\n\n\n",
        b"includeFile = runtime-only.txt",
        b"",
    ], ids=["utf8-crlf", "trailing-lfs", "nested-include-without-final-lf", "empty"])
    def test_inline_block_preserves_the_bytes_covered_by_the_hash(self, tmp_path, payload):
        source = tmp_path / "fragment.txt"
        source.write_bytes(payload)
        output = self.export(tmp_path, "-S", str(source)).read_bytes()
        begin = f"# BEGIN INCLUDE_INLINE: {source} sha256=".encode()
        end = f"# END INCLUDE_INLINE: {source}\n".encode()
        digest, framed_body = output.split(begin, 1)[1].split(b"\n", 1)
        block = framed_body.split(end, 1)[0]
        assert block == payload + b"\n"
        assert hashlib.sha256(block[:-1]).hexdigest().encode() == digest

    def test_order_is_kept_and_nothing_is_added(self, tmp_path, extra):
        text = self.export(tmp_path, "-S", str(extra), "-s", "HUtoMaterialSchneider").read_text(encoding="utf-8")
        include_line = f"includeFile                          = {SHIPPED_TABLE}"
        assert text.index(f"# BEGIN INCLUDE_INLINE: {extra}") < text.index(include_line)
        assert text.count("includeFile") == 1
        assert [line.split(":")[0] for line in text.splitlines() if line.startswith("# INCLUDE")] == [
            "# INCLUDE_INLINE", "# INCLUDE"]

    def test_any_s_or_S_replaces_the_default_table(self, tmp_path, extra):
        """Naming the table is the caller's job once anything is included; TOPAS reports a missing one."""
        text = self.export(tmp_path, "-S", str(extra)).read_text(encoding="utf-8")
        assert "includeFile" not in text
        assert str(SHIPPED_TABLE) not in text.split("# BEGIN INCLUDE_INLINE")[1]

    def test_an_unreadable_S_file_is_reported_not_raised(self, tmp_path, caplog):
        assert study_main([str(STUDY), str(tmp_path / "topas.txt"), "-S", str(tmp_path / "missing.txt")]) == 2
        assert "cannot read" in caplog.text
