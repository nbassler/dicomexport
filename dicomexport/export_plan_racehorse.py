import logging
import datetime

from dicomexport.__version__ import __version__
from dicomexport.model_plan import Field
import numpy as np


logger = logging.getLogger(__name__)


class RacehorsePlan:
    @staticmethod
    def generate(myfield: Field, layer_index: int, name="", test_mode=False) -> str:
        """
        Export the field to a Varian Racehorse Mode input file.
        """

        c = "* ----- RACEHORSE Spot List -----\n"

        check_total_mu = 0.0  # TODO

        layer = myfield.layers[layer_index]
        c += f"* Field: {myfield.number:02d}"  # no newline
        c += f"  Layer: {layer.number:02d}\n"  # TODO: nominal energy, but does RACEHORSE allow for it?
        c += "\n"
        c += _racehorse_header(name)

        for n, spot in enumerate(layer.spots):
            c += f"{n:2d},{spot.x:8.2f},{spot.y:8.2f},{spot.mu:8.2f}\n"  # index, mm, mm, monitor units
            check_total_mu += spot.mu

        if not np.isclose(check_total_mu, layer.cum_mu, rtol=1e-4):
            raise ValueError(
                f"Total MU for layer {layer.number:02d}: {check_total_mu:.4f} differs from expected {layer.cum_mu:.4f} by more than 0.01%."
            )

        return c


def _racehorse_header(name: str = "") -> str:
    """
    Generate the header for the Racehorse input file.
    """

    dt = datetime.datetime.now()
    tmstr = dt.strftime("%d-%m-%Y")

    h = "#HEADER\n"
    h += f"NAME, {name}\n"
    h += f"DATE, {tmstr}\n"
    h += "CREATORNAME, DicomExport\n"
    h += f"CREATORVERSION, {__version__}\n"
    h += "\n"

    v = "#VALUES\n"
    v += "Index;Position x;Position y;Dose\n"  # if RACEHORSE allows for it, rename "Dose" to "MU", units in mm

    return h + v
