from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent
BEAM_MODELS_DIR = PROJECT_ROOT / "res" / "beam_models"
SPR_TABLES_DIR = PROJECT_ROOT / "res" / "spr_tables"


def list_files(folder: Path, suffixes: list) -> dict:
    """Return {filename: full_path} for all matching files in folder."""
    if not folder.is_dir():
        return {}
    return {f.name: f for f in sorted(folder.iterdir()) if f.suffix in suffixes}
