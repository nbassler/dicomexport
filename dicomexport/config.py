"""Where dicomexport finds its data files: beam models, CT-number-to-material tables, range shifters.

DEFAULTS_DIR is the set shipped inside the package (issue #112), so dicomexport runs straight
after installation. It is read-only reference material: an upgrade replaces it. A site keeps
its own data in a copy of it elsewhere, never by editing these files.

Layout, the same in the shipped set and in a site's copy:

    beam_models/*.csv       one is chosen per export
    ct_to_material/*.txt    one is chosen per export
    range_shifters.csv      looked up by the plan's RangeShifterID

A real directory rather than importlib.resources, because these files are handed on as
paths: a table chosen from here ends up in a TOPAS includeFile line, so it has to outlive
the export.

That rules out bundling the files into a PyInstaller --onefile executable. Such an
executable unpacks its data into a temporary directory that is deleted when it exits, and
an exported includeFile would then point at a file that no longer exists. Frozen builds
therefore ship defaults/ beside the executable, as res/ was shipped before.
"""
import sys
from pathlib import Path

if getattr(sys, "frozen", False):
    DEFAULTS_DIR = Path(sys.executable).resolve().parent / "defaults"
else:
    DEFAULTS_DIR = Path(__file__).resolve().parent / "defaults"

BEAM_MODELS = "beam_models"
CT_TO_MATERIAL = "ct_to_material"
RANGE_SHIFTERS = "range_shifters.csv"
