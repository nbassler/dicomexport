import sys
import logging

from dicomexport.parser_plan_export import create_parser
from dicomexport.beam_model import BeamModel
from dicomexport.import_plan import load_plan
from dicomexport.config import ConfigError
from dicomexport.export_plan import export_plan
from dicomexport.export_mcpl import generate_mcpl_file
from dicomexport.export_spotlist import export_spotlist
from dicomexport.parser_config import config_from_args, range_shifter_catalog_from_args
from dicomexport.parser_topas_options import check_options, options_from_args

logger = logging.getLogger(__name__)


def main(args=None) -> int:

    if args is None:
        args = sys.argv[1:]

    parser = create_parser()
    parsed_args = parser.parse_args(args)
    check_options(parser, parsed_args)

    if parsed_args.verbosity == 1:
        logging.basicConfig(level=logging.INFO)

    if parsed_args.verbosity > 1:
        logging.basicConfig(level=logging.DEBUG)

    # Check plan file
    if not parsed_args.fin.exists():
        logger.error(f"Input plan file not found: {parsed_args.fin}")
        return 1

    try:
        cfg = config_from_args(parsed_args)
        rs_catalog = range_shifter_catalog_from_args(parsed_args, cfg)
    except (ConfigError, ValueError) as e:
        logger.error("%s", e)
        return 2

    # load the plan
    pln = load_plan(parsed_args.fin, rs_catalog=rs_catalog)

    # -f is a DICOM BeamNumber (issue #96). Check it before exporting anything.
    if parsed_args.field_nr:
        try:
            pln.select_fields([parsed_args.field_nr])
        except ValueError as e:
            logger.error("-f %d: %s", parsed_args.field_nr, e)
            return 2

    if parsed_args.diag:
        print("Plan diagnostics:")
        print(pln)
        return 0

    # Next, load the beam model: -b, or the one the configuration directory makes unambiguous.
    try:
        bm_path = cfg.beam_model(parsed_args.fbm)
    except ConfigError as e:
        logger.error("%s", e)
        return 2
    if cfg.is_shipped:
        logger.warning(
            "Using the defaults shipped with dicomexport (%s). The shipped beam models and "
            "range shifters are examples. Set up a site configuration directory with --init-config.",
            cfg.path)
    logger.info("Beam model: %s", bm_path)

    pln.beam_model = BeamModel(bm_path,
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
            if parsed_args.field_nr else None,
            num_primaries=parsed_args.nstat,
            rng_seed=42,
            rot180x=(parsed_args.mcpl_frame == 'rotx180'),
        )

    elif parsed_args.export_fmt == 'topas':
        opts = options_from_args(parsed_args)
        if opts.beam_direction == 1:
            logger.warning(
                "--nozzle-side pos-z places the beam source at gantry+180 deg, mirroring "
                "every field (issue #66). Do not use it for patient plans; the IEC-correct "
                "setting is neg-z (the default).")
        if parsed_args.nr_threads != 0 and not parsed_args.test_mode:
            logger.info(
                "--threads has no effect without --test-mode: the plan-only Topas export "
                "writes a fragment with no setup block, so there is no Ts/NumberOfThreads "
                "line to set. Use the study export (dicomexport) for a complete input file.")
        export_plan(pln, pln.beam_model, parsed_args.fout,
                    field_nr=parsed_args.field_nr,
                    fmt=parsed_args.export_fmt,
                    test_mode=parsed_args.test_mode,
                    opts=opts)

    elif parsed_args.export_fmt == 'racehorse':
        # TODO
        pass

    elif parsed_args.export_fmt == 'spotlist':
        export_spotlist(
            pln,
            parsed_args.fout,
            field_list=[parsed_args.field_nr] if parsed_args.field_nr else None,
            col_count=parsed_args.spotlist_column_count,
            spot_pos_iso=parsed_args.spot_pos_iso,
        )

    else:
        logger.error(f"Unsupported export format: {parsed_args.export_fmt}")
        return 1

    return 0


if __name__ == '__main__':
    sys.exit(main())
