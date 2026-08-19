import sys
import logging

from dicomexport.parser_plan_export import create_parser
from dicomexport.beam_model import BeamModel
from dicomexport.import_plan import load_plan
from dicomexport.model_plan import load_range_shifter_catalog
from dicomexport.export_plan import export_plan
from dicomexport.export_mcpl import generate_mcpl_file
from dicomexport.export_spotlist import export_spotlist

logger = logging.getLogger(__name__)


def main(args=None) -> int:

    if args is None:
        args = sys.argv[1:]

    parser = create_parser()
    parsed_args = parser.parse_args(args)

    if parsed_args.verbosity == 1:
        logging.basicConfig(level=logging.INFO)

    if parsed_args.verbosity > 1:
        logging.basicConfig(level=logging.DEBUG)

    # Check plan file
    if not parsed_args.fin.exists():
        logger.error(f"Input plan file not found: {parsed_args.fin}")
        return 1

    # load the plan
    rs_catalog = (load_range_shifter_catalog(parsed_args.rs_catalog_path)
                  if parsed_args.rs_catalog_path else None)
    pln = load_plan(parsed_args.fin, rs_catalog=rs_catalog)

    if parsed_args.diag:
        print("Plan diagnostics:")
        print(pln)
        return 0

    # Next, load the beam model.
    if not parsed_args.fbm:
        logger.error(
            "No beam model provided. Use -b to specify a beam model CSV file.")
        raise ValueError("Beam model file is required.")

    pln.beam_model = BeamModel(parsed_args.fbm,
                               beam_model_position=parsed_args.beam_model_position)
    logger.debug("Applying beam model to plan...")
    pln.apply_beammodel()

    logger.debug("Exporting plan format...")
    if parsed_args.export_fmt == 'mcpl':
        if parsed_args.nozzle_side != 'neg-z':
            logger.info(
                "--nozzle-side does not apply to MCPL export (the phase space is "
                "frame-relative / pre-gantry). Use --mcpl-frame to choose the beam frame.")
        generate_mcpl_file(
            pln,
            pln.beam_model,
            output_path=parsed_args.fout,
            field_list=[parsed_args.field_nr]
            if parsed_args.field_nr > 0 else None,
            num_primaries=parsed_args.nstat,
            rng_seed=42,
            rot180x=(parsed_args.mcpl_frame == 'rotx180'),
        )

    elif parsed_args.export_fmt == 'topas':
        beam_direction = 1 if parsed_args.nozzle_side == 'pos-z' else -1
        if beam_direction == 1:
            logger.warning(
                "--nozzle-side pos-z places the beam source at gantry+180 deg, mirroring "
                "every field (issue #66). Do not use it for patient plans; the IEC-correct "
                "setting is neg-z (the default).")
        export_plan(pln, pln.beam_model, parsed_args.fout,
                    field_nr=parsed_args.field_nr,
                    nstat=parsed_args.nstat,
                    fmt=parsed_args.export_fmt,
                    test_mode=parsed_args.test_mode,
                    beam_direction=beam_direction)

    elif parsed_args.export_fmt == 'racehorse':
        # TODO
        pass

    elif parsed_args.export_fmt == 'spotlist':
        export_spotlist(
            pln,
            parsed_args.fout,
            field_list=[parsed_args.field_nr] if parsed_args.field_nr > 0 else None,
            col_count=parsed_args.spotlist_column_count,
            spot_pos_iso=parsed_args.spot_pos_iso,
        )

    else:
        logger.error(f"Unsupported export format: {parsed_args.export_fmt}")
        return 1

    return 0


if __name__ == '__main__':
    sys.exit(main())
