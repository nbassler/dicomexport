import os
from typing import Any, ClassVar

import pytest


class TestListFiles:

    def setup_method(self):
        from dicomexport.gui.utils import BEAM_MODELS_DIR, CT_TO_MATERIAL_DIR, list_files
        self.list_files = list_files
        self.beam_models_dir = BEAM_MODELS_DIR
        self.ct_to_material_dir = CT_TO_MATERIAL_DIR

    def test_finds_csv_files(self):
        result = self.list_files(self.beam_models_dir, [".csv"])
        assert len(result) > 0, "Expected at least one beam model CSV"
        for name, path in result.items():
            assert path.suffix == ".csv"

    def test_finds_ct_to_material_tables(self):
        result = self.list_files(self.ct_to_material_dir, [".txt"])
        assert "HUtoMaterialSchneider.txt" in result

    def test_filters_by_suffix(self):
        result = self.list_files(self.beam_models_dir, [".txt"])
        assert len(result) == 0, "No .txt files expected in beam_models/"

    def test_keys_are_filenames(self):
        result = self.list_files(self.beam_models_dir, [".csv"])
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
