from pathlib import Path


def list_files(folder: Path, suffixes: list) -> dict:
    """Return {filename: full_path} for all matching files in folder."""
    return {f.name: f for f in sorted(folder.iterdir()) if f.suffix in suffixes}
