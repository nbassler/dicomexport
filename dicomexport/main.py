import json
import sys
import logging
from pathlib import Path

from dicomexport.__version__ import __version__
from dicomexport.parser_main import create_parser
from dicomexport.beam_model import BeamModel
from dicomexport.config import ENV_VAR, ConfigDir, ConfigError, init_config_dir
from dicomexport.dicom_scan import RTDOSE, scan_study
from dicomexport.import_ct import load_ct
from dicomexport.import_rtstruct import load_rs
from dicomexport.import_plan import load_plan
from dicomexport.material_override import check_contours, resolve_overrides, warn_declared_overrides
from dicomexport.model_plan import range_shifter_catalog_of
from dicomexport.export_study_topas import export_study_topas
from dicomexport.parser_config import config_from_args, includes_from_args, range_shifter_catalog_from_args
from dicomexport.parser_topas_options import check_options, options_from_args

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
    check_options(parser, parsed_args)

    if parsed_args.verbosity == 1:
        logging.basicConfig(level=logging.INFO)

    if parsed_args.verbosity > 1:
        logging.basicConfig(level=logging.DEBUG)

    if parsed_args.init_config:
        return init_config(parsed_args.init_config)

    # Errors are logged and returned rather than raised: the Qt GUI runs main() in a thread
    # and shows the log, where an exception would end the thread without a word.
    try:
        cfg = config_from_args(parsed_args)
        if parsed_args.list_config:
            return list_config(cfg, parsed_args.list_config)
        if parsed_args.study_dir is None:
            parser.error("the following arguments are required: study_dir")
        bm_path = cfg.beam_model(parsed_args.bm)
        includes = includes_from_args(parsed_args, cfg)
        rs_catalog = range_shifter_catalog_from_args(parsed_args, cfg)
    except (ConfigError, ValueError) as e:
        logger.error("%s", e)
        return 2
    if cfg.is_shipped:
        logger.warning(
            "Using the defaults shipped with dicomexport (%s): DCPT's beam models, the OpenTOPAS "
            "example table and other centres' range shifters. They are examples, not your "
            "site's data. Set up a configuration directory with --init-config.", cfg.path)
    logger.info("Beam model: %s", bm_path)
    for inc in includes:
        logger.info("Including %s: %s", "inline" if inc.inline else "by path", inc.path)

    study_dir = parsed_args.study_dir
    # The RTSTRUCT and the plan first: checking the override names and the range shifters is
    # quick, loading the CT is not.
    rs = load_rs(study_dir)
    try:
        material_overrides = resolve_overrides(parsed_args.material_overrides, rs)
        # An unknown RangeShifterID, or an invalid plan, is reported like a configuration
        # error, not raised: the Qt GUI would lose an exception without a word (issue #129).
        pn = load_plan(study_dir, rs_catalog=rs_catalog)
    except ValueError as e:
        logger.error("%s", e)
        return 2
    warn_declared_overrides(rs, material_overrides)
    for o in material_overrides:
        logger.info("Material override: structure %r is %s", o.roi_name, o.material)

    ct = load_ct(study_dir)
    try:
        check_contours(material_overrides, rs.file_path, [img.image_position_patient[2] for img in ct.images])
    except ValueError as e:
        logger.error("%s", e)
        return 2
    bm = BeamModel(bm_path,
                   beam_model_position=parsed_args.beam_model_position)

    # -f is a DICOM BeamNumber (issue #96). Check it before exporting anything.
    if parsed_args.field_nr:
        try:
            pn.select_fields([parsed_args.field_nr])
        except ValueError as e:
            logger.error("-f %d: %s", parsed_args.field_nr, e)
            return 2

    pn.beam_model = bm
    pn.apply_beammodel()

    rd_path = get_path_dicom_dose(study_dir)

    # export the plan file
    if parsed_args.export_fmt == 'topas':
        opts = options_from_args(parsed_args)
        if opts.beam_direction == 1:
            logger.warning(
                "--nozzle-side pos-z places the beam source at gantry+180 deg, mirroring "
                "every field (issue #66). Do not use it for patient plans; the IEC-correct "
                "setting is neg-z (the default).")
        # Named in the header of every TOPAS file, so a run says which data it used.
        sources = [
            ("CONFIG_DIR", str(cfg)),
            ("BEAM_MODEL", str(bm_path)),
            ("RANGE_SHIFTER_CATALOG", rs_catalog.source),
        ]
        export_study_topas(ct, rs, pn,
                           parsed_args.output_base_path,
                           field_nr=parsed_args.field_nr,
                           dose_path=rd_path,
                           opts=opts,
                           sources=sources,
                           includes=includes,
                           material_overrides=material_overrides)
    elif parsed_args.export_fmt == 'mcpl':
        logger.error(
            "MCPL export is not implemented in the study CLI. Use the plan export "
            "instead: main_plan_export.py <plan.dcm> <out.mcpl> --export-fmt mcpl")
        return 2
    elif parsed_args.export_fmt == 'racehorse':
        logger.error("Racehorse export is not implemented yet in this build.")
        # Later: call your Racehorse exporter here.
        return 2
    else:
        logger.error("Unknown export format: %s", parsed_args.export_fmt)
        return 2

    return 0


def init_config(target: Path) -> int:
    """--init-config: copy the shipped defaults into target, never overwriting."""
    copied, skipped = init_config_dir(target)
    for p in copied:
        print(f"copied   {p}")
    for p in skipped:
        print(f"skipped  {p} (exists, left unchanged)")
    print(f"{len(copied)} copied, {len(skipped)} skipped. Edit the files in {target}; "
          f"dicomexport uses it when given as --config-dir, or as ${ENV_VAR}, "
          f"or when it is ~/.config/dicomexport or /etc/dicomexport.")
    return 0


def list_config(cfg: ConfigDir, fmt: str) -> int:
    """--list-config: what the configuration directory in effect offers."""
    catalog = range_shifter_catalog_of(cfg.path)
    listing = {"dicomexport_version": __version__, **cfg.listing(list(catalog))}
    if fmt == "json":
        print(json.dumps(listing, indent=2))
        return 0

    def show(title: str, entries: list) -> None:
        print(f"{title}:")
        for e in entries or [{"name": "(none)", "default": False}]:
            print(f"  {e['name']}{'  (default)' if e['default'] else ''}")

    print(f"Configuration directory: {cfg}")
    show("Beam models (-b)", listing["beam_models"])
    show("CT-number-to-material tables (-s/-S)", listing["ct_to_material"])
    rs = listing["range_shifters"]
    print(f"Range shifters ({rs['path']}{'' if rs['exists'] else ', missing'}):")
    print(f"  {', '.join(rs['ids']) or '(none)'}")
    m = listing["materials"]
    print(f"Materials (-S materials.txt): {m['path']}{'' if m['exists'] else ' (missing)'}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
