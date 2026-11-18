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
from pathlib import Path
from typing import Collection, Optional

import numpy as np
import pydicom

from dicomexport.model_rtstruct import RTStruct

logger = logging.getLogger(__name__)

# TOPAS trims these from both ends of an RTSTRUCT structure name (TsDicomPatient.cc:699).
_TOPAS_WHITESPACE = " \n\t\v\r\f"

# Characters a name cannot contain in a TOPAS file (TsParameterManager.cc:1884-1922): TOPAS
# rejects = ' ` ? in a value, ends the line at #, ends the string at ", and rewrites
# typographic quotes and dashes in the file but not in the RTSTRUCT.
_TOPAS_UNSAFE = set("='`?#\"") | set("\u2018\u2019\u201c\u201d") | {chr(c) for c in range(0x2010, 0x2016)}


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
    """Split "ROI=MATERIAL" at the last '=', so a ROI name with '=' gets the message below."""
    roi, sep, material = text.rpartition("=")
    material = material.strip()
    if not sep or not roi.strip() or not material:
        raise ValueError(f"--material-override {text!r}: expected ROI=MATERIAL.")
    bad = _unsafe(material) or next((c for c in material if c.isspace()), None)
    if bad:
        raise ValueError(f"--material-override {text!r}: a material name cannot contain {bad!r} "
                         f"in a TOPAS file.")
    return roi, material


def _unsafe(name: str):
    """The first character of name that a TOPAS file cannot carry, or None."""
    return next((c for c in name if c in _TOPAS_UNSAFE or ord(c) < 32), None)


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
        bad = _unsafe(key)
        if bad:
            raise ValueError(f"--material-override {text!r}: TOPAS cannot match structure "
                             f"{names[0]!r}, because a TOPAS file cannot carry {bad!r}. Rename "
                             f"the structure.")
        if key in seen:
            raise ValueError(f"--material-override {text!r}: structure {names[0]!r} already "
                             f"has an override ({seen[key]!r}).")
        seen[key] = text
        overrides.append(MaterialOverride(names[0], material))
    return overrides


def check_contours(overrides: list[MaterialOverride], rtstruct_file: Optional[Path],
                   slice_z: Collection[float]) -> None:
    """Check that TOPAS will build each overridden structure as the RTSTRUCT defines it.

    ``slice_z`` are the z positions of the CT slices (ImagePositionPatient). TOPAS
    (TsDicomPatient.cc:645-784, OpenTOPAS 4.3.0):

    - fills every contour of 3 or more points and never clears a voxel, whatever the
      ContourGeometricType: a hole, nested or XOR, gets the material, an open contour is closed;
    - skips contours of fewer than 3 points, and stops on a structure with none;
    - places a contour only on a CT slice at exactly its z, and skips it otherwise;
    - compares the name's raw bytes with the UTF-8 TOPAS file;
    - loses the first item of StructureSetROISequence when ROIContourSequence lists another
      ROI before it, and then stops (a reference assigned through at line 652).

    Each would put the material elsewhere than the RTSTRUCT says, or stop TOPAS on the compute
    node, so it is an error here. Raises ValueError naming the structure or the file.
    """
    if not overrides:
        return
    if rtstruct_file is None:
        raise ValueError("Material overrides need the RTSTRUCT file to check the structures against.")
    bad = _unsafe(rtstruct_file.as_posix())
    if bad:
        raise ValueError(f"--material-override: TOPAS cannot read the RTSTRUCT path {rtstruct_file}, because "
                         f"a TOPAS file cannot carry {bad!r}. Rename or move the file.")
    ds = pydicom.dcmread(rtstruct_file)
    numbers = {}
    for item in ds.StructureSetROISequence:
        # The raw bytes, before pydicom decodes them: TOPAS compares those.
        raw = item.get_item("ROIName").value or b""
        numbers[topas_structure_name(str(item.ROIName))] = (int(item.ROINumber), raw)
    _check_roi_order(ds, rtstruct_file)
    contours = {int(rc.ReferencedROINumber): rc.get("ContourSequence") or []
                for rc in ds.get("ROIContourSequence", [])}
    on_slice = set(slice_z)

    for o in overrides:
        number, raw = numbers[o.topas_name]
        what = f"--material-override for structure {o.roi_name!r} in {rtstruct_file}"
        if raw.strip(_TOPAS_WHITESPACE.encode()).replace(b" ", b"_") != o.topas_name.encode("utf-8"):
            raise ValueError(f"{what}: its name is not stored as UTF-8 (SpecificCharacterSet "
                             f"{ds.get('SpecificCharacterSet', 'not set')!s}), and TOPAS compares "
                             f"the stored bytes with the UTF-8 TOPAS file. Rename the structure, or "
                             f"save the RTSTRUCT as UTF-8 (ISO_IR 192).")
        _check_roi_contours(contours.get(number, []), on_slice, what)


def _check_roi_order(ds, rtstruct_file: Path) -> None:
    """Refuse an RTSTRUCT that OpenTOPAS 4.3.0 cannot read whole, whichever ROI is overridden."""
    ss_numbers = [int(item.ROINumber) for item in ds.StructureSetROISequence]
    referenced = [int(rc.ReferencedROINumber) for rc in ds.get("ROIContourSequence", [])]
    unknown = sorted(set(referenced) - set(ss_numbers))
    if unknown:
        raise ValueError(f"--material-override: {rtstruct_file} has contours for ROI numbers {unknown}, "
                         f"which StructureSetROISequence does not define; TOPAS would stop reading it.")
    if ss_numbers and ss_numbers[0] in referenced and referenced.index(ss_numbers[0]) > 0:
        raise ValueError(f"--material-override: OpenTOPAS 4.3.0 cannot read {rtstruct_file}: its "
                         f"ROIContourSequence lists ROI {ss_numbers[0]}, the first of "
                         f"StructureSetROISequence, after other ROIs, and TOPAS then loses it and "
                         f"stops (TsDicomPatient.cc:652). Export the RTSTRUCT again with both "
                         f"sequences in the same order.")


def _check_roi_contours(sequence, on_slice: set, what: str) -> None:
    slices: dict[float, list[np.ndarray]] = {}
    for c in sequence:
        points = np.asarray([float(v) for v in c.get("ContourData") or []]).reshape(-1, 3)
        if len(points) < 3:
            continue        # a point or a line: TOPAS ignores it, and it encloses no volume
        kind = str(c.get("ContourGeometricType", ""))
        if kind != "CLOSED_PLANAR":
            raise ValueError(f"{what}: it has a {kind or 'untyped'} contour, which TOPAS would fill "
                             f"as a closed polygon. Only CLOSED_PLANAR contours can be overridden.")
        z = float(points[0, 2])
        if z not in on_slice:
            raise ValueError(f"{what}: it has a contour at z = {z:g} mm, where the CT has no slice; "
                             f"TOPAS would skip it.")
        slices.setdefault(z, []).append(points[:, :2])
    if not slices:
        raise ValueError(f"{what}: it has no closed contour of 3 or more points, so TOPAS would "
                         f"override no voxel.")
    for z, polygons in slices.items():
        for i, a in enumerate(polygons):
            for j, b in enumerate(polygons):
                if i != j and _enters(a, b):
                    raise ValueError(f"{what}: at z = {z:g} mm one contour lies inside or overlaps "
                                     f"another, which marks a hole; TOPAS would fill it with the "
                                     f"material.")


_ON_EDGE_MM = 1e-3


def _enters(a: np.ndarray, b: np.ndarray) -> bool:
    """Does polygon a reach into polygon b? Vertices of a on b's edge (shared edges of two
    neighbouring contours) do not count, so the answer does not depend on where a starts."""
    points = a[_distance_to_edges(a, b) > _ON_EDGE_MM]
    return bool(np.any(_inside(points, b)))


def _distance_to_edges(points: np.ndarray, polygon: np.ndarray) -> np.ndarray:
    """Distance of each point to the nearest edge of the closed polygon."""
    start = polygon
    edge = np.roll(polygon, -1, axis=0) - start                       # (m, 2)
    rel = points[:, None, :] - start[None, :, :]                      # (n, m, 2)
    length2 = np.maximum((edge ** 2).sum(axis=1), 1e-300)
    t = np.clip((rel * edge).sum(axis=2) / length2, 0.0, 1.0)         # (n, m)
    return np.sqrt(((rel - t[..., None] * edge) ** 2).sum(axis=2)).min(axis=1)


def _inside(points: np.ndarray, polygon: np.ndarray) -> np.ndarray:
    """Even-odd rule: which points are inside the closed polygon?"""
    x, y = points[:, :1], points[:, 1:2]                              # (n, 1)
    x1, y1 = polygon[:, 0], polygon[:, 1]
    x2, y2 = np.roll(x1, -1), np.roll(y1, -1)
    crosses = (y1 > y) != (y2 > y)                                    # (n, m)
    with np.errstate(divide="ignore", invalid="ignore"):
        x_at = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
    return np.count_nonzero(crosses & (x < x_at), axis=1) % 2 == 1


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
