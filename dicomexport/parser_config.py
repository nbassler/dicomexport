"""CLI flags for the configuration directory and the files chosen from it (issue #112).

Shared by the study exporter (dicomexport) and the plan exporter (plan-export), so both
resolve -b, --config-dir and the range shifter catalog the same way.
"""
import argparse
import logging
from pathlib import Path

from dicomexport.config import ENV_VAR, ConfigDir, Include, find_config_dir
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
    parser.add_argument('-b', '--beam-model', dest=dest, default=None, metavar='BM',
                        help="Beam model: a CSV file, or the name of one in beam_models/ of the "
                             "configuration directory (with or without .csv). May be omitted when "
                             "the choice is unambiguous: with the shipped defaults it is "
                             "DCPT_beam_model__v5.csv, in a site's directory the only beam model "
                             "there. --list-config shows the choices.")


class _AppendInclude(argparse.Action):
    """-s and -S append to one list, so the files keep their command-line order."""

    def __call__(self, parser, namespace, values, option_string=None):
        includes = list(getattr(namespace, self.dest) or [])
        includes.append((values, self.const))
        setattr(namespace, self.dest, includes)


def add_includes(parser: argparse.ArgumentParser) -> None:
    parser.add_argument('-s', '--include', dest='includes', action=_AppendInclude, const=False, default=None,
                        metavar='FILE',
                        help="Include a TOPAS parameter file by path (an includeFile line), unread. "
                             "Usually the CT-number-to-material table, which must expect what the "
                             "CT holds, usually Hounsfield units. A bare name is looked up in "
                             "ct_to_material/ of the configuration directory (with or without .txt) "
                             "and written as an absolute path; any other path is written exactly as "
                             "given, so it may name a file that exists only where TOPAS runs. "
                             "Repeatable, with -S, in the order given. Without any -s or -S, the "
                             "configuration directory's only table is included. If an included "
                             "file sets a parameter dicomexport already writes, TOPAS silently "
                             "keeps dicomexport's value. With more than one included file, TOPAS "
                             "stops if two of them set the same parameter, or one sets a parameter "
                             "that has a TOPAS default, unless the TOPAS file itself sets it. "
                             "Use -S for such code.")
    parser.add_argument('-S', '--include-inline', dest='includes', action=_AppendInclude, const=True,
                        default=None, metavar='FILE',
                        help="Like -s, but paste the file into each TOPAS file, between "
                             "'# BEGIN INCLUDE_INLINE: FILE sha256=...' and "
                             "'# END INCLUDE_INLINE: FILE' lines. The file must be UTF-8 and exist "
                             "when exporting. Any nested includes and other referenced files "
                             "must be accessible to TOPAS at runtime. TOPAS normally rejects "
                             "duplicate definitions in the same file.")


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


def includes_from_args(args: argparse.Namespace, cfg: ConfigDir) -> list[Include]:
    """-s and -S in command-line order, or the configuration directory's only table."""
    given = getattr(args, 'includes', None)
    if not given:
        return [cfg.default_include()]
    return [cfg.include(arg, inline=inline) for arg, inline in given]


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
