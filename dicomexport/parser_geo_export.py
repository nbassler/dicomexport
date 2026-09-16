import argparse
from pathlib import Path

from dicomexport.__version__ import __version__


def create_parser():
    parser = argparse.ArgumentParser(
        description="Convert DICOM CT and RTSTRUCT files to geometry needed for TOPAS.")

    parser.add_argument('ct_dir', type=Path,
                        help="(required) Path to DICOM CT directory containing the CT slices.")

    parser.add_argument('rs_file', nargs='?', type=Path, default=None,
                        help="Path to DICOM RTSTRUCT file. If omitted, will search CT_DIR for the first RS*.dcm file.")

    parser.add_argument('fout', nargs='?', type=Path, default="geometry.txt",
                        help="Output TOPAS geometry file (default: geometry.txt).")

    parser.add_argument('--threads', type=int, dest='nr_threads', default=0,
                        help="TOPAS Ts/NumberOfThreads (default: 0). 0 uses all cores on the "
                             "machine that RUNS the file, -1 all but one, N exactly N. "
                             "Resolved at run time, not at export time, so it is safe to "
                             "export on one node and run on another.")

    parser.add_argument('-v', '--verbosity', action='count', default=0,
                        help="Increase verbosity (can use -v, -vv, etc.).")

    parser.add_argument('-V', '--version', action='version', version=__version__,
                        help="Show version and exit.")

    return parser
