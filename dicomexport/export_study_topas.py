import logging
from pathlib import Path
from typing import Optional

from dicomexport.model_ct import CTModel
from dicomexport.model_rtstruct import RTStruct
from dicomexport.beam_model import BeamModel
from dicomexport.topas_text import TopasText
from dicomexport.model_plan import Plan, Field
from dicomexport.export_plan_topas import TopasPlan


logger = logging.getLogger(__name__)


def export_study_topas(ct: CTModel, rs: RTStruct, plan: Plan, output_base_path: Path,
                       field_nr: int = 0, dose_path: Optional[Path] = None, nstat: int = int(1e6)) -> None:
    """
    Export the CT and RTStruct models to a Topas-compatible geometry file.
    """

    if field_nr < 0 or field_nr >= len(plan.fields):
        raise ValueError(
            f"Invalid field number: {field_nr}. Must be between 0 and {len(plan.fields) - 1}.")
    if field_nr == 0:
        # Export all fields
        for field in plan.fields:
            logger.info("=" * 50)
            logger.info(
                f"Exporting field {field.number} to Topas geometry file...")
            logger.info("=" * 50)
            _export_study_field_topas(
                ct, rs, field, plan.beam_model, output_base_path, dose_path, nstat=nstat)
            logger.info("-" * 50 + "\n")
    else:
        # Export a single field
        field = plan.fields[field_nr]
        _export_study_field_topas(
            ct, rs, field, plan.beam_model, output_base_path, dose_path, nstat=nstat)


def _export_study_field_topas(ct: CTModel, rs: RTStruct, fld: Field, bm: Optional[BeamModel] = None,
                              output_base_path: Optional[Path] = None,
                              dose_path: Optional[Path] = None, nstat: int = int(1e6)) -> None:
    """
    Export a single field to a Topas-compatible geometry file.
    """
    # topas results will be written to output/field_number (no extension, will be handled by Topas
    # make target string for output file:
    if output_base_path:
        topas_output_file_str_no_suffix = output_base_path.with_name(
            f"{output_base_path.stem}_field{fld.number}")
    else:
        topas_output_file_str_no_suffix = Path(f"foobar_field{fld.number}")

    nstat_scale = TopasPlan.calculate_scaling_factor(fld, nstat)

    lines = []
    lines.append(TopasText.header(fld, nstat_scale, nstat))
    lines.append(TopasText.header2())
    if ct.spr_to_material_path:
        lines.append(TopasText.spr_to_material(ct.spr_to_material_path))
    lines.append(TopasText.variables(fld))
    lines.append(TopasText.setup())
    lines.append(TopasText.world_setup())
    if dose_path:
        lines.append(TopasText.geometry_patient_dicom(dose_path))
    lines.append(TopasText.geometry_gantry())
    lines.append(TopasText.geometry_couch())
    lines.append(TopasText.geometry_dcm_to_iec())
    if bm and bm.beam_model_position:
        lines.append(TopasText.geometry_beam_position_timefeature(
            bm.beam_model_position))
    else:
        lines.append(TopasText.geometry_beam_position_timefeature(0.0))

    lines.append(TopasText.geometry_range_shifter(fld))
    lines.append(TopasText.field_beam_timefeature())
    lines.append(TopasText.scorer_setup_dicom(
        topas_output_path=str(topas_output_file_str_no_suffix)))

    # For now, if no beam model is provided, spots and info are not shown.
    # This should be revisited in the future.
    # best would be to refactor the code to have a default beam model with basic parameters.
    # and move the load beam model from __init__.py to a new dedicated function in BeamModel class.
    if bm:
        lines.append(TopasPlan.time_features_string(
            fld, bm, nominal=True, nstat=nstat))
        topas_string = "\n".join(lines)

        # show some information about the field
        TopasPlan.show_plan_data(fld, bm, nstat=nstat)
    else:
        topas_string = "\n".join(lines)
        logger.warning(
            "No beam model provided. Limited conversion, TODO: fix this in the future.")

    if output_base_path is None:
        output_base_path = Path(f"topas_geometry_field{fld.number}")

    output_path = output_base_path.with_name(
        f"{output_base_path.stem}_field{fld.number:02d}.txt")
    output_path.write_text(topas_string)
    logger.info(
        f"Wrote Topas geometry file for field {fld.number}: {output_path.resolve()}")
