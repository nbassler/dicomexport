"""
Group the DICOM files in a study directory by their Modality header.

dicomexport used to decide what a DICOM file was from its filename prefix
(``RN*.dcm``, ``RS*.dcm``, ``CT*.dcm``, ``RD*.dcm``). Those prefixes are vendor
conventions, not standard: Eclipse writes ``RN`` for the plan, RayStation writes
``RP``, and PACS exports often ship bare SOP Instance UIDs with no prefix and no
``.dcm`` suffix at all. Keying on the name made valid studies invisible (issue #77).

The scan here reads the ``Modality`` tag from each file's header instead. It is
cheap: a header-only read of a 182-file / 280 MB study takes ~40 ms, which is less
than the full-header pass that :func:`import_ct.get_ct_files_sorted_by_instance_number`
already performed on every CT slice just to sort by ``InstanceNumber``. That value is
picked up in the same pass here, so the sort no longer needs a second read.
"""

import logging
from dataclasses import dataclass, field
from pathlib import Path

import pydicom
from pydicom.errors import InvalidDicomError
from pydicom.misc import is_dicom

logger = logging.getLogger(__name__)

CT = "CT"
RTPLAN = "RTPLAN"
RTSTRUCT = "RTSTRUCT"
RTDOSE = "RTDOSE"

#: Modalities dicomexport consumes. Files of any other modality are ignored.
WANTED = (CT, RTPLAN, RTSTRUCT, RTDOSE)

#: Tags read during the scan. Modality classifies the file; InstanceNumber orders
#: the CT series; the rest establish that every file belongs to one study of one
#: patient. Carrying all six costs ~1 ms more than Modality alone on a 182-file study.
_SCAN_TAGS = [
    "Modality", "InstanceNumber",
    "StudyInstanceUID", "SeriesInstanceUID", "PatientID", "FrameOfReferenceUID",
]

#: Media Storage Directory Storage -- the SOP Class of a DICOMDIR. Such a file
#: legitimately carries no Modality, so it must not be mistaken for a damaged one.
_DICOMDIR_SOP_CLASS = "1.2.840.10008.1.3.10"


@dataclass(frozen=True)
class FileInfo:
    """The header facts harvested for one file during the scan."""

    modality: str
    instance_number: int | None = None
    study_uid: str | None = None
    series_uid: str | None = None
    patient_id: str | None = None
    frame_of_reference_uid: str | None = None


@dataclass
class StudyScan:
    """The DICOM files under a directory, grouped by Modality."""

    root: Path
    files: dict[str, list[Path]] = field(default_factory=dict)

    #: Header facts per classified file, from the same pass.
    info: dict[Path, FileInfo] = field(default_factory=dict)

    #: Files carrying the DICM magic that nonetheless failed to parse -- i.e. damaged
    #: DICOM, not merely unrelated files. Kept rather than dropped: in a study
    #: directory such a file is most likely a damaged CT slice, and silently
    #: exporting a series one slice short would misplace the patient. Callers that
    #: own a CT series must treat this as fatal.
    unreadable: list[Path] = field(default_factory=list)

    def get(self, modality: str) -> list[Path]:
        """Return the files of the given modality, sorted by path. Never None."""
        return self.files.get(modality, [])

    def instance_number_of(self, path: Path) -> int | None:
        """InstanceNumber for a classified file, or None if the tag was absent."""
        info = self.info.get(path)
        return None if info is None else info.instance_number

    def classified(self) -> list[Path]:
        """Every file assigned to a wanted modality."""
        return [p for m in WANTED for p in self.get(m)]


def is_dicom_file(path: Path) -> bool:
    """
    True if the file declares itself DICOM Part 10, judged by content not by name.

    The ``.dcm`` suffix is a convention, not part of the standard: interchange media
    use extension-less ISO 9660 names (``IM000001``), PACS exports often write bare
    SOP Instance UIDs, and Siemens uses ``.ima``. Since the point of issue #77 is to
    stop trusting filenames, this defers to :func:`pydicom.misc.is_dicom`, which
    checks the DICM magic bytes after the 128-byte preamble -- a 132-byte read.

    Wrapped only to turn an unopenable file into False rather than an exception.
    """
    try:
        return is_dicom(path)
    except OSError as exc:
        logger.debug("Cannot open %s (%s)", path, exc)
        return False


def _str_or_none(ds, tag: str) -> str | None:
    """Tag value as a plain string, or None when absent or empty."""
    value = getattr(ds, tag, None)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _is_dicomdir(ds) -> bool:
    """True for a DICOMDIR index file, which has no Modality by design."""
    file_meta = getattr(ds, "file_meta", None)
    if file_meta is None:
        return False
    return getattr(file_meta, "MediaStorageSOPClassUID", None) == _DICOMDIR_SOP_CLASS


def _read_header(path: Path):
    """Return the header dataset, or None if the file is not readable as DICOM."""
    try:
        return pydicom.dcmread(path, specific_tags=_SCAN_TAGS, stop_before_pixels=True)
    except (InvalidDicomError, OSError, AttributeError, ValueError) as exc:
        logger.debug("Not readable as DICOM: %s (%s)", path, exc)
        return None


def scan_study(root: Path) -> StudyScan:
    """
    Walk ``root`` recursively and group the DICOM files by their Modality tag.

    Files that are not DICOM Part 10 at all are skipped outright, judged by the
    DICM magic bytes rather than by suffix. Of the rest -- files that declare
    themselves DICOM -- those that fail to parse are collected in
    :attr:`StudyScan.unreadable`, and those whose Modality is not in
    :data:`WANTED` are ignored.
    """
    scan = StudyScan(root=root, files={m: [] for m in WANTED})

    for path in sorted(p for p in root.glob("**/*") if p.is_file()):
        if not is_dicom_file(path):
            logger.debug("Not a DICOM Part 10 file: %s", path)
            continue

        ds = _read_header(path)
        if ds is None:
            scan.unreadable.append(path)
            continue

        if _is_dicomdir(ds):
            logger.debug("Ignoring DICOMDIR: %s", path)
            continue

        modality = getattr(ds, "Modality", None)
        if modality is None:
            # Carries the DICM magic and is not a DICOMDIR, yet we cannot tell what
            # it is. pydicom returns a partial dataset rather than raising when a
            # file is truncated before the Modality tag, so this -- not a parse
            # failure -- is what a damaged slice usually looks like.
            logger.debug("No Modality tag, treating as damaged: %s", path)
            scan.unreadable.append(path)
            continue

        if modality not in WANTED:
            logger.debug("Ignoring %s (Modality=%s)", path, modality)
            continue

        scan.files[modality].append(path)
        raw = getattr(ds, "InstanceNumber", None)
        scan.info[path] = FileInfo(
            modality=modality,
            instance_number=None if raw is None else int(raw),
            study_uid=_str_or_none(ds, "StudyInstanceUID"),
            series_uid=_str_or_none(ds, "SeriesInstanceUID"),
            patient_id=_str_or_none(ds, "PatientID"),
            frame_of_reference_uid=_str_or_none(ds, "FrameOfReferenceUID"),
        )

    logger.debug(
        "Scanned %s: %s, %d unreadable",
        root,
        ", ".join(f"{len(scan.get(m))} {m}" for m in WANTED),
        len(scan.unreadable),
    )
    return scan


def exactly_one(files: list[Path], what: str, root: Path, hint: str) -> Path:
    """
    Return the single file in ``files``, or raise naming the candidates.

    Args:
        files: candidates, already filtered to one modality.
        what: human name for the error text, e.g. "plan files".
        root: the directory searched, for the not-found message.
        hint: what the user should do when several were found.
    """
    if not files:
        raise FileNotFoundError(
            f"No {what} found in {root} or its subdirectories")
    if len(files) > 1:
        files_str = ", ".join(str(f) for f in files)
        raise ValueError(
            f"Multiple {what} found: {files_str}. {hint}")
    return files[0]


def _group_by_value(scan: StudyScan, paths: list[Path], attr: str) -> dict[str, list[Path]]:
    """Bucket paths by one FileInfo field, skipping files where it is absent."""
    groups: dict[str, list[Path]] = {}
    for path in paths:
        value = getattr(scan.info[path], attr)
        if value is not None:
            groups.setdefault(value, []).append(path)
    return groups


def _describe(groups: dict[str, list[Path]], scan: StudyScan) -> str:
    """Render the mismatching groups compactly for an error message."""
    parts = []
    for value, paths in sorted(groups.items()):
        modalities = sorted({scan.info[p].modality for p in paths})
        example = paths[0].name
        parts.append(
            f"{value} ({len(paths)} file(s), {'/'.join(modalities)}, e.g. {example})")
    return "; ".join(parts)


def check_single_study(scan: StudyScan) -> None:
    """
    Abort unless everything found belongs to one study of one patient.

    A directory holding two exports produces a silently wrong export rather than an
    error: two CT series in the *same* directory are merged into one geometry, since
    the only pre-existing guard caught the case where they sat in different
    subdirectories. Two RTPLANs or two RTSTRUCTs already fail via exactly_one(), so
    the CT series is the gap this closes.

    Files missing one of these tags are skipped for that check rather than treated as
    a mismatch, so a vendor that omits e.g. FrameOfReferenceUID on RTDOSE still works.
    """
    classified = scan.classified()
    if not classified:
        return

    checks = (
        ("patient_id", classified, "PatientID",
         "The directory holds data for more than one patient."),
        ("study_uid", classified, "StudyInstanceUID",
         "The directory holds more than one study."),
        ("series_uid", scan.get(CT), "SeriesInstanceUID",
         "The directory holds more than one CT series."),
        ("frame_of_reference_uid", classified, "FrameOfReferenceUID",
         "The files do not share a frame of reference, so the geometry would not line up."),
    )

    for attr, paths, tag, problem in checks:
        groups = _group_by_value(scan, paths, attr)
        if len(groups) > 1:
            raise ValueError(
                f"{problem} Found {len(groups)} distinct {tag} values under "
                f"{scan.root}: {_describe(groups, scan)}. Please export one study "
                "per directory.")


def raise_if_unreadable(scan: StudyScan) -> None:
    """
    Abort when the scan hit files it could not parse.

    Called by the CT loader only. A damaged file in a study directory is
    overwhelmingly likely to be a CT slice, and a series quietly missing one slice
    produces a wrong patient geometry rather than an error. Other loaders tolerate
    unreadable files, since a stray damaged file should not block an otherwise
    valid plan or dose lookup.
    """
    if not scan.unreadable:
        return
    files_str = ", ".join(str(f) for f in scan.unreadable)
    raise ValueError(
        f"{len(scan.unreadable)} file(s) under {scan.root} claim to be DICOM but "
        f"could not be read as DICOM: {files_str}. A damaged file in a study "
        "directory is most likely a CT slice; exporting would silently produce an "
        "incomplete series. Remove or repair the file(s) and retry.")
