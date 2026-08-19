import sys
import logging
from dataclasses import dataclass, field as dc_field
from typing import List, Tuple, Optional
from io import StringIO
from pathlib import Path

from dicomexport.beam_model import BeamModel, get_fwhm

logger = logging.getLogger(__name__)


INDENT = "    "

#: "No range shifter". Always resolvable, including when a user catalog replaces the
#: built-in one, since it describes the absence of a device rather than a device.
NO_RANGE_SHIFTER_ID = "None"

#: Physical thickness [mm] and material of the range shifters dicomexport has met.
#: A DICOM plan names only the RangeShifterID, so these have to be looked up.
#: Mirrored as per-site CSVs under res/range_shifters/, which also serve as the
#: worked examples for --range-shifter-catalog.
RS_CATALOG = {
    NO_RANGE_SHIFTER_ID: {"thickness": 0.0, "material": None},
    "RS_2CM":  {"thickness": 20.0,  "material": "Lexan"},   # DCPT
    "RS_3CM":  {"thickness": 30.0,  "material": "Lexan"},   # DCPT
    "RS_5CM":  {"thickness": 50.0,  "material": "Lexan"},   # DCPT
    "RS_Block": {"thickness": 39.936, "material": "Lexan"},  # CCB
    "RS_3.5": {"thickness": 30.62,  "material": "Lexan"},  # Skandion, name quotes WET
    # WPE. PROVISIONAL: assumed 5.1 cm Lexan from the ID, not confirmed by the centre.
    # The plan carries no RangeShifterWaterEquivalentThickness to cross-check against,
    # and Skandion's RS_3.5 above shows an ID can quote WET rather than thickness --
    # if RS51 means 51 mm WET, the physical Lexan is nearer 45 mm. Confirm before
    # trusting a range computed with it.
    "RS51": {"thickness": 51.0, "material": "Lexan"},
}


def load_range_shifter_catalog(path: Path) -> dict:
    """
    Read a range shifter catalog CSV and return it in RS_CATALOG form.

    The result *replaces* the built-in catalog rather than extending it, so the file
    must list every shifter the plan uses. See res/range_shifters/README.md for why,
    and for the format: ``id,thickness_mm,material`` with ``#`` comments.

    The "no shifter" entry is always added, so a plan using that ID keeps working
    whatever the file contains.
    """
    catalog: dict = {NO_RANGE_SHIFTER_ID: {"thickness": 0.0, "material": None}}

    with open(path, newline="", encoding="utf-8") as f:
        for lineno, raw in enumerate(f, start=1):
            line = raw.split("#", 1)[0].strip()
            if not line:
                continue

            parts = [c.strip() for c in line.split(",")]
            if len(parts) != 3:
                raise ValueError(
                    f"{path}:{lineno}: expected 3 comma-separated columns "
                    f"(id,thickness_mm,material), found {len(parts)}: {raw.strip()!r}")

            rs_id, thickness, material = parts
            if not rs_id:
                raise ValueError(f"{path}:{lineno}: range shifter ID is empty")
            if rs_id in catalog and rs_id != NO_RANGE_SHIFTER_ID:
                raise ValueError(f"{path}:{lineno}: duplicate range shifter ID {rs_id!r}")

            try:
                thickness_mm = float(thickness)
            except ValueError:
                raise ValueError(
                    f"{path}:{lineno}: thickness for {rs_id!r} is not a number: "
                    f"{thickness!r}") from None
            if not thickness_mm >= 0.0:
                raise ValueError(
                    f"{path}:{lineno}: thickness for {rs_id!r} must be >= 0 mm, "
                    f"got {thickness_mm}")

            catalog[rs_id] = {"thickness": thickness_mm, "material": material or None}

    if len(catalog) == 1:
        raise ValueError(f"{path}: no range shifters defined")

    logger.info("Range shifter catalog %s replaces the built-in one: %s",
                path, ", ".join(k for k in catalog if k != NO_RANGE_SHIFTER_ID))
    return catalog


@dataclass
class RangeShifter:
    """Range shifter data."""
    id: str = ""
    number: int = 0
    type: str = ""
    thickness: float = 0.0  # in mm
    # distance from isocenter to downstream edge of range shifter is given in DICOM file [mm]
    isocenter_distance: float = 0.0
    material: Optional[str] = "Lexan"  # None when there is no shifter
    is_inserted: bool = False  # True if range shifter is inserted

    # the following are for future compatibility, but at the moment not used
    # density: float = 1.20  # g/cm3
    water_equivalent_thickness: float = 0.0  # mm


@dataclass
class Spot:
    """Single scanned spot in a proton layer."""
    x: float
    y: float
    mu: float
    size_x: float = 0.0  # FWHM in X
    size_y: float = 0.0  # FWHM in Y

    def __repr__(self):
        return f"<Spot x={self.x:.2f} y={self.y:.2f} mu={self.mu:.4f}>"


@dataclass
class Layer:
    """
    A single energy layer in a proton field.

    Attributes:
        spots: List of Spot objects.
        energy_nominal: Nominal beam energy [MeV].
        energy_measured: Measured energy [MeV].
        espread: Energy spread [MeV].
        cum_mu: Cumulative MU.
        repaint: Number of repaintings.
        mu_to_part_coef: Conversion MU -> particles.
        is_empty: True if no MU.
        isocenter: (x, y, z) position [mm].
        gantry_angle: [deg]
        couch_angle: [deg]
        snout_position: [mm]
        table_position: (vert, long, lat) [mm].
        meterset_rate: MU/min (optional).
        number: Layer number (int).
        spot_size: FWHM [mm] (set after beam model application).
    """

    spots: List[Spot] = dc_field(default_factory=list)
    energy_nominal: float = 0.0  # [MeV]
    energy_measured: float = 0.0  # [MeV]
    espread: float = 0.0  # [MeV] 1 sigma
    cum_mu: float = 0.0  # cumulative MU
    cum_particles: float = 0.0
    repaint: int = 0
    mu_to_part_coef: float = 0.0
    is_empty: bool = True

    isocenter: Tuple[float, float, float] = (0.0, 0.0, 0.0)     # [mm]
    gantry_angle: float = 0.0  # [deg]
    couch_angle: float = 0.0   # [deg]
    snout_position: float = 0.0  # [mm]
    table_position: Tuple[float, float, float] = (0.0, 0.0, 0.0)  # [mm]
    meterset_rate: float = 0.0

    number: int = 0  # layer number, starting from 1, only including layers which contain data
    spot_size: Tuple[float, float] = (0.0, 0.0)  # FWHM in (x,y), set after beam model application [mm]

    @property
    def n_spots(self) -> int:
        return len(self.spots)

    @property
    def n_particles(self) -> float:
        """Number of particles in this layer.
           will only be meaningful after beam model application."""
        if self.mu_to_part_coef > 0.0:
            return self.cum_mu * self.mu_to_part_coef
        else:
            return 0.0

    @property
    def xmin(self) -> float:
        return min((spot.x for spot in self.spots), default=0.0)

    @property
    def xmax(self) -> float:
        return max((spot.x for spot in self.spots), default=0.0)

    @property
    def ymin(self) -> float:
        return min((spot.y for spot in self.spots), default=0.0)

    @property
    def ymax(self) -> float:
        return max((spot.y for spot in self.spots), default=0.0)

    def __repr__(self):
        lines = []
        lines.append("------------------------------------------------")
        lines.append(
            f"Energy nominal        : {self.energy_nominal:10.4f} MeV")
        lines.append(
            f"Energy measured       : {self.energy_measured:10.4f} MeV")
        lines.append(f"Energy spread         : {self.espread:10.4f} MeV")
        lines.append(f"Cumulative MU         : {self.cum_mu:10.4f}")
        lines.append(
            f"Cumulative particles  : {getattr(self, 'cum_particles', 0.0):10.4e} (estimated)")
        lines.append(f"Number of spots       : {self.n_spots:10d}")
        lines.append("------------------------------------------------")
        lines.append(
            f"Spot layer min/max X  : {self.xmin:+10.4f} {self.xmax:+10.4f} mm")
        lines.append(
            f"Spot layer min/max Y  : {self.ymin:+10.4f} {self.ymax:+10.4f} mm")
        lines.append("------------------------------------------------")
        return "\n".join(lines)


@dataclass
class Field:
    """A field consisting of multiple energy layers."""

    modality: str = "RTPLAN"

    layers: List[Layer] = dc_field(default_factory=list)
    dose: float = 0.0
    cum_mu: float = 0.0
    cum_particles: float = 0.0
    pld_csetweight: float = 0.0
    scaling: float = 1.0
    name: str = ""

    meterset_weight_final: float = 0.0
    meterset_per_weight: float = 0.0

    #: (x, y) source-to-axis distance [mm]: the point the scanned ray pivots about,
    #: taken from the deflection magnets where the plan names them and otherwise from
    #: VirtualSourceAxisDistances. This is the ONLY home for the value -- it is a
    #: per-beam machine property and does not vary between layers.
    #:
    #: (0.0, 0.0) means unknown, as for PLD and RST plans, which carry no SAD. DICOM
    #: plans never leave it unset: the importer raises instead. Consumers must never
    #: divide by it unchecked, and they differ deliberately in what they do instead
    #: (issue #79): the MCPL and spotlist exporters fall back to a parallel beam and
    #: warn, since a phase space without divergence is still usable; the TOPAS
    #: exporter raises, because it must emit a per-spot angle and a silently
    #: zero-angle beam would be indistinguishable from a real one in the output.
    sad: Tuple[float, float] = (0.0, 0.0)
    sop_instance_uid: str = ""
    number: int = 0

    range_shifter: Optional[RangeShifter] = None  # optional range shifter data

    @property
    def n_layers(self) -> int:
        return len(self.layers)

    @property
    def n_particles(self) -> float:
        """Total number of particles in this field.
        Will only be meaningful after beam model application."""
        return sum(layer.n_particles for layer in self.layers)

    @property
    def n_spots(self) -> int:
        return sum(layer.n_spots for layer in self.layers)

    @property
    def xmin(self) -> float:
        return min((layer.xmin for layer in self.layers if layer.n_spots > 0), default=0.0)

    @property
    def xmax(self) -> float:
        return max((layer.xmax for layer in self.layers if layer.n_spots > 0), default=0.0)

    @property
    def ymin(self) -> float:
        return min((layer.ymin for layer in self.layers if layer.n_spots > 0), default=0.0)

    @property
    def ymax(self) -> float:
        return max((layer.ymax for layer in self.layers if layer.n_spots > 0), default=0.0)

    @property
    def emin(self) -> float:
        """Minimum energy of all layers in this field."""
        return min(layer.energy_nominal for layer in self.layers) if self.layers else 0.0

    @property
    def emax(self) -> float:
        """Maximum energy of all layers in this field."""
        return max(layer.energy_nominal for layer in self.layers) if self.layers else 0.0

    def diagnose(self):
        """Print overview of field to stdout."""
        print(self.__repr__())

    def __repr__(self):
        """Return overview of field as a string."""

        lines = []
        lines.append(
            INDENT + "------------------------------------------------")
        lines.append(INDENT + f"Energy layers          : {self.n_layers:10d}")
        lines.append(INDENT + f"Total MUs              : {self.cum_mu:10.4f}")
        lines.append(
            INDENT + "------------------------------------------------")
        for i, layer in enumerate(self.layers):
            lines.append(
                INDENT + f"   Layer {i+1:3}: {layer.energy_nominal: 10.4f} MeV " + f"   {layer.n_spots:10d} spots")
        lines.append(
            INDENT + f"Lowest energy          : {self.emin:10.4f} MeV")
        lines.append(
            INDENT + f"Highest energy         : {self.emax:10.4f} MeV")
        lines.append(
            INDENT + "------------------------------------------------")
        lines.append(
            INDENT + f"Spot field min/max X   : {self.xmin:+10.4f} {self.xmax:+10.4f} mm")
        lines.append(
            INDENT + f"Spot field min/max Y   : {self.ymin:+10.4f} {self.ymax:+10.4f} mm")
        lines.append(
            INDENT + "------------------------------------------------")
        lines.append("")
        return "\n".join(lines)


@dataclass
class Plan:
    """A proton therapy plan consisting of multiple fields."""

    fields: List[Field] = dc_field(default_factory=list)
    patient_id: str = ""
    patient_name: str = ""
    patient_initials: str = ""
    patient_firstname: str = ""
    plan_label: str = ""
    plan_date: str = ""
    sop_instance_uid: str = ""
    beam_model: Optional[BeamModel] = None  # optional beam model class
    beam_name: str = ""
    scaling: float = 1.0
    # uid: str = ""

    @property
    def n_fields(self) -> int:
        return len(self.fields)

    @property
    def n_layers(self) -> int:
        return sum(field.n_layers for field in self.fields)

    @property
    def n_spots(self) -> int:
        return sum(field.n_spots for field in self.fields)

    def apply_beammodel(self):
        """Adjust plan to beam model."""
        if self.beam_model:
            for myfield in self.fields:
                for layer in myfield.layers:
                    # calculate number of particles
                    layer.mu_to_part_coef = self.beam_model.f_ppmu(
                        layer.energy_nominal)
                    logger.debug(
                        f"Layer {layer.energy_nominal} MeV, MU to particles conversion factor = {layer.mu_to_part_coef:.2f}")
                    logger.debug(
                        f"Layer {layer.energy_nominal} MeV, mu_to_part_coef = {layer.mu_to_part_coef:.2f}")
                    layer.energy_measured = self.beam_model.f_e(
                        layer.energy_nominal)
                    layer.espread = self.beam_model.f_espread(
                        layer.energy_nominal)
                    layer.spot_size = (
                        self.beam_model.f_sx(layer.energy_nominal) * get_fwhm(1.0),
                        self.beam_model.f_sy(layer.energy_nominal) * get_fwhm(1.0)
                    )
        else:
            logger.error("No beam model set, cannot apply beam model to plan.")
            raise ValueError("No beam model set for plan.")

        # set cumulative sums
        for myfield in self.fields:
            myfield.cum_particles = 0.0
            myfield.cum_mu = 0.0

            # set layer specific values
            for layer in myfield.layers:
                logger.debug("Processing layer with %d spots", layer.n_spots)
                if layer.n_spots > 0:
                    mu_list = [spot.mu for spot in layer.spots]
                    layer.cum_mu = sum(mu_list)
                    layer.is_empty = False

                    myfield.cum_particles += layer.cum_particles
                    myfield.cum_mu += layer.cum_mu

    def __repr__(self):
        """Return overview of plan as a string."""
        lines = []
        lines.append("Diagnostics:")
        lines.append("---------------------------------------------------")
        lines.append(
            f"Patient Name           : '{self.patient_name}'       [{self.patient_initials}]")
        lines.append(f"Patient ID             : {self.patient_id}")
        lines.append(f"Plan label             : {self.plan_label}")
        lines.append(
            f"Plan date              : {getattr(self, 'plan_date', '')}")
        lines.append(f"Number of Fields       : {self.n_fields:2d}")

        for i, myfield in enumerate(self.fields):
            lines.append("---------------------------------------------------")
            lines.append(
                f"   Field                  : {i + 1:02d}/{self.n_fields:02d}:")
            # Use the field's diagnose method if it returns a string, else str()
            diagnose_str = getattr(myfield, '__str__', None)
            if callable(diagnose_str):
                lines.append(str(myfield))
            else:
                # fallback to diagnose() if it prints
                buf = StringIO()
                sys_stdout = sys.stdout
                sys.stdout = buf
                myfield.diagnose()
                sys.stdout = sys_stdout
                lines.append(buf.getvalue().strip())
            lines.append("")
        return "\n".join(lines)
