import os
from typing import Any, ClassVar

import pytest


class TestGuiConfig:
    """The GUIs list the configuration directory in effect (issue #112)."""

    def test_lists_the_shipped_defaults_without_a_site_directory(self):
        from dicomexport.config import DEFAULTS_DIR
        from dicomexport.gui.utils import by_name, gui_config
        cfg = gui_config()
        assert cfg.path == DEFAULTS_DIR
        assert "HUtoMaterialSchneider.txt" in by_name(cfg.ct_to_material_tables())
        assert cfg.default_beam_model().name == "DCPT_beam_model__v5.csv"

    def test_lists_a_site_directory(self, tmp_path, monkeypatch):
        from dicomexport.config import ENV_VAR
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
        cls._window = MainWindow()

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
