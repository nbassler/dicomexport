# placeholder for geometry export functionality
import sys
import logging
from pathlib import Path

from dicomexport.parser_main import create_parser
from dicomexport.beam_model import BeamModel
from dicomexport.dicom_scan import RTDOSE, scan_study
from dicomexport.import_ct import load_ct
from dicomexport.import_rtstruct import load_rs
from dicomexport.import_plan import load_plan
from dicomexport.export_study_topas import export_study_topas

logger = logging.getLogger(__name__)


def get_path_dicom_dose(study_dir: Path) -> Path:
    """
    Get the path to the DICOM RTDOSE file in the study directory.

    Selected by Modality header rather than an RD*.dcm glob (issue #77).
    """
    # scan_study() returns files sorted by path, so the choice is reproducible.
    dose_files = scan_study(study_dir).get(RTDOSE)
    if not dose_files:
        raise FileNotFoundError(
            f"No DICOM RTDOSE file (Modality=RTDOSE) found in {study_dir} or its subdirectories.")
    if len(dose_files) > 1:
        # Only the dose grid geometry is cloned from this file, not the dose values,
        # so any of them will do as long as the choice does not vary between runs.
        logger.warning(
            "Multiple DICOM RTDOSE files found, using the first one: %s", dose_files[0].name)
    logger.info("Using RTDOSE file: %s", dose_files[0].name)
    return dose_files[0]


def main(args=None) -> int:

    if args is None:
        args = sys.argv[1:]

    parser = create_parser()
    parsed_args = parser.parse_args(args)

    if parsed_args.verbosity == 1:
        logging.basicConfig(level=logging.INFO)

    if parsed_args.verbosity > 1:
        logging.basicConfig(level=logging.DEBUG)

    # load the CT files
    study_dir = parsed_args.study_dir
    ct = load_ct(study_dir)
    ct.spr_to_material_path = parsed_args.spr_to_material_path

    rs = load_rs(study_dir)
    bm = BeamModel(parsed_args.bm,
                   beam_model_position=parsed_args.beam_model_position)

    pn = load_plan(study_dir)
    pn.beam_model = bm
    pn.apply_beammodel()

    rd_path = get_path_dicom_dose(study_dir)

    # export the plan file
    if parsed_args.export_fmt == 'topas':
        beam_direction = 1 if parsed_args.nozzle_side == 'pos-z' else -1
        if beam_direction == 1:
            logger.warning(
                "--nozzle-side pos-z places the beam source at gantry+180 deg, mirroring "
                "every field (issue #66). Do not use it for patient plans; the IEC-correct "
                "setting is neg-z (the default).")
        export_study_topas(ct, rs, pn,
                           parsed_args.output_base_path,
                           field_nr=parsed_args.field_nr,
                           dose_path=rd_path,
                           nstat=parsed_args.nstat,
                           beam_direction=beam_direction)
    elif parsed_args.export_fmt == 'phasespace':
        logger.error("Phasespace export is not implemented yet in this build.")
        # Later: call your MCPL exporter here.
        return 2
    elif parsed_args.export_fmt == 'racehorse':
        logger.error("Racehorse export is not implemented yet in this build.")
        # Later: call your Racehorse exporter here.
        return 2
    else:
        logger.error("Unknown export format: %s", parsed_args.export_fmt)
        return 2

    return 0


if __name__ == '__main__':
    sys.exit(main())
