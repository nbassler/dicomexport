import argparse
from pathlib import Path

from dicomexport.__version__ import __version__


def create_parser():
    parser = argparse.ArgumentParser(
        description="Convert DICOM-RT Ion plans to MC-compatible spot lists using a beam model."
    )

    parser.add_argument('fin', type=Path, help="Input DICOM-RN or IBA .pld file")
    parser.add_argument('fout', nargs='?', type=Path, default="plan.txt",
                        help="Output file, default: plan.txt. Field number will be "
                        "appended automatically to the name before the extension.")
    parser.add_argument('-b', '--beam-model', type=Path, dest='fbm', help="Beam model CSV path", default=None)
    parser.add_argument('-p', '--beam-model-position', type=float, dest='beam_model_position',
                        help="Beam model position in mm, relative to isocenter, positive upstream. "
                        "If not given, the value is read from the BMODPOS key in the beam model file "
                        "header, or defaults to 500.0 mm if absent.",
                        default=None)
    parser.add_argument('--range-shifter-catalog', type=Path, dest='rs_catalog_path', default=None,
                        help="Range shifter catalog CSV. REPLACES the built-in catalog, so it "
                             "must list every range shifter the plan uses. "
                             "See res/range_shifters/README.md.")
    parser.add_argument('-f', '--field', type=int, dest='field_nr', default=0,
                        help="Field number to export. If not specified, all fields will be exported.")
    parser.add_argument('-d', '--diag', action='store_true', dest="diag",
                        help="Print plan diagnostics and exit", default=False)
    parser.add_argument('-s', '--scale', type=float, dest='scale',
                        help="additional scaling multiplier for MC plan", default=1.0)
    parser.add_argument('-N', '--nstat', type=int, dest='nstat', help="Target protons for simulation", default=int(1e6))
    parser.add_argument('-nc', '--spotlist-column-count', type=int, dest='spotlist_column_count',
                        choices=[5, 6, 7, 9, 11], default=11,
                        help="Number of columns in the spotlist export. Valid values: 5, 6, 7, 9, or 11 (default: 11).")

    parser.add_argument(
        '--export-fmt', dest='export_fmt', choices=['topas', 'mcpl', 'racehorse', 'spotlist'], default='topas',
        help=("Export format (default: topas). "
              "Formats: topas (*.txt), mcpl (*.mcpl), racehorse (*.csv), spotlist (*.txt).")
    )

    parser.add_argument('--spot-pos-iso', action='store_true', dest='spot_pos_iso', default=False,
                        help="Export spot X/Y positions at isocenter (z=0) instead of the beam model plane. "
                             "Spot sizes, divergences, and correlations are still taken from the beam model.")

    parser.add_argument('--test-mode', action='store_true', dest='test_mode', default=False,
                        help="Generate a self-contained Topas file (no DICOM patient) with a water box "
                             "and isocenter dose scorer. Useful for CI beam-direction checks.")

    parser.add_argument('--mcpl-frame', dest='mcpl_frame', choices=['iec', 'rotx180'],
                        default='iec',
                        help="Coordinate frame for MCPL phase-space output (default: iec). "
                             "iec: canonical IEC 61217 gantry/nozzle frame -- source plane at +D, "
                             "beam travels toward -Z, isocenter at origin, pre-gantry (the receiving "
                             "MC applies the gantry rotation). rotx180: the same beam rigidly rotated "
                             "180 deg about X, i.e. beam travels toward +Z with the source at -D; this "
                             "flips the sign of Y (a proper rotation cannot reverse Z alone). Use "
                             "rotx180 for downstream codes that expect a +Z-forward beam. Only applies "
                             "to MCPL export.")

    parser.add_argument('--nozzle-side', dest='nozzle_side', choices=['pos-z', 'neg-z'],
                        default='neg-z',
                        help="Which side of the gantry-local Z axis the nozzle sits on (default: neg-z). "
                             "neg-z reproduces IEC 61217: at gantry 0 the beam enters an HFS patient "
                             "from the anterior side (verified against OpenTOPAS 4.2.3, issue #66). "
                             "pos-z mirrors the source to gantry+180 deg and is only meant for "
                             "non-patient research setups.")

    parser.add_argument('-v', '--verbosity', action='count', help="Increase verbosity", default=0)
    parser.add_argument('-V', '--version', action='version', version=__version__)

    return parser
