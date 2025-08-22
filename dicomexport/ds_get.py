# dicomexport/ds_get.py
from __future__ import annotations
from pathlib import Path
from typing import Callable, Iterable, TypeVar, Any

from pydicom.dataset import Dataset

T = TypeVar("T")


class DicomAttributeMissingError(ValueError):
    pass


class DicomAttributeInvalidError(ValueError):
    pass


def req(ds: Dataset, keyword: str, *, cast: Callable[[Any], T] | None = None,
        n: int | None = None, file: Path | None = None) -> T | Any:
    """
    Get a REQUIRED DICOM attribute by *keyword*. Raise clear error if missing
    or malformed. Optionally check sequence length (n).
    """
    val = getattr(ds, keyword, None)
    if val is None:
        where = f" in {file.name}" if file else ""
        raise DicomAttributeMissingError(f"Missing required DICOM attribute '{keyword}'{where}.")
    if n is not None and hasattr(val, "__len__") and len(val) != n:
        where = f" in {file.name}" if file else ""
        raise DicomAttributeInvalidError(
            f"Attribute '{keyword}' has length {len(val)}, expected {n}{where}."
        )
    return cast(val) if cast else val


def opt(ds: Dataset, keyword: str, default: T, *,
        cast: Callable[[Any], T] | None = None, n: int | None = None) -> T:
    """
    Get an OPTIONAL DICOM attribute; return default if missing OR cast/length fails.
    """
    val = getattr(ds, keyword, None)
    if val is None:
        return default
    if n is not None and hasattr(val, "__len__") and len(val) != n:
        return default
    if cast is None:
        return val  # type: ignore[return-value]
    try:
        return cast(val)
    except Exception:
        return default

# Small casting helpers (handy across modules)


def tuple_of_float(seq: Iterable[Any]) -> tuple[float, ...]:
    return tuple(float(x) for x in seq)


def as_int(x: Any) -> int:
    return int(x)


def as_str(x: Any) -> str:
    return str(x)


__all__ = [
    "req", "opt",
    "tuple_of_float", "as_int", "as_str",
    "DicomAttributeMissingError", "DicomAttributeInvalidError",
]
