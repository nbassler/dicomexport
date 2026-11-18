"""Where dicomexport finds its data files: beam models, CT-number-to-material tables, range shifters.

Two kinds of directory share one layout (issue #112):

    beam_models/*.csv       one is chosen per export (-b)
    ct_to_material/*.txt    CT-number-to-material tables, included with -s or -S
    range_shifters.csv      looked up by the plan's RangeShifterID
    materials.txt           TOPAS material definitions, pasted with -S (issue #94)

DEFAULTS_DIR is the set shipped with the package, so dicomexport runs straight after
installation. It is read-only reference material: an upgrade replaces it.

A site keeps its own data in a configuration directory outside the package, started as a
copy of the defaults (--init-config) and edited there. An upgrade never touches it.

Exactly one directory is in effect, never merged. find_config_dir() takes the first of:

    1. --config-dir DIR
    2. $DICOMEXPORT_CONFIG_DIR
    3. the user configuration directory: ~/.config/dicomexport ($XDG_CONFIG_HOME is honoured),
       %APPDATA%\\dicomexport on Windows
    4. /etc/dicomexport (not on Windows)
    5. DEFAULTS_DIR

1 and 2 must exist when given: a typo must never fall back to other data silently. 3 and 4
are used only if they exist.

DEFAULTS_DIR is a real directory rather than importlib.resources, because these files are
handed on as paths: a table chosen from here ends up in a TOPAS includeFile line, so it has
to outlive the export. That rules out bundling the files into a PyInstaller --onefile
executable, which unpacks its data into a temporary directory deleted on exit. Frozen
builds therefore ship defaults/ beside the executable.
"""
import hashlib
import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


def shipped_defaults_dir() -> Path:
    """Where the shipped defaults are: in the package, or beside a frozen executable."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / "defaults"
    return Path(__file__).resolve().parent / "defaults"


DEFAULTS_DIR = shipped_defaults_dir()

BEAM_MODELS = "beam_models"
CT_TO_MATERIAL = "ct_to_material"
RANGE_SHIFTERS = "range_shifters.csv"
MATERIALS = "materials.txt"

ENV_VAR = "DICOMEXPORT_CONFIG_DIR"

#: The beam model used when -b is omitted, but only with the shipped defaults. In a site's
#: own directory -b may be omitted only when the directory holds exactly one beam model, so
#: dicomexport never picks a calibration on a site's behalf.
DEFAULT_BEAM_MODEL = "DCPT_beam_model__v5.csv"

_BEAM_MODEL_SUFFIXES = (".csv",)
_CT_TO_MATERIAL_SUFFIXES = (".txt",)


class ConfigError(Exception):
    """A configuration directory, or a file asked of it, cannot be used. The message says why."""


@dataclass(frozen=True)
class Include:
    """A TOPAS parameter file for the export: included by path (-s) or pasted (-S).

    ``path`` is what is written: into the includeFile line, or into the lines that mark the
    pasted block. ``text`` and ``sha256`` are set only for a pasted file.
    """

    path: str
    inline: bool = False
    text: Optional[str] = None
    sha256: Optional[str] = None


def user_config_dir() -> Path:
    """The per-user configuration directory, whether or not it exists."""
    if os.name == "nt":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "dicomexport"


def system_config_dir() -> Optional[Path]:
    """The machine-wide configuration directory, whether or not it exists. None on Windows."""
    return None if os.name == "nt" else Path("/etc/dicomexport")


@dataclass(frozen=True)
class ConfigDir:
    """The configuration directory in effect, and how it was found."""

    path: Path
    found_by: str

    def __post_init__(self):
        # Absolute, so files picked from it are written as absolute paths, wherever TOPAS runs.
        object.__setattr__(self, "path", Path(self.path).absolute())

    @property
    def is_shipped(self) -> bool:
        return self.path.resolve() == DEFAULTS_DIR

    def __str__(self) -> str:
        return f"{self.path} ({self.found_by})"

    # ----- what the directory offers -------------------------------------------------

    def beam_models(self) -> list[Path]:
        return _files(self.path / BEAM_MODELS, _BEAM_MODEL_SUFFIXES)

    def ct_to_material_tables(self) -> list[Path]:
        return _files(self.path / CT_TO_MATERIAL, _CT_TO_MATERIAL_SUFFIXES)

    @property
    def range_shifters(self) -> Path:
        return self.path / RANGE_SHIFTERS

    @property
    def materials(self) -> Path:
        return self.path / MATERIALS

    def default_beam_model(self) -> Optional[Path]:
        """The beam model used when -b is omitted, or None when the choice is not unambiguous."""
        models = self.beam_models()
        if self.is_shipped:
            return next((p for p in models if p.name == DEFAULT_BEAM_MODEL), None)
        return models[0] if len(models) == 1 else None

    def default_ct_to_material_table(self) -> Optional[Path]:
        """The table included when neither -s nor -S is given: the only one, or None."""
        tables = self.ct_to_material_tables()
        return tables[0] if len(tables) == 1 else None

    # ----- choosing a file -----------------------------------------------------------

    def beam_model(self, arg: Optional[os.PathLike | str]) -> Path:
        """Choose a beam model from a local file path, a name in beam_models/, or the default."""
        if arg is not None and Path(arg).is_file():
            return Path(arg)
        return self._select(arg, self.beam_models(), self.default_beam_model(),
                            what="beam model", flag="-b", subdir=BEAM_MODELS)

    def default_include(self) -> Include:
        """What is included when neither -s nor -S is given: the directory's only table."""
        table = self._select(None, self.ct_to_material_tables(), self.default_ct_to_material_table(),
                             what="CT-number-to-material table", flag="-s or -S", subdir=CT_TO_MATERIAL)
        return Include(str(table))

    def includable(self) -> list[Path]:
        """The files -s and -S find by name: the tables in ct_to_material/, then the .txt files
        at the top of the directory, such as materials.txt."""
        return self.ct_to_material_tables() + _files(self.path, _CT_TO_MATERIAL_SUFFIXES)

    def include(self, arg: os.PathLike | str, inline: bool = False) -> Include:
        """A file for -s (inline False) or -S (inline True).

        A bare name that is not a file here is looked up with includable() and written as an
        absolute path. Anything else is written exactly as given (issue #63): for -s it may
        name a file that exists only where TOPAS runs. -S reads the file, so it must exist.
        """
        raw = os.fspath(arg)
        given = Path(raw)
        path = raw
        if raw == given.name and not given.is_file():
            path = str(self._select(raw, self.includable(), None,
                                    what="file to include", flag="-s", subdir=""))
        if not inline:
            return Include(path)
        try:
            data = Path(path).read_bytes()
            text = data.decode("utf-8")
        except OSError as e:
            raise ConfigError(f"-S {raw}: cannot read {path}: {e.strerror}.") from None
        except UnicodeDecodeError:
            raise ConfigError(f"-S {raw}: {path} is not a UTF-8 text file.") from None
        return Include(path, inline=True, text=text, sha256=hashlib.sha256(data).hexdigest())

    def _select(self, arg: Optional[os.PathLike | str], candidates: list[Path], default: Optional[Path],
                what: str, flag: str, subdir: str) -> Path:
        names = ", ".join(p.name for p in candidates) or "(none)"
        if arg is None:
            if default is not None:
                return default
            if not candidates:
                raise ConfigError(f"No {what} given, and {self.path / subdir} has none. "
                                  f"Pass one with {flag} FILE.")
            raise ConfigError(f"No {what} given, and {self.path / subdir} has {len(candidates)}: "
                              f"{names}. Choose one with {flag} NAME.")

        name = os.fspath(arg)
        for p in candidates:
            if name in (p.name, p.stem):
                return p
        where = self.path / subdir if subdir else self.path
        raise ConfigError(f"{what.capitalize()} {name!r} is neither a file nor a name in "
                          f"{where}, which has: {names}.")

    # ----- for front ends --------------------------------------------------------------

    def listing(self, range_shifter_ids: list[str]) -> dict:
        """What this directory offers, for --list-config. JSON-serialisable."""
        def entries(files: list[Path], default: Optional[Path]) -> list[dict]:
            return [{"name": p.name, "path": str(p), "default": p == default} for p in files]

        return {
            "config_dir": str(self.path),
            "found_by": self.found_by,
            "is_shipped_defaults": self.is_shipped,
            "beam_models": entries(self.beam_models(), self.default_beam_model()),
            "ct_to_material": entries(self.ct_to_material_tables(), self.default_ct_to_material_table()),
            "range_shifters": {"path": str(self.range_shifters), "exists": self.range_shifters.is_file(),
                               "ids": range_shifter_ids},
            "materials": {"path": str(self.materials), "exists": self.materials.is_file()},
        }


def _files(folder: Path, suffixes: tuple[str, ...]) -> list[Path]:
    if not folder.is_dir():
        return []
    return sorted(p for p in folder.iterdir() if p.is_file() and p.suffix in suffixes)


def find_config_dir(explicit: Optional[os.PathLike | str] = None) -> ConfigDir:
    """The configuration directory in effect. See the module docstring for the order."""
    if explicit:
        return _must_exist(Path(explicit), "--config-dir")
    from_env = (os.environ.get(ENV_VAR) or "").strip()
    if from_env:
        return _must_exist(Path(from_env), f"${ENV_VAR}")
    user = user_config_dir()
    if user.is_dir():
        return ConfigDir(user, "user configuration directory")
    system = system_config_dir()
    if system is not None and system.is_dir():
        return ConfigDir(system, "system configuration directory")
    return ConfigDir(DEFAULTS_DIR, "shipped defaults")


def _must_exist(path: Path, found_by: str) -> ConfigDir:
    if not path.is_dir():
        raise ConfigError(f"Configuration directory {path} (from {found_by}) does not exist. "
                          f"Create one with --init-config {path}.")
    return ConfigDir(path, found_by)


def init_config_dir(target: os.PathLike | str) -> tuple[list[Path], list[Path]]:
    """Copy the shipped defaults into target, never overwriting a file that is already there.

    Returns (copied, skipped), as paths in target. Re-running it, e.g. after an upgrade, adds
    only files the site does not have yet, and leaves the site's own files alone.
    """
    target = Path(target)
    copied, skipped = [], []
    for src in sorted(p for p in DEFAULTS_DIR.rglob("*") if p.is_file()):
        dst = target / src.relative_to(DEFAULTS_DIR)
        if dst.exists():
            skipped.append(dst)
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        copied.append(dst)
    return copied, skipped
