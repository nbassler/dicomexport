"""Structure material overrides: --material-override "ROI=MATERIAL" (issue #94).

TOPAS converts CT numbers to materials voxel by voxel, then replaces the material inside the
named RTSTRUCT structures (MaterialByRTStructNames / MaterialByRTStructMaterials). dicomexport
checks the structure names against the RTSTRUCT it read and writes those parameters. It does
not check the material names: TOPAS reports an unknown material, and the definitions of a
site's own materials come from a pasted file (-S materials.txt), which dicomexport does not
read.
"""
import logging
from dataclasses import dataclass

from dicomexport.model_rtstruct import RTStruct

logger = logging.getLogger(__name__)

# TOPAS trims these from both ends of an RTSTRUCT structure name (TsDicomPatient.cc:699).
_TOPAS_WHITESPACE = " \n\t\v\r\f"


def topas_structure_name(name: str) -> str:
    """A structure name as TOPAS matches it: trimmed, then spaces replaced by underscores.

    TOPAS rewrites the names it reads from the RTSTRUCT this way, but compares them with the
    names in MaterialByRTStructNames verbatim, so those must be written rewritten.
    """
    return name.strip(_TOPAS_WHITESPACE).replace(" ", "_")


@dataclass(frozen=True)
class MaterialOverride:
    roi_name: str
    """The ROI name as in the RTSTRUCT."""
    material: str

    @property
    def topas_name(self) -> str:
        return topas_structure_name(self.roi_name)


def parse_override(text: str) -> tuple[str, str]:
    """Split "ROI=MATERIAL" at the last '=': ROI names may contain one, material names do not."""
    roi, sep, material = text.rpartition("=")
    if not sep or not roi.strip() or not material.strip():
        raise ValueError(f"--material-override {text!r}: expected ROI=MATERIAL.")
    return roi, material.strip()


def resolve_overrides(given: list[str], rs: RTStruct) -> list[MaterialOverride]:
    """Check each "ROI=MATERIAL" against the RTSTRUCT. Raises ValueError naming the problem.

    A ROI matches when it is the same name as TOPAS sees it, so "Solid Water" and
    "Solid_Water" both name a structure called "Solid Water". The order is kept: TOPAS gives
    the first listed structure precedence where structures overlap.
    """
    by_topas_name: dict[str, list[str]] = {}
    for roi in rs.rois:
        by_topas_name.setdefault(topas_structure_name(roi.roi_name), []).append(roi.roi_name)
    available = ", ".join(repr(r.roi_name) for r in rs.rois) or "(none)"

    overrides: list[MaterialOverride] = []
    seen: dict[str, str] = {}
    for text in given:
        roi, material = parse_override(text)
        key = topas_structure_name(roi)
        names = by_topas_name.get(key)
        if not names:
            raise ValueError(f"--material-override {text!r}: no structure {roi!r} in "
                             f"{_rtstruct(rs)}, which has: {available}.")
        if len(names) > 1:
            raise ValueError(f"--material-override {text!r}: TOPAS cannot tell apart the "
                             f"structures {', '.join(map(repr, names))} in {_rtstruct(rs)}, "
                             f"which it all names {key!r}.")
        if key in seen:
            raise ValueError(f"--material-override {text!r}: structure {names[0]!r} already "
                             f"has an override ({seen[key]!r}).")
        seen[key] = text
        overrides.append(MaterialOverride(names[0], material))
    return overrides


def warn_declared_overrides(rs: RTStruct, overrides: list[MaterialOverride]) -> None:
    """Warn about each ROI whose RTSTRUCT declares a material or density that is not applied.

    A warning, not an error: planning systems write such overrides routinely, e.g. on couch
    structures, and TOPAS ignores them (issue #94).
    """
    covered = {o.roi_name for o in overrides}
    for roi in rs.rois:
        if roi.declared_overrides and roi.roi_name not in covered:
            logger.warning(
                "The RTSTRUCT declares %s for structure %r, which TOPAS ignores: it converts "
                "the CT numbers there as everywhere else. To set a material, pass "
                "--material-override %r.",
                ", ".join(roi.declared_overrides), roi.roi_name, f"{roi.roi_name}=MATERIAL")


def _rtstruct(rs: RTStruct) -> str:
    return str(rs.file_path) if rs.file_path else "the RTSTRUCT"
