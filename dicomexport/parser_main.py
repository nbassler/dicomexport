import argparse
from pathlib import Path

from dicomexport.__version__ import __version__


def create_parser():
    parser = argparse.ArgumentParser(
        description="Convert DICOM CT and RTSTRUCT files to geometry needed for TOPAS.")

    parser.add_argument('study_dir', type=Path,
                        help="(required) Path to folder containing the study."
                        "The folder should contain"
                        " a) DICOM CT series(CT*.dcm) and"
                        " b) one DICOM RTSTRUCT file (RS*.dcm) and"
                        " c) one DICOM RTPLAN file (RN*.dcm) and"
                        " d) at least one DICOM RTDOSE file (RD*.dcm) where the resulting dose distribution will be stored.")

    parser.add_argument('output_base_path', nargs='?', type=Path, default="topas.txt",
                        help="Export file (default: topas.txt). \
                            Field number will be appended automatically to the name before the extension.")

    parser.add_argument('-b', '--beam-model', type=Path, dest='bm',
                        help="(required) Beam model CSV path", default=None)

    parser.add_argument('-s', '--spr-to-material', type=Path, dest='spr_to_material_path',
                        help="(required) SPR to material mapping CSV path", default=None)

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

    parser.add_argument('-N', '--nstat', type=int, dest='nstat',
                        help="Target protons for simulation", default=int(1e6))

    parser.add_argument(
        '--export-fmt', dest='export_fmt', choices=['topas', 'mcpl', 'racehorse'], default='topas',
        help=("Export format (default: topas). "
              "Formats: topas (*.txt), mcpl (*.mcpl), racehorse (*.csv).")
    )

    parser.add_argument('--nozzle-side', dest='nozzle_side', choices=['pos-z', 'neg-z'],
                        default='neg-z',
                        help="Which side of the gantry-local Z axis the nozzle sits on (default: neg-z). "
                             "neg-z reproduces IEC 61217: at gantry 0 the beam enters an HFS patient "
                             "from the anterior side (verified against OpenTOPAS 4.2.3, issue #66). "
                             "pos-z mirrors the source to gantry+180 deg and is only meant for "
                             "non-patient research setups.")

    parser.add_argument('-v', '--verbosity', action='count', default=0,
                        help="Increase verbosity (can use -v, -vv, etc.).")

    parser.add_argument('-V', '--version', action='version', version=__version__,
                        help="Show version and exit.")

    return parser
