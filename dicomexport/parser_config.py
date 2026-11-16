"""CLI flags for the configuration directory and the files chosen from it (issue #112).

Shared by the study exporter (dicomexport) and the plan exporter (plan-export), so both
resolve -b, --config-dir and the range shifter catalog the same way.
"""
import argparse
import logging
from pathlib import Path

from dicomexport.config import ENV_VAR, ConfigDir, find_config_dir
from dicomexport.model_plan import RangeShifterCatalog, load_range_shifter_catalog, range_shifter_catalog_of

logger = logging.getLogger(__name__)

CONFIG_DIR_HELP = (
    "Configuration directory holding beam_models/, ct_to_material/ and range_shifters.csv. "
    f"If not given: ${ENV_VAR}, then ~/.config/dicomexport (%%APPDATA%%\\dicomexport on Windows), "
    "then /etc/dicomexport, then the defaults shipped with dicomexport; the first that exists "
    "is used, and only that one. Create one with --init-config DIR.")


def add_config_dir(parser: argparse.ArgumentParser) -> None:
    parser.add_argument('--config-dir', type=Path, dest='config_dir', default=None, metavar='DIR',
                        help=CONFIG_DIR_HELP)


def add_beam_model(parser: argparse.ArgumentParser, dest: str) -> None:
    parser.add_argument('-b', '--beam-model', type=Path, dest=dest, default=None, metavar='BM',
                        help="Beam model: a CSV file, or the name of one in beam_models/ of the "
                             "configuration directory (with or without .csv). May be omitted when "
                             "the choice is unambiguous: with the shipped defaults it is "
                             "DCPT_beam_model__v5.csv, in a site's directory the only beam model "
                             "there. --list-config shows the choices.")


def add_range_shifter_catalog(parser: argparse.ArgumentParser) -> None:
    parser.add_argument('--range-shifter-catalog', type=Path, dest='rs_catalog_path', default=None,
                        help="Range shifter catalog CSV. REPLACES range_shifters.csv of the "
                             "configuration directory, so it must list every range shifter the "
                             "plan uses. The README.md of the shipped defaults describes the format.")


def config_from_args(args: argparse.Namespace) -> ConfigDir:
    """The configuration directory in effect. Raises config.ConfigError for a bad --config-dir."""
    cfg = find_config_dir(getattr(args, 'config_dir', None))
    logger.info("Configuration directory: %s", cfg)
    return cfg


def range_shifter_catalog_from_args(args: argparse.Namespace, cfg: ConfigDir) -> RangeShifterCatalog:
    """--range-shifter-catalog if given, else range_shifters.csv of the configuration directory."""
    if getattr(args, 'rs_catalog_path', None):
        catalog = load_range_shifter_catalog(args.rs_catalog_path)
        logger.info("Range shifter catalog %s replaces the one in the configuration directory: %s",
                    args.rs_catalog_path, ", ".join(catalog) or "(none)")
        return catalog
    catalog = range_shifter_catalog_of(cfg.path)
    logger.info("Range shifter catalog %s: %s", catalog.source, ", ".join(catalog) or "(none)")
    return catalog
