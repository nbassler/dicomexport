"""Where dicomexport finds its data files: beam models, CT-number-to-material tables, range shifters.

DEFAULTS_DIR is the set shipped inside the package (issue #112), so dicomexport runs straight
after installation. It is read-only reference material: an upgrade replaces it. A site keeps
its own data in a copy of it elsewhere, never by editing these files.

Layout, the same in the shipped set and in a site's copy:

    beam_models/*.csv       one is chosen per export
    ct_to_material/*.txt    one is chosen per export
    range_shifters.csv      looked up by the plan's RangeShifterID

Path(__file__) rather than importlib.resources, because these files are handed on as real
paths (TOPAS includeFile), and it also resolves inside a PyInstaller bundle, as long as the
build adds dicomexport/defaults as data.
"""
from pathlib import Path

DEFAULTS_DIR = Path(__file__).resolve().parent / "defaults"

BEAM_MODELS = "beam_models"
CT_TO_MATERIAL = "ct_to_material"
RANGE_SHIFTERS = "range_shifters.csv"
