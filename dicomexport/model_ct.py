from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Tuple, Optional


@dataclass
class Image:
    """
    A single image in a CT scan.

    Attributes:
        pixel_data: The pixel data of the image.
        instance_number: The instance number of the image.
        sop_instance_uid: The SOP Instance UID of the image.
        sop_class_uid: The SOP Class UID of the image.
    """
    modality: str = "CT"

    pixel_data: bytes = b""  # pixel data are not needed for the pipeline, but a placeholder is just provided for future use

    sop_class_uid: str = ""
    sop_instance_uid: str = ""
    modality: str = ""
    series_description: str = ""

    pixel_spacing: Tuple[float, float] = (0.0, 0.0)
    slice_thickness: float = 0.0
    slice_position: float = 0.0  # will be computed from image position and orientation
    image_orientation: Tuple[float, float, float, float, float, float] = (0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
    image_position_patient: Tuple[float, float, float] = (0.0, 0.0, 0.0)

    instance_number: int = 0

    patient_id: str = ""
    patient_name: str = ""
    patient_initials: str = ""
    patient_firstname: str = ""
    patient_position: str = ""
    rows: int = 0
    columns: int = 0


@dataclass
class CTModel:
    """
    A model for CT data in a proton treatment plan.

    Attributes:
        images: List of images in the CT model.
        directory: Directory holding the CT slices. TOPAS does not search subdirectories,
            so this may differ from the study directory.
"""
    images: List[Image] = field(default_factory=list)
    directory: Optional[Path] = None
    spr_to_material_path: Optional[Path] = None  # in fact mandatory as long we depend on the dose cube

    # In dicom format, the following data are per image, and could in princple be different
    # from image to image, but we assume they are the same for all images in this model
    # therefore we store them in the CTModel class as well.
    # Topas is not able to handle varying data per image, so it is legit here, but
    # but should this change in the future, we can still adapt the code.
    @property
    def patient_id(self) -> str:
        return self.images[0].patient_id if self.images else ""

    @property
    def patient_name(self) -> str:
        return self.images[0].patient_name if self.images else ""

    @property
    def patient_position(self) -> str:
        return self.images[0].patient_position if self.images else ""

    @property
    def rows(self) -> int:
        return self.images[0].rows if self.images else 0

    @property
    def columns(self) -> int:
        return self.images[0].columns if self.images else 0

    @property
    def n_slices(self) -> int:
        """Number of slices in the CT model."""
        return len(self.images)

    @property
    def slice_thickness(self) -> float:
        """Slice thickness of the CT model."""
        if len(self.images) > 1:
            return self.images[1].slice_position - self.images[0].slice_position
        else:
            return 0.0

    @property
    def voxel_size(self) -> Tuple[float, float, float]:
        """Voxel size (dx, dy, dz) in mm.

        DICOM PixelSpacing is (row spacing, column spacing) = (dy, dx).
        """
        if not self.images:
            return (0.0, 0.0, 0.0)
        dy, dx = self.images[0].pixel_spacing
        return (dx, dy, self.slice_thickness)

    @property
    def full_widths(self) -> Tuple[float, float, float]:
        """Full extent (x, y, z) of the CT volume in mm."""
        dx, dy, dz = self.voxel_size
        return (self.columns * dx, self.rows * dy, self.n_slices * dz)

    @property
    def half_widths(self) -> Tuple[float, float, float]:
        """Half extent (x, y, z) of the CT volume in mm."""
        return tuple(w * 0.5 for w in self.full_widths)  # type: ignore[return-value]

    @property
    def dicom_origin(self) -> Tuple[float, float, float]:
        """Centre of the CT volume, expressed in DICOM patient coordinates [mm].

        This reproduces what TOPAS computes internally for
        ``dc:Ge/Patient/DicomOrigin{X,Y,Z}`` (TsDicomPatient.cc), namely the
        position of the first voxel centre relative to the DICOM origin minus
        its position relative to the component centre.

        It must be written into the TOPAS input file, because TOPAS defines these
        parameters too late for its own geometry overlap check. See TopasText.variables().

        Only valid for an evenly spaced CT series; see _check_uniform_slice_spacing().
        """
        if not self.images:
            return (0.0, 0.0, 0.0)

        dx, dy, dz = self.voxel_size
        ipp = self.images[0].image_position_patient
        return (ipp[0] + 0.5 * (self.columns - 1) * dx,
                ipp[1] + 0.5 * (self.rows - 1) * dy,
                ipp[2] + 0.5 * (self.full_widths[2] - dz))

    def __repr__(self):
        return (
            f"<CTModel patient_id='{self.patient_id}', "
            f"name='{self.patient_name}', "
            f"position='{self.patient_position}', "
            f"slices={len(self.images)}>"
        )
