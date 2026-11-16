import argparse
from pathlib import Path

from dicomexport.__version__ import __version__
from dicomexport.parser_topas_options import (add_batches, add_dose_cube_16bit, add_nozzle_side, add_nstat,
                                              add_spot_mode, add_threads, add_topas_version)


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
                        help="Range shifter catalog CSV. REPLACES the default catalog "
                             "(range_shifters.csv in dicomexport's defaults directory), so it "
                             "must list every range shifter the plan uses. "
                             "The README.md next to the default catalog describes the format.")
    parser.add_argument('-f', '--field', type=int, dest='field_nr', default=0,
                        help="DICOM BeamNumber of the field to export. If not specified, all fields will be exported.")

    add_nstat(parser)

    add_threads(parser)

    add_topas_version(parser)

    add_dose_cube_16bit(parser)

    add_spot_mode(parser)
    add_batches(parser)

    parser.add_argument(
        '--export-fmt', dest='export_fmt', choices=['topas', 'mcpl', 'racehorse'], default='topas',
        help=("Export format (default: topas). "
              "Formats: topas (*.txt), mcpl (*.mcpl), racehorse (*.csv).")
    )

    add_nozzle_side(parser)

    parser.add_argument('-v', '--verbosity', action='count', default=0,
                        help="Increase verbosity (can use -v, -vv, etc.).")

    parser.add_argument('-V', '--version', action='version', version=__version__,
                        help="Show version and exit.")

    return parser
