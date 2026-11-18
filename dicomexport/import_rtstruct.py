import pydicom
import logging
from pathlib import Path
from typing import Dict, List

from dicomexport.dicom_scan import RTSTRUCT, scan_study, exactly_one
from dicomexport.model_rtstruct import RTStruct, RTStructROI


logger = logging.getLogger(__name__)


def load_rs(rtstruct_path: Path) -> RTStruct:
    """
    Import an RT Structure Set (RTSTRUCT) from a DICOM file and return a RTStruct.
    Path may also be a directory containing an RS*.dcm files.

    """

    if rtstruct_path.is_dir():
        # Select by Modality header rather than an RS*.dcm glob (issue #77).
        rtstruct_file = exactly_one(
            scan_study(rtstruct_path).get(RTSTRUCT),
            "RTSTRUCT files",
            rtstruct_path,
            "Please pass the specific RS file.",
        )
        logger.info(f"Using RTSTRUCT file: {rtstruct_file.name}")
    else:
        if not rtstruct_path.exists():
            raise FileNotFoundError(
                f"RTSTRUCT file not found: {rtstruct_path}")
        rtstruct_file = rtstruct_path

    ds = pydicom.dcmread(rtstruct_file)

    # Check if the file is an RTSTRUCT
    if ds.Modality != "RTSTRUCT":
        raise ValueError(
            f"File {rtstruct_file} is not a valid RTSTRUCT file (Modality: {ds.Modality})")

    # --- Basic patient info ---
    patient_id = ds.get("PatientID", "")
    patient_name = ds.get("PatientName", "")
    patient_firstname = ds.get("PatientFirstName", "")
    patient_initials = ds.get("PatientInitials", "")

    # --- Frame of Reference UID ---
    frame_of_reference_uid = getattr(ds, "FrameOfReferenceUID", None)
    if not frame_of_reference_uid:
        raise ValueError(
            "RTSTRUCT missing FrameOfReferenceUID, required for geometry consistency checks.")

    # --- Parse ROIs ---
    rois: List[RTStructROI] = []

    # Build ROI name/number map from StructureSetROISequence
    roi_name_map = {}
    for roi in ds.StructureSetROISequence:
        roi_number = int(roi.ROINumber)
        roi_name = str(roi.ROIName)
        roi_name_map[roi_number] = roi_name

    # Parse colors if available
    color_map = {}
    if hasattr(ds, "ROIContourSequence"):
        for roi_contour in ds.ROIContourSequence:
            roi_number = int(roi_contour.ReferencedROINumber)
            if hasattr(roi_contour, "ROIDisplayColor"):
                color_map[roi_number] = tuple(int(c)
                                              for c in roi_contour.ROIDisplayColor)

    declared = _declared_overrides(ds)

    # Assemble ROIs
    for roi_number, roi_name in roi_name_map.items():
        color = color_map.get(roi_number, (255, 255, 255))  # Default white
        rois.append(RTStructROI(
            roi_name=roi_name,
            roi_number=roi_number,
            rgb_color=color,
            declared_overrides=declared.get(roi_number, []),
        ))

    logger.info(
        f"Imported RTSTRUCT: {rtstruct_path.name} with {len(rois)} ROIs")

    return RTStruct(
        rois=rois,
        frame_of_reference_uid=frame_of_reference_uid,
        patient_id=patient_id,
        patient_name=str(patient_name),
        patient_initials=patient_initials,
        patient_firstname=patient_firstname,
        file_path=rtstruct_file,
    )


def _declared_overrides(ds) -> Dict[int, List[str]]:
    """What RTROIObservationsSequence declares about each ROI's material, by ROI number.

    The ROI's MaterialID (300A,00E1) and every item of its ROIPhysicalPropertiesSequence
    (3006,00B0), as "PROPERTY=value" strings. Treatment planning systems write these for
    density overrides; TOPAS ignores them (issue #94).
    """
    declared: Dict[int, List[str]] = {}
    for obs in ds.get("RTROIObservationsSequence", []):
        if "ReferencedROINumber" not in obs:
            continue
        entries = []
        if obs.get("MaterialID"):
            entries.append(f"MaterialID={obs.MaterialID}")
        for prop in obs.get("ROIPhysicalPropertiesSequence", []):
            name = str(prop.get("ROIPhysicalProperty", "")) or "ROIPhysicalProperty"
            entries.append(f"{name}={prop.get('ROIPhysicalPropertyValue', '')}")
        if entries:
            declared.setdefault(int(obs.ReferencedROINumber), []).extend(entries)
    return declared
