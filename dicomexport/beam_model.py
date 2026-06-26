import logging
import re
import numpy as np
from pathlib import Path

_BMODPOS_RE = re.compile(r'BMODPOS\s+(-?[\d.]+)\s*([a-zA-Z\xb5\xc2\xb5µ]*)')

logger = logging.getLogger(__name__)


def get_fwhm(sigma):
    return sigma * 2.0 * np.sqrt(2.0 * np.log(2.0))


def read_bmodpos(fn: Path) -> float | None:
    """Return the BMODPOS value in mm from the CSV header, or None if absent.

    Raises ValueError if the key is present but the unit is not 'mm'.
    """
    with open(fn) as f:
        for line in f:
            if not line.startswith('#'):
                break
            m = _BMODPOS_RE.search(line)
            if m:
                unit = m.group(2)
                if unit != 'mm':
                    raise ValueError(
                        f"BMODPOS unit must be 'mm', got "
                        f"'{unit or '(none)'}' in {Path(fn).name}")
                return float(m.group(1))
    return None


class BeamModel():
    """Beam model from a given CSV file."""

    def __init__(self, fn: Path, beam_model_position=None):
        """
        Load a beam model given as a CSV file.

        Header rows will be discarded and must be prefixed with '#'.

        Input columns for beam model:
            1) nominal energy [MeV]
            2) measured energy [MeV]
            3) energy spread 1 sigma [MeV]
            4) primary protons per MU [protons/MU]
            5) 1 sigma spot size x [mm]
            6) 1 sigma spot size y [mm]
            7) 1 sigma divergence x [rad]
            8) 1 sigma divergence y [rad]
            9) cor (x, x') [mm]
            10) cor (y, y') [mm]
        """
        data = np.genfromtxt(fn, delimiter=",", invalid_raise=False, comments='#')

        # lookup by nominal energy (first column)
        energy = data[:, 0]

        k = 'cubic'

        cols = len(data[0])
        logger.debug("Number of columns in beam model: %i", cols)

        # Defaults: no divergence / no correlation
        self.has_divergence = False
        self.f_divx = lambda E: 0.0
        self.f_divy = lambda E: 0.0
        self.f_corx = lambda E: 0.0
        self.f_cory = lambda E: 0.0

        try:
            from scipy.interpolate import interp1d
        except ImportError:
            logger.error("scipy is not installed, cannot interpolate beam model.")
            logger.error("Please install pymchelper[dicom] or pymchelper[all] to us this feature.")
            return

        if cols in (6, 10):
            self.f_en = interp1d(energy, data[:, 0], kind=k)  # nominal energy [MeV]
            self.f_e = interp1d(energy, data[:, 1], kind=k)  # measured energy [MeV]
            self.f_espread = interp1d(energy, data[:, 2], kind=k)  # energy spread 1 sigma [MeV]
            self.f_ppmu = interp1d(energy, data[:, 3], kind=k)  # protons per MU [protons/MU]
            self.f_sx = interp1d(energy, data[:, 4], kind=k)  # 1 sigma x [mm]
            self.f_sy = interp1d(energy, data[:, 5], kind=k)  # 1 sigma y [mm]
        else:
            logger.error("invalid column count")

        if cols == 10:
            logger.debug("Beam model has divergence data")
            self.has_divergence = True
            self.f_divx = interp1d(energy, data[:, 6], kind=k)  # divergence x [rad]
            self.f_divy = interp1d(energy, data[:, 7], kind=k)  # divergence y [rad]
            self.f_corx = interp1d(energy, data[:, 8], kind=k)  # correlation coef. rho (x, x') [-]
            self.f_cory = interp1d(energy, data[:, 9], kind=k)  # correlation coef. rho (y, y') [-]

        self.data = data
        self.filename = Path(fn).name

        _file_position = read_bmodpos(fn)

        if beam_model_position is None:
            if _file_position is not None:
                self.beam_model_position = _file_position
                logger.info("Beam model position from file header: %.1f mm", _file_position)
            else:
                self.beam_model_position = 500.0
                logger.warning("No BMODPOS in beam model file; using default %.1f mm", 500.0)
        else:
            if _file_position is not None and _file_position != beam_model_position:
                logger.warning(
                    "CLI beam model position (%.1f mm) overrides file BMODPOS (%.1f mm)",
                    beam_model_position, _file_position)
            self.beam_model_position = beam_model_position

        if self.beam_model_position <= 0.0:
            raise ValueError(
                f"beam_model_position must be > 0.0 mm (distance upstream of isocenter, "
                f"independent of beam transport direction), got {self.beam_model_position} mm")
