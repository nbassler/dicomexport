import logging
from pathlib import Path

from dicomexport.model_plan import Field, Plan
from dicomexport.beam_model import BeamModel
from dicomexport.export_plan_topas import TopasPlan
from dicomexport.export_plan_racehorse import RacehorsePlan
from dicomexport.topas_export_options import DEFAULTS, TopasExportOptions

logger = logging.getLogger(__name__)


# toplevel export plan method
def export_plan(pln: Plan, bm: BeamModel, output_base_path: Path, field_nr: int = 0,
                fmt: str = "topas", test_mode: bool = False,
                opts: TopasExportOptions = DEFAULTS) -> None:
    """
    Export one or all fields from a Plan to output files.
    field_nr is a DICOM BeamNumber; 0 exports every field (issue #96).
    """
    for field in pln.select_fields([field_nr] if field_nr else None):
        logger.info(f'Exporting {field.label} = BeamNumber {field.number} "{field.name}"')
        if fmt == "racehorse":
            # mono-energetic: one file per layer
            for layer_index, layer in enumerate(field.layers):
                p = _out_path(output_base_path, field, f"_layer{layer.number:02d}")
                text = RacehorsePlan.generate(field, layer_index, name=str(p), test_mode=False)
                p.write_text(text)
                logger.debug(f"Exported field {field.number} layer {layer.number} to Racehorse format.")
        elif fmt == "topas":
            text = TopasPlan.generate(field, bm, test_mode=test_mode, opts=opts)
            _out_path(output_base_path, field).write_text(text)
            logger.debug(f"Exported field {field.number} to Topas format.")
        else:
            raise ValueError(f"Unknown format: {fmt}")


def _out_path(base: Path, field: Field, extra: str = "") -> Path:
    return base.with_name(f"{base.stem}_{field.label}{extra}{base.suffix}")
