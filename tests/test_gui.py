import os
from pathlib import Path
from typing import Any, ClassVar

import pytest


class TestListFiles:

    def setup_method(self):
        from dicomexport.gui.utils import list_files
        self.list_files = list_files

    def test_finds_csv_files(self):
        result = self.list_files(Path("res/beam_models"), [".csv"])
        assert len(result) > 0, "Expected at least one beam model CSV"
        for name, path in result.items():
            assert path.suffix == ".csv"

    def test_finds_spr_tables(self):
        result = self.list_files(Path("res/spr_tables"), [".csv", ".txt"])
        assert len(result) > 0, "Expected at least one SPR table"

    def test_filters_by_suffix(self):
        result = self.list_files(Path("res/beam_models"), [".txt"])
        assert len(result) == 0, "No .txt files expected in beam_models/"

    def test_keys_are_filenames(self):
        result = self.list_files(Path("res/beam_models"), [".csv"])
        for name, path in result.items():
            assert name == path.name


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
