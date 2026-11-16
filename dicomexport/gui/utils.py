from pathlib import Path

from dicomexport.config import BEAM_MODELS, CT_TO_MATERIAL, DEFAULTS_DIR

# The shipped data (issue #112). config.DEFAULTS_DIR also resolves inside a PyInstaller
# bundle, provided the build adds dicomexport/defaults as data.
BEAM_MODELS_DIR = DEFAULTS_DIR / BEAM_MODELS
CT_TO_MATERIAL_DIR = DEFAULTS_DIR / CT_TO_MATERIAL


def list_files(folder: Path, suffixes: list) -> dict:
    """Return {filename: full_path} for all matching files in folder."""
    if not folder.is_dir():
        return {}
    return {f.name: f for f in sorted(folder.iterdir()) if f.suffix in suffixes}
