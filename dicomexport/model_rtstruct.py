from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple


@dataclass
class RTStructROI:
    """
    A model for a single ROI (Region of Interest) in an RT Structure Set.
    """
    roi_name: str
    roi_number: int
    rgb_color: Tuple[int, int, int]  # RGB color

    # What the RTSTRUCT declares about the ROI's material, as "PROPERTY=value" strings: its
    # MaterialID and every ROIPhysicalProperty, e.g. "REL_ELEC_DENSITY=1.0" (issue #94).
    # dicomexport does not apply them; it warns when no --material-override covers them.
    declared_overrides: List[str] = field(default_factory=list)

    # Contour data can be added here if needed, but they are not needed for the pipeline.
    # Contour data are in patient coordinates.


@dataclass
class RTStruct:
    """
    A model representing an RT Structure Set for proton therapy planning.

    Attributes:
        rois: List of ROIs in the structure set.
        patient_id: Patient ID.
        patient_name: Patient name.
        patient_initials: Patient initials.
        patient_firstname: Patient first name.
    """

    modality: str = "RTSTRUCT"  # Default modality for RT Structure Set

    rois: List[RTStructROI] = field(default_factory=list)

    patient_id: str = ""
    patient_name: str = ""
    patient_initials: str = ""
    patient_firstname: str = ""
    frame_of_reference_uid: str = ""

    file_path: Optional[Path] = None
    """The RTSTRUCT file read, as found under the path given (relative stays relative)."""

    @property
    def n_rois(self) -> int:
        """Return the number of ROIs in the structure set."""
        return len(self.rois)
