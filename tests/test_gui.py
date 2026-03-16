import os
import unittest
from pathlib import Path
from typing import Any, ClassVar


class TestListFiles(unittest.TestCase):
    """Tests for the list_files helper used by both gui apps."""

    def setUp(self):
        # Import here so the test doesn't fail if PyQt6 is absent
        from dicomexport.gui.qt_app import list_files
        self.list_files = list_files

    def test_finds_csv_files(self):
        folder = Path("res/beam_models")
        result = self.list_files(folder, [".csv"])
        self.assertTrue(len(result) > 0, "Expected at least one beam model CSV")
        for name, path in result.items():
            self.assertEqual(path.suffix, ".csv")

    def test_finds_spr_tables(self):
        folder = Path("res/spr_tables")
        result = self.list_files(folder, [".csv", ".txt"])
        self.assertTrue(len(result) > 0, "Expected at least one SPR table")

    def test_filters_by_suffix(self):
        folder = Path("res/beam_models")
        result = self.list_files(folder, [".txt"])
        self.assertEqual(len(result), 0, "No .txt files expected in beam_models/")

    def test_keys_are_filenames(self):
        folder = Path("res/beam_models")
        result = self.list_files(folder, [".csv"])
        for name, path in result.items():
            self.assertEqual(name, path.name)


class TestQtWindow(unittest.TestCase):
    """Minimal headless smoke test for the Qt MainWindow."""

    _app: ClassVar[Any] = None
    _window: ClassVar[Any] = None

    @classmethod
    def setUpClass(cls):
        try:
            import PyQt6  # noqa: F401
        except ImportError:
            return
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
        from PyQt6.QtWidgets import QApplication
        from dicomexport.gui.qt_app import MainWindow
        cls._app = QApplication.instance() or QApplication([])
        cls._window = MainWindow()

    def setUp(self):
        if self._window is None:
            self.skipTest("PyQt6 not installed")

    def test_window_creates(self):
        self.assertIsNotNone(self._window)

    def test_window_title_contains_version(self):
        from dicomexport.__version__ import __version__
        self.assertIn(__version__, self._window.windowTitle())

    def test_comboboxes_populated(self):
        self.assertGreater(self._window.beam_model.count(), 0)
        self.assertGreater(self._window.spr_table.count(), 0)


if __name__ == "__main__":
    unittest.main()
