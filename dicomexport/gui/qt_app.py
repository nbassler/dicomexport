import sys
from pathlib import Path

from PyQt6 import uic
from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtWidgets import QApplication, QFileDialog, QMainWindow, QMessageBox

from dicomexport.__version__ import __version__
from dicomexport.beam_model import read_bmodpos
from dicomexport.config import ConfigError
from dicomexport.gui.utils import by_name, gui_config
from dicomexport.main import main as dicomexport_main
from dicomexport.parser_main import create_parser

if getattr(sys, "frozen", False):
    UI_FILE = Path(sys._MEIPASS) / "dicomexport" / "gui" / "main_window.ui"
else:
    UI_FILE = Path(__file__).parent / "main_window.ui"


class ExportWorker(QThread):
    """Runs dicomexport_main in a background thread."""
    finished = pyqtSignal(int)   # exit code
    log = pyqtSignal(str)        # log line

    def __init__(self, args: list):
        super().__init__()
        self._args = args

    def run(self):
        import logging

        class QtHandler(logging.Handler):
            def __init__(self, signal):
                super().__init__()
                self._signal = signal

            def emit(self, record):
                self._signal.emit(self.format(record))

        handler = QtHandler(self.log)
        handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
        logger = logging.getLogger("dicomexport")
        prev_level = logger.level
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)

        try:
            rc = dicomexport_main(self._args)
        except Exception as e:
            self.log.emit(f"ERROR: {e}")
            rc = 1
        finally:
            logger.removeHandler(handler)
            logger.setLevel(prev_level)

        self.finished.emit(rc)


class MainWindow(QMainWindow):
    def __init__(self, cfg=None):
        super().__init__()
        uic.loadUi(UI_FILE, self)
        self.setWindowTitle(f"DICOM Export {__version__}")

        # The configuration directory in effect (issue #112). It is passed on as --config-dir,
        # so the export also takes its range shifter catalog from the directory listed here.
        self._cfg = cfg if cfg is not None else gui_config()
        self._beam_models = by_name(self._cfg.beam_models())
        self._ct_tables = by_name(self._cfg.ct_to_material_tables())

        self.beam_model.addItems(self._beam_models.keys())
        self.ct_table.addItems(self._ct_tables.keys())
        default_bm = self._cfg.default_beam_model()
        default_table = self._cfg.default_ct_to_material_table()
        self.beam_model.setPlaceholderText("Select a beam model")
        self.ct_table.setPlaceholderText("Select a CT-number-to-material table")
        self.beam_model.setCurrentIndex(self.beam_model.findText(default_bm.name) if default_bm else -1)
        self.ct_table.setCurrentIndex(self.ct_table.findText(default_table.name) if default_table else -1)
        self.log_output.append(f"Configuration directory: {self._cfg}")

        # Populate defaults from the parser (single source of truth)
        _p = create_parser()
        self.field_nr.setValue(_p.get_default("field_nr"))
        self.nstat.setValue(_p.get_default("nstat"))
        self.output_base.setText(str(_p.get_default("output_base_path")))

        self.beam_model.currentIndexChanged.connect(self._on_beam_model_changed)
        self._on_beam_model_changed()  # populate position for the initial selection

        self.btn_study_dir.clicked.connect(self._browse_study_dir)
        self.btn_run.clicked.connect(self._run_export)

        self._worker = None

    def _on_beam_model_changed(self):
        bm_path = self._beam_models.get(self.beam_model.currentText())
        if bm_path:
            pos = read_bmodpos(bm_path)
            self.bm_position.setValue(pos if pos is not None else 500.0)

    def _browse_study_dir(self):
        path = QFileDialog.getExistingDirectory(self, "Select study directory")
        if path:
            self.study_dir.setText(path)

    def _run_export(self):
        study_dir = self.study_dir.text().strip()
        if not study_dir:
            self.log_output.append("ERROR: Please select a study directory.")
            return

        beam_model = self._beam_models.get(self.beam_model.currentText())
        ct_table = self._ct_tables.get(self.ct_table.currentText())
        if beam_model is None or ct_table is None:
            self.log_output.append("ERROR: Please select a beam model and a CT-number-to-material table.")
            return

        args = [
            study_dir,
            self.output_base.text(),
            "-b", str(beam_model),
            "-s", str(ct_table),
            "--config-dir", str(self._cfg.path),
            "-p", str(self.bm_position.value()),
            "-f", str(self.field_nr.value()),
            "-N", str(self.nstat.value()),
        ]

        self.log_output.clear()
        self.btn_run.setEnabled(False)

        self._worker = ExportWorker(args)
        self._worker.log.connect(self.log_output.append)
        self._worker.finished.connect(self._on_finished)
        self._worker.start()

    def _on_finished(self, rc: int):
        if rc == 0:
            self.log_output.append("Export completed successfully.")
        else:
            self.log_output.append(f"Export failed (exit code {rc}).")
        self.btn_run.setEnabled(True)


def main():
    app = QApplication(sys.argv)
    try:
        cfg = gui_config()
    except ConfigError as e:
        QMessageBox.critical(None, "Configuration directory", str(e))
        sys.exit(1)
    if not cfg.beam_models() or not cfg.ct_to_material_tables():
        QMessageBox.critical(
            None, "Missing data",
            f"The configuration directory {cfg} has no beam models or no "
            f"CT-number-to-material tables.\n\n"
            "With the shipped defaults, the installation is incomplete: in a standalone "
            "build, the 'defaults' folder must be in the same folder as the executable.")
        sys.exit(1)
    window = MainWindow(cfg)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
