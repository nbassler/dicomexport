"""
Helpers for building throwaway DICOM files in tests.

dicomexport selects files by their Modality header (issue #77), so tests can no
longer stand up a study with empty ``Path.touch()`` files -- those are not
readable as DICOM. These helpers write a minimal but genuinely valid dataset
(~370 bytes) carrying just the tags the scanner reads.
"""

from pathlib import Path

from pydicom.dataset import Dataset, FileMetaDataset
from pydicom.sequence import Sequence
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


def write_dicom_raw(path: Path, modality: str, instance_number, **identity) -> Path:
    """
    Write a fixture whose InstanceNumber is deliberately malformed.

    Used to prove the scanner survives vendor quirks; ``instance_number`` is written
    verbatim (e.g. a list, producing a multi-valued IS that int() cannot convert).
    """
    import warnings
    ds = Dataset()
    ds.Modality = modality
    ds.InstanceNumber = instance_number
    ds.StudyInstanceUID = identity.get("study_uid", STUDY_UID)
    ds.SeriesInstanceUID = identity.get("series_uid", SERIES_UID)
    ds.FrameOfReferenceUID = identity.get("frame_uid", FRAME_UID)
    ds.PatientID = identity.get("patient_id", PATIENT_ID)

    file_meta = FileMetaDataset()
    file_meta.MediaStorageSOPClassUID = _SOP_CLASS_UID
    file_meta.MediaStorageSOPInstanceUID = generate_uid()
    file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
    ds.file_meta = file_meta
    ds.preamble = b"\0" * 128

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        ds.save_as(path, enforce_file_format=True)
    return Path(path)


def make_ccb_style_plan(source: Path, out_path: Path,
                        ref_order=(4, 5, 1, 2, 3), with_delivery=(1, 2, 3),
                        without_dose=(), defined_beams=None) -> Path:
    """
    Rewrite a real RTPLAN so its fraction group mirrors the CCB case of issue #75.

    ``ref_order`` is the order of ReferencedBeamNumber values written into the
    ReferencedBeamSequence -- deliberately not the IonBeamSequence order. Only the
    beams in ``with_delivery`` keep BeamDose/BeamMeterset; the rest carry just the
    reference, as a plan does for beams that deliver nothing. Numbers in
    ``without_dose`` keep their meterset but lose BeamDose.

    IonBeamSequence covers every referenced number by default, so the two sequences
    describe the same beams and differ only in order and completeness. Pass
    ``defined_beams`` to break that deliberately -- either dropping a beam the fraction
    group delivers on, or defining one it never references.
    """
    import pydicom
    from copy import deepcopy

    ds = pydicom.dcmread(source)
    template_beam = ds.IonBeamSequence[0]

    beams = []
    for number in sorted(ref_order if defined_beams is None else defined_beams):
        beam = deepcopy(template_beam)
        beam.BeamNumber = number
        beam.BeamName = f"Beam{number}"
        beams.append(beam)
    ds.IonBeamSequence = Sequence(beams)

    references = []
    for number in ref_order:
        ref = Dataset()
        ref.ReferencedBeamNumber = number
        if number in with_delivery:
            # Distinct values per beam, so a mis-pairing is visible in assertions.
            if number not in without_dose:
                ref.BeamDose = 10.0 + number
            ref.BeamMeterset = 1000.0 * number
        references.append(ref)

    fg = ds.FractionGroupSequence[0]
    fg.ReferencedBeamSequence = Sequence(references)
    fg.NumberOfBeams = len(references)

    ds.save_as(out_path, enforce_file_format=True)
    return Path(out_path)
