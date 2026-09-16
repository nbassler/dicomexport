import logging
from pathlib import Path

from dicomexport.model_ct import CTModel
from dicomexport.model_rtstruct import RTStruct
from dicomexport.topas_text import TopasText


logger = logging.getLogger(__name__)


def export_geo(ct: CTModel, rs: RTStruct, output_path: Path, nr_threads: int = 0) -> None:
    content = TopasGeo.generate(ct, rs, nr_threads=nr_threads)
    output_path.write_text(content)
    logger.info(f"Wrote Topas geometry file: {output_path.resolve()}")


class TopasGeo:
    @staticmethod
    def generate(ct: CTModel, rs: RTStruct, nr_threads: int = 0):
        """
        Export the CT and RTStruct models to a Topas-compatible geometry file.
        """
        lines = []
        lines.append("# Topas geometry file\n")
        lines.append(TopasText.setup(nr_threads=nr_threads))
        # No plan here, so the isocenter is unknown and assumed to be at the DICOM origin.
        lines.append(TopasText.world_setup(TopasText.world_half_lengths(ct)))
        lines.append(TopasText.geometry_patient(ct, rs))
        lines.append(TopasText.scorer_setup_dicom())
        topas_string = "\n".join(lines)
        return topas_string
