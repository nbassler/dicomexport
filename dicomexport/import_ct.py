import logging
import pydicom
from pathlib import Path
from typing import List

from dicomexport.ds_get import req, opt, tuple_of_float, as_int, as_str

from dicomexport.model_ct import CTModel, Image

logger = logging.getLogger(__name__)


def get_ct_files_sorted_by_instance_number(directory: Path) -> List[Path]:
    """
    Return a list of CT DICOM file paths in the directory,
    sorted by the DICOM 'InstanceNumber' tag.

    Reason: we cannot rely on the file names to be sorted correctly,
    e.g. when the files are copied from a PACS system or running numbering as 1 instead of 001.
    """
    files = list(directory.glob("CT*.dcm"))
    if not files:
        raise FileNotFoundError(
            f"No CT DICOM files matching 'CT*.dcm' found in {directory}")

    def get_instance_number(file: Path) -> int:
        ds = pydicom.dcmread(file, stop_before_pixels=True)
        if not hasattr(ds, 'InstanceNumber'):
            raise AttributeError(
                f"File {file} is missing 'InstanceNumber' DICOM tag.")
        return int(ds.InstanceNumber)

    files.sort(key=get_instance_number)
    return files


def load_ct(mydir: Path) -> CTModel:
    """
    Load a series of CT DICOM files from a directory and return a CTModel.
    """
    if not mydir.is_dir():
        raise ValueError(f"{mydir} is not a directory")

    ct_files = get_ct_files_sorted_by_instance_number(mydir)

    ct_model = CTModel()

    for file in ct_files:
        ds = pydicom.dcmread(file, stop_before_pixels=False)
        logger.debug(f"Loading CT slice: {file.name}")

        # The next parts are just tests for a new scheme for reading DICOM files which should be more robust
        # in case of missing tags which are non essential
        # The following approach is designed to robustly read DICOM files, handling missing or non-essential tags gracefully.
        # Required tags will raise errors if missing or malformed, while optional tags will default to safe values.
        # This scheme improves resilience when processing DICOM data from diverse sources.
        #
        img = Image(
            # REQUIRED — fail fast if missing/malformed
            pixel_spacing=req(ds, "PixelSpacing", cast=tuple_of_float, n=2, file=file),
            slice_location=req(ds, "SliceLocation", cast=float, file=file),
            image_orientation=req(ds, "ImageOrientationPatient", cast=tuple_of_float, n=6, file=file),
            image_position_patient=req(ds, "ImagePositionPatient", cast=tuple_of_float, n=3, file=file),
            rows=req(ds, "Rows", cast=int, file=file),
            columns=req(ds, "Columns", cast=int, file=file),
            patient_position=req(ds, "PatientPosition", cast=as_str, file=file),

            # OPTIONAL — default silently if missing/odd
            sop_class_uid=opt(ds, "SOPClassUID", "", cast=as_str),
            sop_instance_uid=opt(ds, "SOPInstanceUID", "", cast=as_str),
            modality=opt(ds, "Modality", "", cast=as_str),
            series_description=opt(ds, "SeriesDescription", "", cast=as_str),
            instance_number=opt(ds, "InstanceNumber", 0, cast=as_int),
            patient_name=opt(ds, "PatientName", "", cast=as_str),
            patient_id=opt(ds, "PatientID", "", cast=as_str),
        )
        ct_model.images.append(img)

    # Sort images by z-position if needed:
    ct_model.images.sort(key=lambda img: img.image_position_patient[2])

    return ct_model
