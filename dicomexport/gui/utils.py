from pathlib import Path

from dicomexport.config import ConfigDir, find_config_dir


def gui_config() -> ConfigDir:
    """The configuration directory in effect, found the same way as on the command line.

    No --config-dir here, so $DICOMEXPORT_CONFIG_DIR, the user and the system directories,
    then the shipped defaults (issue #112). Raises config.ConfigError if
    $DICOMEXPORT_CONFIG_DIR names a directory that does not exist.
    """
    return find_config_dir()


def by_name(files: list[Path]) -> dict:
    """Return {filename: full_path}, in the order given."""
    return {f.name: f for f in files}
