import sys
from pathlib import Path

from PyQt6 import uic
from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtWidgets import QApplication, QFileDialog, QMainWindow, QMessageBox

from dicomexport.__version__ import __version__
from dicomexport.main import main as dicomexport_main
from dicomexport.parser_main import create_parser

UI_FILE = Path(__file__).parent / "main_window.ui"
PROJECT_ROOT = Path(__file__).parent.parent.parent
BEAM_MODELS_DIR = PROJECT_ROOT / "res" / "beam_models"
SPR_TABLES_DIR = PROJECT_ROOT / "res" / "spr_tables"


def list_files(folder: Path, suffixes: list) -> dict:
    return {f.name: f for f in sorted(folder.iterdir()) if f.suffix in suffixes}


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
        root_logger = logging.getLogger()
        root_logger.addHandler(handler)
        root_logger.setLevel(logging.INFO)

        try:
            rc = dicomexport_main(self._args)
        except Exception as e:
            self.log.emit(f"ERROR: {e}")
            rc = 1
        finally:
            root_logger.removeHandler(handler)

        self.finished.emit(rc)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        uic.loadUi(UI_FILE, self)
        self.setWindowTitle(f"DICOM Export {__version__}")

        self._beam_models = list_files(BEAM_MODELS_DIR, [".csv"])
        self._spr_tables = list_files(SPR_TABLES_DIR, [".csv", ".txt"])

        self.beam_model.addItems(self._beam_models.keys())
        self.spr_table.addItems(self._spr_tables.keys())

        # Populate defaults from the parser (single source of truth)
        _p = create_parser()
        self.bm_position.setValue(_p.get_default("beam_model_position"))
        self.field_nr.setValue(_p.get_default("field_nr"))
        self.nstat.setValue(_p.get_default("nstat"))
        self.output_base.setText(str(_p.get_default("output_base_path")))

        self.btn_study_dir.clicked.connect(self._browse_study_dir)
        self.btn_run.clicked.connect(self._run_export)

        self._worker = None

    def _browse_study_dir(self):
        path = QFileDialog.getExistingDirectory(self, "Select study directory")
        if path:
            self.study_dir.setText(path)

    def _run_export(self):
        study_dir = self.study_dir.text().strip()
        if not study_dir:
            self.log_output.append("ERROR: Please select a study directory.")
            return

        beam_model = str(self._beam_models[self.beam_model.currentText()])
        spr_table = str(self._spr_tables[self.spr_table.currentText()])

        args = [
            study_dir,
            self.output_base.text(),
            "-b", beam_model,
            "-s", spr_table,
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
    if not BEAM_MODELS_DIR.exists() or not SPR_TABLES_DIR.exists():
        QMessageBox.critical(
            None, "Missing resources",
            f"Could not find the required resource folders:\n"
            f"  {BEAM_MODELS_DIR}\n"
            f"  {SPR_TABLES_DIR}\n\n"
            "Make sure 'res/' is in the same folder as the executable.")
        sys.exit(1)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
