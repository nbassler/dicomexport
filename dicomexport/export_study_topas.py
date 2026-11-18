import logging
from collections.abc import Sequence
from pathlib import Path
from typing import Optional

from dicomexport.config import Include
from dicomexport.model_ct import CTModel
from dicomexport.model_rtstruct import RTStruct
from dicomexport.beam_model import BeamModel
from dicomexport.topas_text import TopasText
from dicomexport.model_plan import Plan, Field
from dicomexport.export_plan_topas import TopasPlan
from dicomexport.topas_export_options import DEFAULTS, TopasExportOptions


logger = logging.getLogger(__name__)


def export_study_topas(ct: CTModel, rs: RTStruct, plan: Plan, output_base_path: Path,
                       field_nr: int = 0, dose_path: Optional[Path] = None,
                       opts: TopasExportOptions = DEFAULTS,
                       sources: Optional[Sequence[tuple[str, str]]] = None,
                       includes: Optional[Sequence[Include]] = None) -> None:
    """
    Export the CT and RTStruct models to a Topas-compatible geometry file.

    ``sources`` are (key, value) pairs naming the data files the export used, written into the
    header of every field file (issue #112). The exporter also records the files in
    ``includes``, usually the CT-number-to-material table, as it writes them.
    """

    # field_nr is a DICOM BeamNumber; 0 exports every field (issue #96).
    for field in plan.select_fields([field_nr] if field_nr else None):
        logger.info("=" * 50)
        logger.info(f'Exporting {field.label} = BeamNumber {field.number} "{field.name}"')
        logger.info("=" * 50)
        _export_study_field_topas(
            ct, rs, field, plan.beam_model, output_base_path, dose_path, opts=opts, sources=sources,
            includes=includes)
        logger.info("-" * 50 + "\n")


def _export_study_field_topas(ct: CTModel, rs: RTStruct, fld: Field, bm: Optional[BeamModel] = None,
                              output_base_path: Optional[Path] = None,
                              dose_path: Optional[Path] = None,
                              opts: TopasExportOptions = DEFAULTS,
                              sources: Optional[Sequence[tuple[str, str]]] = None,
                              includes: Optional[Sequence[Include]] = None) -> None:
    """
    Export a single field to a Topas-compatible geometry file.
    """
    isocenter = fld.layers[0].isocenter
    beam_reach = bm.beam_model_position if bm else 0.0
    world_hl = TopasText.world_half_lengths(ct, isocenter, beam_reach)
    logger.info("World half-lengths [cm]:      "
                f"({world_hl[0] / 10:.1f}, {world_hl[1] / 10:.1f}, {world_hl[2] / 10:.1f})")
    # The input file and the dose cube TOPAS writes share one name: topas_field03.txt writes
    # topas_field03.dcm (issue #96). The dose path has no directory and no suffix: TOPAS adds
    # the suffix and writes it where it runs.
    if output_base_path is None:
        output_base_path = Path("topas.txt")
    stem = f"{output_base_path.stem}_{fld.label}"

    nstat_scale = TopasPlan.calculate_scaling_factor(fld, opts.nstat)

    lines = []
    # Every spot's beam parameters, built once and used by every section below.
    table = TopasPlan.spot_table(fld, bm, opts.nstat, opts.beam_direction) if bm else None

    lines.append(TopasPlan.header(fld, table, opts, nstat_scale))
    source_lines = [*(sources or ()), *TopasText.include_sources(includes or ())]
    lines.append(TopasText.header2(source_lines))
    if includes:
        lines.append(TopasText.includes(includes))
    lines.append(TopasText.variables(fld, ct.dicom_origin))
    lines.append(TopasText.setup(nr_threads=opts.nr_threads, **TopasPlan._setup_kwargs(table, opts)))
    lines.append(TopasText.world_setup(world_hl))
    if dose_path:
        lines.append(TopasText.geometry_patient_dicom(dose_path, ct.directory))
    lines.append(TopasText.geometry_gantry())
    lines.append(TopasText.geometry_couch())
    lines.append(TopasText.geometry_dcm_to_iec())
    use_sources = opts.spot_mode == "sources"
    if not use_sources:
        lines.append(TopasText.geometry_beam_position_timefeature(
            bm.beam_model_position if bm else 0.0, beam_direction=opts.beam_direction))

    lines.append(TopasText.geometry_range_shifter(fld, beam_direction=opts.beam_direction))
    if not use_sources:
        lines.append(TopasText.field_beam_timefeature(topas_version=opts.topas_version))
    lines.append(TopasText.scorer_setup_dicom(
        topas_output_path=stem,
        dose_cube_16bit=opts.dose_cube_16bit))

    # For now, if no beam model is provided, spots and info are not shown.
    # This should be revisited in the future.
    # best would be to refactor the code to have a default beam model with basic parameters.
    # and move the load beam model from __init__.py to a new dedicated function in BeamModel class.
    if bm:
        if use_sources:
            lines.append(TopasPlan.sources_string(
                fld, bm, nstat=opts.nstat, beam_direction=opts.beam_direction,
                topas_version=opts.topas_version, table=table, batches=opts.n_batches))
        else:
            lines.append(TopasPlan.time_features_string(
                fld, bm, nstat=opts.nstat, beam_direction=opts.beam_direction, table=table))
        topas_string = "\n".join(lines)

        # show some information about the field
        TopasPlan.show_plan_data(fld, bm, nstat=opts.nstat)
    else:
        topas_string = "\n".join(lines)
        logger.warning(
            "No beam model provided. Limited conversion, TODO: fix this in the future.")

    output_path = output_base_path.with_name(f"{stem}.txt")
    output_path.write_text(topas_string, encoding="utf-8", newline="")
    logger.info(
        f"Wrote Topas geometry file for field {fld.number}: {output_path.resolve()}")
