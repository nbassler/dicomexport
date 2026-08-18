"""
Helpers for building throwaway DICOM files in tests.

dicomexport selects files by their Modality header (issue #77), so tests can no
longer stand up a study with empty ``Path.touch()`` files -- those are not
readable as DICOM. These helpers write a minimal but genuinely valid dataset
(~370 bytes) carrying just the tags the scanner reads.
"""

from pathlib import Path

from pydicom.dataset import Dataset, FileMetaDataset
from pydicom.uid import UID, ExplicitVRLittleEndian, generate_uid

# Any valid SOP Class works; the scanner keys on Modality, not on this.
_SOP_CLASS_UID = UID("1.2.840.10008.5.1.4.1.1.2")

# Media Storage Directory Storage, i.e. a DICOMDIR index file.
_DICOMDIR_SOP_CLASS = UID("1.2.840.10008.1.3.10")


#: Identity shared by every fixture unless a test deliberately diverges, so that
#: the single-study consistency check passes by default.
STUDY_UID = UID("1.2.826.0.1.3680043.8.498.10000000000000000000000000000001")
SERIES_UID = UID("1.2.826.0.1.3680043.8.498.10000000000000000000000000000002")
FRAME_UID = UID("1.2.826.0.1.3680043.8.498.10000000000000000000000000000003")
PATIENT_ID = "FIXTURE_PATIENT"

# Deliberately divergent identities, for tests that simulate a mixed directory.
OTHER_STUDY_UID = UID("1.2.826.0.1.3680043.8.498.20000000000000000000000000000001")
OTHER_SERIES_UID = UID("1.2.826.0.1.3680043.8.498.20000000000000000000000000000002")
OTHER_FRAME_UID = UID("1.2.826.0.1.3680043.8.498.20000000000000000000000000000003")


def write_dicom(path: Path, modality: str, instance_number: int | None = 1,
                study_uid: str = STUDY_UID, series_uid: str = SERIES_UID,
                frame_uid: str = FRAME_UID, patient_id: str = PATIENT_ID) -> Path:
    """
    Write a minimal valid DICOM file carrying ``modality``.

    Args:
        path: destination; parent directories must exist.
        modality: value for the Modality tag, e.g. "CT" or "RTPLAN".
        instance_number: value for InstanceNumber, or None to omit the tag.
        study_uid, series_uid, frame_uid, patient_id: identity tags. The defaults
            agree across all fixtures; override one to simulate a mixed directory.

    Returns:
        The path written, for convenience in assertions.
    """
    ds = Dataset()
    ds.Modality = modality
    if instance_number is not None:
        ds.InstanceNumber = instance_number
    ds.StudyInstanceUID = study_uid
    ds.SeriesInstanceUID = series_uid
    ds.FrameOfReferenceUID = frame_uid
    ds.PatientID = patient_id

    file_meta = FileMetaDataset()
    file_meta.MediaStorageSOPClassUID = _SOP_CLASS_UID
    file_meta.MediaStorageSOPInstanceUID = generate_uid()
    file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
    ds.file_meta = file_meta
    ds.preamble = b"\0" * 128

    ds.save_as(path, enforce_file_format=True)
    return Path(path)


def write_dicomdir(path: Path) -> Path:
    """
    Write a minimal DICOMDIR index file.

    A DICOMDIR carries the DICM magic but no Modality tag, so it is the one
    legitimate file that looks like a damaged image to the scanner.
    """
    ds = Dataset()
    file_meta = FileMetaDataset()
    file_meta.MediaStorageSOPClassUID = _DICOMDIR_SOP_CLASS
    file_meta.MediaStorageSOPInstanceUID = generate_uid()
    file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
    ds.file_meta = file_meta
    ds.preamble = b"\0" * 128

    ds.save_as(path, enforce_file_format=True)
    return Path(path)


def write_ct_series(directory: Path, n: int = 2, start: int = 1, **identity) -> list[Path]:
    """Write ``n`` CT slices into ``directory``, numbered from ``start``."""
    directory.mkdir(parents=True, exist_ok=True)
    return [
        write_dicom(directory / f"CT{i:03d}.dcm", "CT", instance_number=i, **identity)
        for i in range(start, start + n)
    ]
