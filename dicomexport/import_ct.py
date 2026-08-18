import logging
import pydicom
import numpy as np
from pathlib import Path
from typing import List, Tuple

from dicomexport.ds_get import req, opt, tuple_of_float_2, tuple_of_float_3, tuple_of_float_6, as_int, as_str
from dicomexport.dicom_scan import CT, scan_study, raise_if_unreadable, check_single_study

from dicomexport.model_ct import CTModel, Image

logger = logging.getLogger(__name__)


def get_ct_files_sorted_by_instance_number(directory: Path) -> List[Path]:
    """
    Return a list of CT DICOM file paths in the directory,
    sorted by the DICOM 'InstanceNumber' tag.

    Files are selected by their Modality header, not by filename (issue #77), so
    PACS exports without a 'CT' prefix work and a structure set named 'CTV.dcm' is
    no longer handed to the CT reader.

    Reason for the sort: we cannot rely on the file names to be sorted correctly,
    e.g. when the files are copied from a PACS system or running numbering as 1 instead of 001.
    """
    scan = scan_study(directory)

    # A damaged file here is most likely a CT slice; see raise_if_unreadable().
    raise_if_unreadable(scan)

    # This is the one place that scans the whole study directory, so it is also where
    # "did the user drop two exports in here?" is caught -- two CT series in a single
    # directory would otherwise merge silently into one geometry.
    check_single_study(scan)

    files = list(scan.get(CT))
    if not files:
        raise FileNotFoundError(
            f"No CT DICOM files (Modality=CT) found in {directory} or its subdirectories")

    parent_dirs = {f.parent for f in files}
    if len(parent_dirs) > 1:
        dirs_str = ", ".join(str(d) for d in sorted(parent_dirs))
        raise ValueError(
            f"CT DICOM files found in multiple subdirectories under {directory}: {dirs_str}. "
            "Please ensure only one CT series is present under the study directory."
        )

    def get_instance_number(file: Path) -> int:
        # Harvested by scan_study() in the same header pass that classified the file.
        number = scan.instance_number_of(file)
        if number is None:
            # Absent, empty, or malformed -- scan_study() warns which. Either way the
            # slice order is unknown, and guessing it would misplace the patient.
            raise AttributeError(
                f"File {file} has no usable 'InstanceNumber' DICOM tag.")
        return number

    files.sort(key=get_instance_number)
    logger.info("Using %d CT slices from %s", len(files), files[0].parent)
    return files


def load_ct(mydir: Path) -> CTModel:
    """
    Load a series of CT DICOM files from a directory and return a CTModel.
    """
    if not mydir.is_dir():
        raise ValueError(f"{mydir} is not a directory")

    ct_files = get_ct_files_sorted_by_instance_number(mydir)

    # get_ct_files_sorted_by_instance_number() guarantees a single parent directory.
    ct_model = CTModel(directory=ct_files[0].parent)

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
            pixel_spacing=req(ds, "PixelSpacing", cast=tuple_of_float_2, n=2, file=file),
            image_orientation=req(ds, "ImageOrientationPatient", cast=tuple_of_float_6, n=6, file=file),
            image_position_patient=req(ds, "ImagePositionPatient", cast=tuple_of_float_3, n=3, file=file),
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

        # Compute slice_position, do not use slice_location from DICOM directly, since it is deprecated.
        img.slice_position = _get_slice_position(img.image_position_patient, img.image_orientation)

        ct_model.images.append(img)

    # Sort images by z-position if needed:
    ct_model.images.sort(key=lambda img: img.slice_position)

    _check_uniform_slice_spacing(ct_model)

    return ct_model


def _check_uniform_slice_spacing(ct: CTModel, tolerance: float = 0.002) -> None:
    """
    Warn if the CT slices are not evenly spaced.

    TOPAS splits such a series into several "slice thickness sections" and derives the
    patient origin from the first section only. dicomexport assumes a single section
    when it computes CTModel.dicom_origin, so an uneven series would be misplaced.
    The tolerance matches the one used in TOPAS' TsDicomPatient.cc.
    """
    if len(ct.images) < 3:
        return

    positions = np.array([img.slice_position for img in ct.images])
    separations = np.diff(positions)
    spread = float(separations.max() - separations.min())

    if spread > tolerance:
        logger.warning(
            "CT slice spacing is not uniform (varies by %.4f mm, from %.4f to %.4f mm). "
            "TOPAS will split this series into multiple slice thickness sections, and the "
            "patient may be misplaced along z. Consider resampling the CT to a uniform grid.",
            spread, float(separations.min()), float(separations.max()))


def _get_slice_position(ipp: Tuple[float, float, float], iop: Tuple[float, float, float, float, float, float]) -> float:
    """
    SliceLocation in DICOM is deprecated, and some CTs may not have it or even fill it with garbage values.
    Therefore, it will be taken from image_position_patient, taking scan orientation into account.

    Args:
        ipp: Image Position Patient (3 floats) as stored in DICOM.
        iop: Image Orientation Patient (6 floats) as stored in DICOM.
            - The first 3 elements (iop[0:3]) correspond to the row direction (X).
            - The last 3 elements (iop[3:6]) correspond to the column direction (Y).
            - The normal vector (Z direction) is computed as the cross product of row and column.

    Returns:
        The position of the slice along the normal vector (Z direction).
    """

    # ipp = np.array(ipp)
    # iop = np.array(iop)
    row = iop[0:3]
    col = iop[3:6]
    normal = np.cross(row, col)
    return float(np.dot(ipp, normal))
