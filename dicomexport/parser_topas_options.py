"""CLI flags for TopasExportOptions, defined once and shared by every parser (#116, part of #3).

Each adder registers one flag with its default taken from TopasExportOptions, so a parser
only chooses which flags it offers. options_from_args() turns the parsed flags back into a
TopasExportOptions; options a parser does not offer keep their defaults.
"""
import argparse

from dicomexport.topas_export_options import DEFAULT_BATCHES, DEFAULTS, NOZZLE_SIDES, SPOT_MODES, TopasExportOptions
from dicomexport.topas_version import TOPAS_VERSION_HELP, parse_topas_version


def add_nstat(parser: argparse.ArgumentParser) -> None:
    parser.add_argument('-N', '--nstat', type=int, dest='nstat',
                        help="Target protons for simulation", default=DEFAULTS.nstat)


def add_threads(parser: argparse.ArgumentParser, note: str = "") -> None:
    parser.add_argument('--threads', type=int, dest='nr_threads', default=DEFAULTS.nr_threads,
                        help=f"TOPAS Ts/NumberOfThreads (default: {DEFAULTS.nr_threads}). 0 uses all cores on the "
                             "machine that RUNS the file, -1 all but one, N exactly N. "
                             "Resolved at run time, not at export time, so it is safe to "
                             "export on one node and run on another." + note)


def add_topas_version(parser: argparse.ArgumentParser, note: str = "") -> None:
    parser.add_argument('--topas-version', type=parse_topas_version, dest='topas_version',
                        default=DEFAULTS.topas_version, metavar='X.Y', help=TOPAS_VERSION_HELP + note)


def add_dose_cube_16bit(parser: argparse.ArgumentParser) -> None:
    parser.add_argument('--dose-cube-16bit', action='store_true', dest='dose_cube_16bit',
                        default=DEFAULTS.dose_cube_16bit,
                        help="Write the TOPAS DICOM dose cube with 16 instead of 32 bits per pixel. "
                             "Halves the file size, but every voxel below ~1.5e-5 of the field's "
                             "peak dose is written as 0, which can remove low-level out-of-field dose.")


def add_nozzle_side(parser: argparse.ArgumentParser) -> None:
    parser.add_argument('--nozzle-side', dest='nozzle_side', choices=list(NOZZLE_SIDES.values()),
                        default=DEFAULTS.nozzle_side,
                        help=f"Which side of the gantry-local Z axis the nozzle sits on (default: {DEFAULTS.nozzle_side}). "
                             "neg-z reproduces IEC 61217: at gantry 0 the beam enters an HFS patient "
                             "from the anterior side (verified against OpenTOPAS 4.2.3 and 4.3.0, issue #66). "
                             "pos-z mirrors the source to gantry+180 deg and is only meant for "
                             "non-patient research setups.")


def add_spot_mode(parser: argparse.ArgumentParser) -> None:
    parser.add_argument('--spot-mode', dest='spot_mode', choices=SPOT_MODES, default=DEFAULTS.spot_mode,
                        help=f"How TOPAS steps through the spots (default: {DEFAULTS.spot_mode}). "
                             "sources: one emittance source per spot, so the whole field is one "
                             "Geant4 run; much faster, because TOPAS merges every scorer after each "
                             "run. TOPAS's history count is then the event number, up to the largest "
                             "spot weight, not the number of protons. timefeature: one run per spot, "
                             "stepping a single source through the spots.")


def add_batches(parser: argparse.ArgumentParser) -> None:
    parser.add_argument('--batches', type=int, dest='batches', default=None, metavar='B',
                        help=f"Sources mode only: split each field into B identical TOPAS runs (default: "
                             f"{DEFAULT_BATCHES}). -N stays the total over all runs: each run simulates "
                             "1/B of every spot's protons, about N/B in all, so B does not multiply the "
                             "number of protons. A scorer with "
                             "Sc/<name>/OutputAfterRun writes one result per run, from which the "
                             "statistical uncertainty follows by batch means. The DICOM dose cube "
                             "adds up over all runs. Spot weights are rounded per run, so a larger B "
                             "needs a larger -N.")


def options_from_args(args: argparse.Namespace) -> TopasExportOptions:
    """Build the export options from parsed flags. Flags the parser does not offer keep their default."""
    nozzle_side = getattr(args, 'nozzle_side', DEFAULTS.nozzle_side)
    return TopasExportOptions(
        nstat=getattr(args, 'nstat', DEFAULTS.nstat),
        beam_direction=TopasExportOptions.beam_direction_of(nozzle_side),
        nr_threads=getattr(args, 'nr_threads', DEFAULTS.nr_threads),
        topas_version=getattr(args, 'topas_version', DEFAULTS.topas_version),
        dose_cube_16bit=getattr(args, 'dose_cube_16bit', DEFAULTS.dose_cube_16bit),
        spot_mode=getattr(args, 'spot_mode', DEFAULTS.spot_mode),
        batches=getattr(args, 'batches', DEFAULTS.batches),
    )


def check_options(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    """Fail at the command line, before any data is loaded, on flags that do not combine."""
    try:
        options_from_args(args)
    except ValueError as e:
        parser.error(str(e).replace("spot_mode", "--spot-mode").replace("batches", "--batches"))
