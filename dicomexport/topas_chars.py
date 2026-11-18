"""Characters a TOPAS parameter file cannot carry in a quoted string value.

OpenTOPAS 4.3.0, TsParameterManager.cc:1884-1922: it rejects = ' ` ? in a value, ends every
line at # (also inside quotes), ends a string at ", and rewrites typographic quotes and dashes
in the file, so a name compared with an RTSTRUCT no longer matches. Paths and names that
dicomexport writes as TOPAS values are checked against this at export (issues #94, #130).
"""
from typing import Optional

UNSAFE = set("='`?#\"") | set("‘’“”") | {chr(c) for c in range(0x2010, 0x2016)}


def unsafe_char(text: str) -> Optional[str]:
    """The first character of text that a TOPAS value cannot carry, or None."""
    return next((c for c in text if c in UNSAFE or ord(c) < 32), None)


def check_topas_value(text: str, what: str) -> None:
    """Raise ValueError if text, written into a TOPAS file as what, cannot be read by TOPAS."""
    bad = unsafe_char(text)
    if bad:
        raise ValueError(f"TOPAS cannot read the {what} {text}: a TOPAS file cannot carry {bad!r}. "
                         f"Rename or move it.")


def check_include_path(path: str) -> None:
    """Raise ValueError if TOPAS cannot open path from an includeFile line.

    includeFile is not a quoted value: TOPAS splits it with G4Tokenizer (TsParameterFile.cc:222)
    at its default delimiters, space, tab and newline, so a path with a space names two files.
    Other whitespace, such as a non-breaking space, does not split it.
    """
    check_topas_value(path, "-s path (includeFile)")
    if any(c in " \t\n" for c in path):
        raise ValueError(f"TOPAS cannot read the -s path (includeFile) {path}: TOPAS splits includeFile "
                         f"at whitespace. Rename or move the file, or paste it with -S.")
