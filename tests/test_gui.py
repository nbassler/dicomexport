import os
import shutil
from pathlib import Path
from subprocess import CompletedProcess
from typing import Any, ClassVar
from unittest.mock import Mock

import pytest

from dicomexport.config import DEFAULTS_DIR, ENV_VAR, find_config_dir, init_config_dir


@pytest.fixture
def site_config(tmp_path, monkeypatch):
    site = tmp_path / "site"
    init_config_dir(site)
    tables = site / "ct_to_material"
    shutil.copyfile(tables / "HUtoMaterialSchneider.txt", tables / "HUtoMaterialSite.txt")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv(ENV_VAR, "site")
    return site


class TestGuiConfig:
    """The GUIs list the configuration directory in effect (issue #112)."""

    def test_lists_the_shipped_defaults_without_a_site_directory(self):
        from dicomexport.gui.utils import by_name, gui_config
        cfg = gui_config()
        assert cfg.path == DEFAULTS_DIR
        assert "HUtoMaterialSchneider.txt" in by_name(cfg.ct_to_material_tables())
        assert cfg.default_beam_model().name == "DCPT_beam_model__v5.csv"

    def test_lists_a_site_directory(self, tmp_path, monkeypatch):
        from dicomexport.gui.utils import by_name, gui_config
        (tmp_path / "beam_models").mkdir()
        (tmp_path / "beam_models" / "SITE_bm.csv").write_text("70,70,1,1,1,1\n")
        monkeypatch.setenv(ENV_VAR, str(tmp_path))
        assert list(by_name(gui_config().beam_models())) == ["SITE_bm.csv"]


class TestQtWindow:
    _app: ClassVar[Any] = None
    _window: ClassVar[Any] = None

    @classmethod
    def setup_class(cls):
        try:
            import PyQt6  # noqa: F401
        except ImportError:
            return
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
        from PyQt6.QtWidgets import QApplication
        from dicomexport.gui.qt_app import MainWindow
        cls._app = QApplication.instance() or QApplication([])
        cls._window = MainWindow(find_config_dir(DEFAULTS_DIR))

    def setup_method(self):
        if self._window is None:
            pytest.skip("PyQt6 not installed")

    def test_window_creates(self):
        assert self._window is not None

    def test_window_title_contains_version(self):
        from dicomexport.__version__ import __version__
        assert __version__ in self._window.windowTitle()

    def test_comboboxes_populated(self):
        assert self._window.beam_model.count() > 0
        assert self._window.spr_table.count() > 0

    def test_export_requires_an_explicit_choice_for_ambiguous_files(self, site_config, monkeypatch):
        from dicomexport.gui import qt_app

        worker = Mock()
        monkeypatch.setattr(qt_app, "ExportWorker", worker)
        window = qt_app.MainWindow()
        assert window.beam_model.currentIndex() == -1
        assert window.spr_table.currentIndex() == -1
        window.study_dir.setText(str(site_config.parent))

        window.btn_run.click()
        worker.assert_not_called()
        assert "Please select a beam model and a CT-number-to-material table." in window.log_output.toPlainText()

        window.beam_model.setCurrentText("DCPT_beam_model__v5.csv")
        window.btn_run.click()
        worker.assert_not_called()
        window.spr_table.setCurrentText("HUtoMaterialSite.txt")
        window.btn_run.click()
        args = worker.call_args.args[0]
        assert args[args.index("-b") + 1] == str(site_config / "beam_models" / "DCPT_beam_model__v5.csv")
        assert args[args.index("-s") + 1] == str(site_config / "ct_to_material" / "HUtoMaterialSite.txt")


@pytest.fixture
def streamlit_app(monkeypatch):
    testing = pytest.importorskip("streamlit.testing.v1")
    app_path = Path(__file__).resolve().parents[1] / "dicomexport" / "gui" / "app.py"
    app = testing.AppTest.from_file(str(app_path)).run()
    assert not app.exception
    run = Mock(return_value=CompletedProcess(args=[], returncode=0, stdout="", stderr=""))
    monkeypatch.setattr("subprocess.run", run)
    return app, run


def test_streamlit_uses_the_beam_model_position_unless_overridden(streamlit_app, tmp_path):
    app, run = streamlit_app
    assert app.selectbox[0].value == "DCPT_beam_model__v5.csv"
    app.text_input[0].set_value(str(tmp_path))
    app.button[0].click().run()
    assert "-p" not in run.call_args.args[0]

    app.checkbox[0].check().run()
    app.number_input[0].set_value(650.0)
    app.button[0].click().run()
    args = run.call_args.args[0]
    assert args[args.index("-p") + 1] == "650.0"


def test_streamlit_requires_an_explicit_choice_for_ambiguous_files(site_config, streamlit_app):
    app, run = streamlit_app
    assert app.selectbox[0].value is None
    assert app.selectbox[1].value is None
    app.text_input[0].set_value(str(site_config.parent))
    app.button[0].click().run()
    run.assert_not_called()
    assert len(app.error) == 2

    app.selectbox[0].set_value("DCPT_beam_model__v5.csv")
    app.button[0].click().run()
    run.assert_not_called()
    app.selectbox[1].set_value("HUtoMaterialSite.txt")
    app.button[0].click().run()
    args = run.call_args.args[0]
    assert args[args.index("-b") + 1] == str(site_config / "beam_models" / "DCPT_beam_model__v5.csv")
    assert args[args.index("-s") + 1] == str(site_config / "ct_to_material" / "HUtoMaterialSite.txt")


def test_streamlit_passes_a_typed_table_path_verbatim(streamlit_app, tmp_path, monkeypatch):
    app, run = streamlit_app
    monkeypatch.setenv(ENV_VAR, str(tmp_path))
    app.run()
    app.text_input[0].set_value(str(tmp_path))
    app.text_input[1].set_value(str(DEFAULTS_DIR / "beam_models" / "DCPT_beam_model__v5.csv"))
    app.text_input[2].set_value("./node-only/table.txt")
    app.button[0].click().run()
    args = run.call_args.args[0]
    assert args[args.index("-s") + 1] == "./node-only/table.txt"
