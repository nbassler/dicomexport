import logging
from pathlib import Path

from dicomexport.model_plan import Plan
from dicomexport.beam_model import BeamModel
from dicomexport.export_plan_topas import TopasPlan
from dicomexport.export_plan_racehorse import RacehorsePlan

logger = logging.getLogger(__name__)


# toplevel export plan method
def export_plan(pln: Plan, bm: BeamModel, output_base_path: Path, field_nr: int = -1,
                nominal: bool = True, nstat: int = int(1e6), fmt: str = "topas") -> None:
    """
    Export one or all fields from a Plan to output files.
    If field_nr >= 1, export only that field.
    If field_nr < 0, export all fields with field number appended.
    First field in a plan is field 1.
    """
    # pick fields
    if field_nr >= 1:
        fields = [(field_nr, pln.fields[field_nr - 1])]
    else:
        fields = list(enumerate(pln.fields))

    for idx, field in fields:
        if fmt == "racehorse":
            # mono-energetic: one file per layer
            for layer_index, layer in enumerate(field.layers):
                p = _out_path(output_base_path, field.number, f"_layer{layer.number:02d}")
                text = RacehorsePlan.generate(field, layer_index, name=str(p), test_mode=False)
                p.write_text(text)
                logger.debug(f"Exported field {field.number} layer {layer.number} to Racehorse format.")
        elif fmt == "topas":
            text = TopasPlan.generate(field, bm, nominal=nominal, nstat=nstat)
            _out_path(output_base_path, field.number).write_text(text)
            logger.debug(f"Exported field {field.number} to Topas format.")
        else:
            raise ValueError(f"Unknown format: {fmt}")


def _out_path(base: Path, field_idx: int, extra: str = "") -> Path:
    return base.with_name(f"{base.stem}_field{field_idx:02d}{extra}{base.suffix}")
