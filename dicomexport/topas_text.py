import datetime
import getpass
import logging  # used for recording the user who generated the file
from pathlib import Path
from typing import Optional, Tuple

from dicomexport.model_plan import Field
from dicomexport.model_ct import CTModel
from dicomexport.model_rtstruct import RTStruct
from dicomexport.__version__ import __version__

logger = logging.getLogger(__name__)


# Air padding added around everything that must fit inside the world volume [mm].
# An oversized world is cheap and is more correct for out-of-field dosimetry: particles
# leaving the world are killed rather than allowed to scatter back into the patient.
WORLD_MARGIN = 500.0


class TopasText:
    @staticmethod
    def header(field: Field, nstat_scale: float, nstat: int) -> str:
        lines = [
            f"# Topas input file for field {field.number}",
            '# ' + '-' * 40,
            f"# SOP_INSTANCE_UID {field.sop_instance_uid}",
            "# ",
            f"# TOTAL_NUMBER_OF_PARTICLES: {field.n_particles:.0f}",
            f"# TOTAL_MU: {field.cum_mu:.2f}",
            f"# REQUESTED_HISTORIES: {nstat:.0f}",
            f"# PARTICLE_SCALING: {nstat_scale:.2f}",
            "#\n"
        ]
        return "\n".join(lines)

    @staticmethod
    def header2() -> str:
        "Add a footer to the topas file with generation date and username."

        lines = [
            f"# Generated {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')} by user '{getpass.getuser()}'",
            f"# using dicomexport {__version__}",
            "# https://github.com/nbassler/dicomexport",
            "#\n"
        ]

        return "\n".join(lines)

    @staticmethod
    def spr_to_material(spr_path: Path) -> str:
        lines = [
            "##############################################",
            "###        SPR TO MATERIAL PATH            ###",
            "##############################################",
            f'includeFile                          = {spr_path}',
            "\n"
        ]
        return "\n".join(lines)

    @staticmethod
    def variables(myfield: Field, dicom_origin: Tuple[float, float, float] = (0.0, 0.0, 0.0)) -> str:
        # Extract isocenter, gantry, couch, and snout_position from the first layer
        # varying isocenter, gantry, couch, snout_position per controlpoint is not supported.
        layer = myfield.layers[0]
        isocenter = getattr(layer, "isocenter", [0.0, 0.0, 0.0])
        gantry_angle = getattr(layer, "gantry_angle", 0.0)
        couch_angle = getattr(layer, "couch_angle", 0.0)
        snout_position = getattr(layer, "snout_position", 421.0)

        lines = [
            "##############################################",
            "###           V A R I A B L E S            ###",
            "##############################################",
            "",
            f"d:Rt/Plan/IsoCenterX                 = {isocenter[0]:.2f} mm",
            f"d:Rt/Plan/IsoCenterY                 = {isocenter[1]:.2f} mm",
            f"d:Rt/Plan/IsoCenterZ                 = {isocenter[2]:.2f} mm",
            f"d:Ge/snoutPosition                   = {snout_position:.2f} mm",
            f"d:Ge/gantryAngle                     = {gantry_angle:.2f} deg",
            f"d:Ge/couchAngle                      = {couch_angle:.2f} deg",
            "",
            "# Centre of the CT volume in DICOM coordinates. TsDicomPatient redefines these itself,",
            "# but only while reading the image, which is after it has calculated the initial patient",
            "# placement from Ge/Patient/Trans*. TOPAS recalculates the placement before the first run,",
            "# so these values do not affect the tracking geometry -- but the geometry overlap check",
            "# runs on the initial placement. Left at 0 the patient is checked at -IsoCenter instead of",
            "# CTcentre - IsoCenter, which aborts TOPAS on a spurious overlap for a long CT (issue #61).",
            f"dc:Ge/Patient/DicomOriginX           = {dicom_origin[0]:.4f} mm",
            f"dc:Ge/Patient/DicomOriginY           = {dicom_origin[1]:.4f} mm",
            f"dc:Ge/Patient/DicomOriginZ           = {dicom_origin[2]:.4f} mm",
            "\n"
        ]
        return "\n".join(lines)

    @staticmethod
    def setup(show_history_interval: int = 100000, nr_threads: int = 0) -> str:
        """
        Generate the TOPAS setup section.

        show_history_interval: Interval at which the history count is shown.
        nr_threads: 0 for using all cores, -1 for all but one.
        """

        # model1 = (
        #     'sv:Ph/Default/Modules                = 6 '
        #     '"g4em-standard_opt3" '
        #     '"g4h-phy_QGSP_BIC_HP" '
        #     '"g4decay" '
        #     '"g4ion-binarycascade" '
        #     '"g4h-elastic_HP" '
        #     '"g4stopping"'
        # )
        model2 = (
            'sv:Ph/Default/Modules                = 6 '
            '"g4em-standard_opt4" '
            '"g4h-phy_QGSP_BIC_AllHP" '
            '"g4decay" '
            '"g4ion-binarycascade" '
            '"g4h-elastic_HP" '
            '"g4stopping"'
        )

        lines = [
            "##############################################",
            "###         T O P A S    S E T U P         ###",
            "##############################################",
            f"# {model2}",
            f"i:Ts/ShowHistoryCountAtInterval         = {show_history_interval}",
            f"i:Ts/NumberOfThreads                    = {nr_threads}",
            "b:Ts/DumpParameters                     = \"False\"",
            "b:Ge/Patient/IgnoreInconsistentFrameOfReferenceUID = \"True\"",
            "\n"
        ]
        return "\n".join(lines)

    @staticmethod
    def world_half_lengths(ct: Optional[CTModel] = None,
                           isocenter: Tuple[float, float, float] = (0.0, 0.0, 0.0),
                           beam_reach: float = 0.0,
                           margin: float = WORLD_MARGIN) -> Tuple[float, float, float]:
        """
        Half-lengths [mm] of a world box that contains both the patient and the beam line.

        The patient box is centred at ``dicom_origin - isocenter`` (see geometry_patient_dicom())
        and the beam line extends up to ``beam_reach`` from the isocenter at the world origin,
        in any direction the gantry can rotate to.

        ct: CT model, or None if the study has no patient (e.g. test mode).
        isocenter: plan isocenter in DICOM coordinates [mm].
        beam_reach: distance from the isocenter to the most upstream beam element [mm].
        margin: air padding added on every side [mm].
        """
        reach = [beam_reach] * 3

        if ct is not None and ct.images:
            centre = [o - i for o, i in zip(ct.dicom_origin, isocenter)]
            reach = [max(r, abs(c) + h)
                     for r, c, h in zip(reach, centre, ct.half_widths)]

        return (reach[0] + margin, reach[1] + margin, reach[2] + margin)

    @staticmethod
    def world_setup(half_lengths: Tuple[float, float, float]) -> str:
        hlx, hly, hlz = half_lengths
        lines = [
            "##############################################",
            "###         W O R L D    S E T U P         ###",
            "##############################################",
            's:Ge/World/Type            = "TsBox"',
            's:Ge/World/Material        = "Air"',
            f"d:Ge/World/HLX             = {hlx:.2f} mm",
            f"d:Ge/World/HLY             = {hly:.2f} mm",
            f"d:Ge/World/HLZ             = {hlz:.2f} mm",
            'b:Ge/World/Invisible       = "True"',
            "\n"
        ]
        return "\n".join(lines)

    @staticmethod
    def geometry_patient_dicom(rd_path: Path, ct_dir: Optional[Path] = None) -> str:
        # TOPAS reads the CT series from DicomDirectory without descending into subdirectories,
        # so it must be the directory holding the slices, not necessarily the study directory.
        # Emit POSIX separators: on Windows str(Path) yields backslashes, which TOPAS misparses.
        # Pass paths through verbatim (no .resolve()): relative-in -> relative-out keeps study
        # directories relocatable; a caller wanting absolute paths passes absolute ones (see #63).
        dicom_dir = (ct_dir if ct_dir else rd_path.parent).as_posix()
        rtdose_path = rd_path.as_posix()
        lines = [
            "##############################################",
            "###            G E O M E T R Y             ###",
            "##############################################",
            's:Ge/Patient/Parent                  = "World"',
            's:Ge/Patient/Type                    = "TsDicomPatient"',
            f's:Ge/Patient/DicomDirectory          = "{dicom_dir}"',
            'sv:Ge/Patient/DicomModalityTags      = 1 "CT"',
            f's:Ge/Patient/CloneRTDoseGridFrom     = "{rtdose_path}"',
            'd:Ge/Patient/TransX                  = Ge/Patient/DicomOriginX - Rt/Plan/IsoCenterX mm',
            'd:Ge/Patient/TransY                  = Ge/Patient/DicomOriginY - Rt/Plan/IsoCenterY mm',
            'd:Ge/Patient/TransZ                  = Ge/Patient/DicomOriginZ - Rt/Plan/IsoCenterZ mm',
            'd:Ge/Patient/RotX                    = 0.00 deg',
            'd:Ge/Patient/RotY                    = 0.00 deg',
            'd:Ge/Patient/RotZ                    = 0.00 deg',
            's:Ge/Patient/Color                   = "Red"',
            "\n"
        ]
        return "\n".join(lines)

    @staticmethod
    def geometry_patient(ct: CTModel, rs: RTStruct) -> str:
        """
        Generate the geometry section for the patient.
        """
        lines = [
            "##############################################",
            "###         G E O M E T R Y   P A T I E N T ###",
            "##############################################",
            's:Ge/Patient/Parent                   = "World"',
            's:Ge/Patient/Type                     = "Group"',
            f'd:Ge/Patient/DicomOriginX             = {ct.dicom_origin[0]:.2f} mm',
            f'd:Ge/Patient/DicomOriginY             = {ct.dicom_origin[1]:.2f} mm',
            f'd:Ge/Patient/DicomOriginZ             = {ct.dicom_origin[2]:.2f} mm',
            "\n"
        ]
        return "\n".join(lines)

    @staticmethod
    def geometry_water_phantom(size: float = 300.0) -> str:
        """
        Generate the geometry section for the water phantom.
        """
        lines = [
            "##############################################",
            "###      G E O M E T R Y   WATERPHANTOM    ###",
            "##############################################",
            's:Ge/WaterPhantom/Parent                     = "Patient"',
            's:Ge/WaterPhantom/Type                       = "TsBox"',
            's:Ge/WaterPhantom/Material                   = "G4_Water"',
            f"d:Ge/WaterPhantom/HLX                        = {size:.2f} mm",
            f"d:Ge/WaterPhantom/HLY                        = {size:.2f} mm",
            f"d:Ge/WaterPhantom/HLZ                        = {size:.2f} mm",
            f'd:Ge/WaterPhantom/TransX                     = {0.0:.2f} mm',
            f'd:Ge/WaterPhantom/TransY                     = {0.0:.2f} mm',
            f'd:Ge/WaterPhantom/TransZ                     = {0.0:.2f} mm',
            f'd:Ge/WaterPhantom/RotX                       = {0.0:.2f} deg',
            f'd:Ge/WaterPhantom/RotY                       = {0.0:.2f} deg',
            f'd:Ge/WaterPhantom/RotZ                       = {0.0:.2f} deg',
            f'd:Ge/WaterPhantom/MaxStepSize                = {0.5:.2f} mm',
            'c:Ge/WaterPhantom/Color                     = "Blue"',
            "\n"
        ]
        return "\n".join(lines)

    @staticmethod
    def geometry_gantry() -> str:
        lines = [
            "##############################################",
            "###     G E O M E T R Y   G A N T R Y      ###",
            "##############################################",
            's:Ge/Gantry/Parent                   = "DCM_to_IEC"',
            's:Ge/Gantry/Type                     = "Group"',
            "d:Ge/Gantry/TransX                   = 0.00 mm",
            "d:Ge/Gantry/TransY                   = 0.00 mm",
            "d:Ge/Gantry/TransZ                   = 0.00 mm",
            "d:Ge/Gantry/RotX                     = 0.00 deg",
            "d:Ge/Gantry/RotY                     = Ge/gantryAngle deg",
            "d:Ge/Gantry/RotZ                     = 0.00 deg",
            "\n"
        ]
        return "\n".join(lines)

    @staticmethod
    def geometry_couch() -> str:
        lines = [
            "##############################################",
            "###      G E O M E T R Y    C O U C H      ###",
            "##############################################",
            's:Ge/Couch/Parent                  = "World"',
            's:Ge/Couch/Type                    = "Group"',
            "d:Ge/Couch/RotX                    = 0. deg",
            "d:Ge/Couch/RotY                    = -1.0 * Ge/couchAngle deg",
            "d:Ge/Couch/RotZ                    = 0. deg",
            "d:Ge/Couch/TransX                  = 0.0 mm",
            "d:Ge/Couch/TransY                  = 0.0 mm",
            "d:Ge/Couch/TransZ                  = 0.0 mm",
            "\n"
        ]
        return "\n".join(lines)

    @staticmethod
    def geometry_dcm_to_iec() -> str:
        lines = [
            "##############################################",
            "###      G E O M E T R Y    DCM_to_IEC     ###",
            "##############################################",
            's:Ge/DCM_to_IEC/Parent               = "Couch"',
            's:Ge/DCM_to_IEC/Type                 = "Group"',
            "d:Ge/DCM_to_IEC/TransX               = 0.0 mm",
            "d:Ge/DCM_to_IEC/TransY               = 0.0 mm",
            "d:Ge/DCM_to_IEC/TransZ               = 0.0 mm",
            "d:Ge/DCM_to_IEC/RotX                 = 90.00 deg",
            "d:Ge/DCM_to_IEC/RotY                 = 0.0 deg",
            "d:Ge/DCM_to_IEC/RotZ                 = 0.0 deg",
            "\n"
        ]
        return "\n".join(lines)

    @staticmethod
    def geometry_beam_position_timefeature(beam_model_position: float = 500.0,
                                           beam_direction: int = 1) -> str:
        # RotY is pre-computed per spot into the BeamPositionRotY time feature.
        # TOPAS rotation parameters are passive (TsVGeometryComponent composes
        # fRotRelToWorld = R_child * R_parent and the local->world map uses the inverse),
        # so the IEC-correct nozzle sits at gantry-local -Z emitting along its +Z:
        #   neg-Z (beam_direction=-1): TransZ=-bmp, RotY=-angx   (IEC 61217, default).
        #     Verified against OpenTOPAS 4.2.3: gantry 0 enters an HFS patient anterior,
        #     gantry 90 from the patient's left (issue #66).
        #   pos-Z (beam_direction=1):  TransZ=+bmp, RotY=180-angx. Source mirrored to
        #     gantry+180°; only for non-patient research setups.
        transz = f"{beam_model_position}" if beam_direction == 1 else f"-{beam_model_position}"
        lines = [
            "##############################################",
            "###    GEOM.  B E A M   P O S I T I O N    ###",
            "##############################################",
            's:Ge/BeamPosition/Parent             = "Gantry"',
            's:Ge/BeamPosition/Type               = "Group"',
            f"d:Ge/BeamPosition/TransZ             = {transz} mm",
            "d:Ge/BeamPosition/TransX             = Tf/spotPositionX/Value mm",
            "d:Ge/BeamPosition/TransY             = -1.0 * Tf/spotPositionY/Value mm",
            "d:Ge/BeamPosition/RotX               = -1.0 * Tf/spotAngleY/Value deg",
            "d:Ge/BeamPosition/RotY               = Tf/BeamPositionRotY/Value deg",
            "d:Ge/BeamPosition/RotZ               = 0.00 deg",
            "\n"
        ]
        return "\n".join(lines)

    @staticmethod
    def geometry_range_shifter(myfield: Field, beam_direction: int = 1) -> str:
        if myfield.range_shifter is None:
            return ""

        rs = myfield.range_shifter
        if rs.thickness <= 0.0:
            # A zero-thickness slab is not geometry. The importer resolves "no shifter"
            # to None rather than to a 0 mm device, so this should be unreachable from
            # DICOM -- but emitting a degenerate TsBox would be worse than emitting none.
            logger.warning(
                "Field %d: range shifter %r has thickness %.3f mm; emitting no geometry.",
                myfield.number, rs.id, rs.thickness)
            return ""
        transz = beam_direction * (rs.isocenter_distance + rs.thickness * 0.5)

        lines = [
            "##############################################",
            "###        R A N G E   S H I F T E R       ###",
            "##############################################",
            's:Ge/RangeShifter/Parent             = "Gantry"',
            's:Ge/RangeShifter/Type               = "TsBox"',
            f's:Ge/RangeShifter/Material           = "{rs.material}"',
            'b:Ge/RangeShifter/Isparallel         = "True"',
            'sv:Ph/Default/LayeredMassGeometryWorlds = 2 "Patient/RTDoseGrid" "RangeShifter"',
            # DICOM specifies only the thickness and position of the range shifter, not its
            # lateral size. 45 x 45 cm covers the maximum beam deflection of 40 cm at isocenter.
            f"d:Ge/RangeShifter/HLX                = {225:.2f} mm",
            f"d:Ge/RangeShifter/HLY                = {225:.2f} mm",
            f"d:Ge/RangeShifter/HLZ                = {rs.thickness*0.5:.2f} mm",
            's:Ge/RangeShifter/Color              = "Orange"',
            f'd:Ge/RangeShifter/TransZ            = {transz:.2f} mm\n',
            "\n"
        ]
        return "\n".join(lines)

    @staticmethod
    def field_beam_timefeature() -> str:
        lines = [
            "##############################################",
            "###               B  E  A  M               ###",
            "##############################################",
            's:So/Field/Type                      = "Emittance"',
            's:So/Field/Component                 = "BeamPosition"',
            's:So/Field/BeamParticle              = "proton"',
            "d:So/Field/BeamEnergy                = Tf/Energy/Value MeV",
            "u:So/Field/BeamEnergySpread          = Tf/EnergySpread/Value",
            's:So/Field/Distribution              = "BiGaussian"',
            "d:So/Field/SigmaX                    = Tf/SigmaX/Value mm",
            "d:So/Field/SigmaY                    = Tf/SigmaY/Value mm",
            "u:So/Field/SigmaXprime               = Tf/SigmaXprime/Value",
            "u:So/Field/SigmaYprime               = Tf/SigmaYprime/Value",
            "u:So/Field/CorrelationX              = Tf/CorrelationX/Value",
            "u:So/Field/CorrelationY              = Tf/CorrelationY/Value",
            "",
            "i:So/Field/NumberOfHistoriesInRun    = Tf/spotWeight/Value",
            "\n"
        ]
        return "\n".join(lines)

    @staticmethod
    def scorer_setup_dicom(dose_to_water: bool = True, topas_output_path: str = "") -> str:
        lines = [
            "##############################################",
            "###       S C O R E R    S E T U P         ###",
            "##############################################",
        ]
        if dose_to_water:
            lines.append(
                's:Sc/Dose/Quantity                   = "DoseToWater"')
            lines.append('b:Sc/Dose/PreCalculateStoppingPowerRatios = "True"')
        else:
            lines.append(
                's:Sc/Dose/Quantity                   = "DoseToMedium"')
        lines.append(
            's:Sc/Dose/Component                  = "Patient/RTDoseGrid"')
        lines.append('s:Sc/Dose/ReferencedDicomPatient     = "Patient"')
        lines.append('s:Sc/Dose/IfOutputFileAlreadyExists  = "Overwrite"')
        lines.append('s:Sc/Dose/OutputType                 = "DICOM"')
        lines.append(
            f's:Sc/Dose/OutputFile                 = "{topas_output_path}"')
        lines.append('b:Sc/Dose/DICOMOutput32BitsPerPixel  = "F"')
        lines.append('\n')
        return "\n".join(lines)

    @staticmethod
    def scoring_box_x(size: float = 300.0) -> str:
        lines = [
            "##############################################",
            "###       S C O R E R    B O X     X       ###",
            "##############################################",
            's:Ge/ScoringXBox/Parent     = "World"',
            's:Ge/ScoringXBox/Type       = "TsBox"',
            'b:Ge/ScoringXBox/IsParallel = "TRUE"',
            f's:Ge/ScoringXBox/HLX       = {size:.2f} mm',
            f's:Ge/ScoringXBox/HLY       = {10.0:.2f} mm',
            f's:Ge/ScoringXBox/HLZ       = {10.0:.2f} mm',
            f's:Ge/ScoringXBox/XBins     = {size:d}',
            's:Ge/ScoringXBox/YBins     = 1',
            's:Ge/ScoringXBox/ZBins     = 1',
            's:Ge/ScoringXBox/Color      = "green"',
            's:Ge/ScoringXBox/TransX     = 0.0 mm',
            's:Ge/ScoringXBox/TransY     = 0.0 mm',
            's:Ge/ScoringXBox/TransZ     = 0.0 mm',
            "\n"
        ]
        return "\n".join(lines)

    @staticmethod
    def scoring_box_y(size: float = 300.0) -> str:
        lines = [
            "##############################################",
            "###       S C O R E R    B O X     Y       ###",
            "##############################################",
            's:Ge/ScoringYBox/Parent     = "World"',
            's:Ge/ScoringYBox/Type       = "TsBox"',
            'b:Ge/ScoringYBox/IsParallel = "TRUE"',
            f's:Ge/ScoringYBox/HLX       = {10.0:.2f} mm',
            f's:Ge/ScoringYBox/HLY       = {size:.2f} mm',
            f's:Ge/ScoringYBox/HLZ       = {10.0:.2f} mm',
            's:Ge/ScoringYBox/XBins     = 1',
            f's:Ge/ScoringYBox/YBins     = {size:d}',
            's:Ge/ScoringYBox/ZBins     = 1',
            's:Ge/ScoringYBox/Color      = "green"',
            's:Ge/ScoringYBox/TransX     = 0.0 mm',
            's:Ge/ScoringYBox/TransY     = 0.0 mm',
            's:Ge/ScoringYBox/TransZ     = 0.0 mm',
            "\n"
        ]
        return "\n".join(lines)

    @staticmethod
    def scoring_box_z(size: float = 300.0) -> str:
        lines = [
            "##############################################",
            "###       S C O R E R    B O X     Z       ###",
            "##############################################",
            's:Ge/ScoringZBox/Parent     = "World"',
            's:Ge/ScoringZBox/Type       = "TsBox"',
            'b:Ge/ScoringZBox/IsParallel = "TRUE"',
            f's:Ge/ScoringZBox/HLX       = {10.0:.2f} mm',
            f's:Ge/ScoringZBox/HLY       = {10.0:.2f} mm',
            f's:Ge/ScoringZBox/HLZ       = {size:.2f} mm',
            's:Ge/ScoringZBox/XBins     = 1',
            's:Ge/ScoringZBox/YBins     = 1',
            f's:Ge/ScoringZBox/ZBins     = {size:d}',
            's:Ge/ScoringZBox/Color      = "green"',
            's:Ge/ScoringZBox/TransX     = 0.0 mm',
            's:Ge/ScoringZBox/TransY     = 0.0 mm',
            's:Ge/ScoringZBox/TransZ     = 0.0 mm',
            "\n"
        ]
        return "\n".join(lines)

    # here do a XY scoring box with 2D binning in X and Y
    @staticmethod
    def scoring_box_xy(size_x: float = 300.0, size_y: float = 300.0) -> str:
        lines = [
            "##############################################",
            "###       S C O R E R    B O X     XY      ###",
            "##############################################",
            's:Ge/ScoringXYBox/Parent     = "World"',
            's:Ge/ScoringXYBox/Type       = "TsBox"',
            'b:Ge/ScoringXYBox/IsParallel = "TRUE"',
            f's:Ge/ScoringXYBox/HLX       = {size_x:.2f} mm',
            f's:Ge/ScoringXYBox/HLY       = {size_y:.2f} mm',
            f's:Ge/ScoringXYBox/HLZ       = {10.0:.2f} mm',
            f's:Ge/ScoringXYBox/XBins     = {size_x:d}',
            f's:Ge/ScoringXYBox/YBins     = {size_y:d}',
            's:Ge/ScoringXYBox/ZBins     = 1',
            's:Ge/ScoringXYBox/Color      = "green"',
            's:Ge/ScoringXYBox/TransX     = 0.0 mm',
            's:Ge/ScoringXYBox/TransY     = 0.0 mm',
            's:Ge/ScoringXYBox/TransZ     = 0.0 mm',
            "\n"
        ]
        return "\n".join(lines)

    @staticmethod
    def scoring_box_xz(size_x: float = 300.0, size_z: float = 300.0) -> str:
        lines = [
            "##############################################",
            "###       S C O R E R    B O X     XZ      ###",
            "##############################################",
            's:Ge/ScoringXZBox/Parent     = "World"',
            's:Ge/ScoringXZBox/Type       = "TsBox"',
            'b:Ge/ScoringXZBox/IsParallel = "TRUE"',
            f's:Ge/ScoringXZBox/HLX       = {size_x:.2f} mm',
            f's:Ge/ScoringXZBox/HLY       = {10.0:.2f} mm',
            f's:Ge/ScoringXZBox/HLZ       = {size_z:.2f} mm',
            f's:Ge/ScoringXZBox/XBins     = {size_x:d}',
            's:Ge/ScoringXZBox/YBins     = 1',
            f's:Ge/ScoringXZBox/ZBins     = {size_z:d}',
            's:Ge/ScoringXZBox/Color      = "green"',
            's:Ge/ScoringXZBox/TransX     = 0.0 mm',
            's:Ge/ScoringXZBox/TransY     = 0.0 mm',
            's:Ge/ScoringXZBox/TransZ     = 0.0 mm',
            "\n"
        ]
        return "\n".join(lines)

    @staticmethod
    def scoring_box_yz(size_y: float = 300.0, size_z: float = 300.0) -> str:
        lines = [
            "##############################################",
            "###       S C O R E R    B O X     YZ      ###",
            "##############################################",
            's:Ge/ScoringYZBox/Parent     = "World"',
            's:Ge/ScoringYZBox/Type       = "TsBox"',
            'b:Ge/ScoringYZBox/IsParallel = "TRUE"',
            f's:Ge/ScoringYZBox/HLX       = {10.0:.2f} mm',
            f's:Ge/ScoringYZBox/HLY       = {size_y:.2f} mm',
            f's:Ge/ScoringYZBox/HLZ       = {size_z:.2f} mm',
            's:Ge/ScoringYZBox/XBins     = 1',
            f's:Ge/ScoringYZBox/YBins     = {size_y:d}',
            f's:Ge/ScoringYZBox/ZBins     = {size_z:d}',
            's:Ge/ScoringYZBox/Color      = "green"',
            's:Ge/ScoringYZBox/TransX     = 0.0 mm',
            's:Ge/ScoringYZBox/TransY     = 0.0 mm',
            's:Ge/ScoringYZBox/TransZ     = 0.0 mm',
            "\n"
        ]
        return "\n".join(lines)

    @staticmethod
    def scoring_water_phantom(component: str, outpath: Path) -> str:
        """ Generate the scoring section for the water phantom.
        Args:
            component (str): The component to score, e.g., "ScoringYBox".
            outpath (Path): The output file path for the scoring data.
        """
        lines = [
            "##############################################",
            "###       S C O R E R    W A T E R         ###",
            "##############################################",
            's:Sc/Scoring_WaterPhantom/Quantity                   = "DoseToWater"',
            f's:Sc/Scoring_WaterPhantom/Component                  = "{component}"',
            's:Sc/Scoring_WaterPhantom/IfOutputFileAlreadyExists  = "Overwrite"',
            's:Sc/Scoring_WaterPhantom/PropagateToChildren        = "True"',
            f's:Sc/Scoring_WaterPhantom/OutputFile                 = "{outpath}"',
            "\n"
        ]
        return "\n".join(lines)

    @staticmethod
    def geometry_isocenter_scorer() -> str:
        """
        Self-contained water box + dose scorer centred at the IEC isocenter (World origin).
        Used in test_mode to verify that the beam actually reaches the isocenter.
        The scorer writes a CSV file named 'isocenter_scorer.csv' (TOPAS adds the .csv extension).
        """
        lines = [
            "##############################################",
            "###   I S O C E N T E R   S C O R E R      ###",
            "##############################################",
            's:Ge/IsoBox/Type                     = "TsBox"',
            's:Ge/IsoBox/Parent                   = "World"',
            's:Ge/IsoBox/Material                 = "G4_WATER"',
            "d:Ge/IsoBox/HLX                      = 200 mm",
            "d:Ge/IsoBox/HLY                      = 200 mm",
            "d:Ge/IsoBox/HLZ                      = 200 mm",
            "d:Ge/IsoBox/TransX                   = 0.0 mm",
            "d:Ge/IsoBox/TransY                   = 0.0 mm",
            "d:Ge/IsoBox/TransZ                   = 0.0 mm",
            's:Sc/IsoScore/Quantity               = "DoseToWater"',
            's:Sc/IsoScore/Component              = "IsoBox"',
            's:Sc/IsoScore/OutputType             = "csv"',
            's:Sc/IsoScore/IfOutputFileAlreadyExists = "Overwrite"',
            's:Sc/IsoScore/OutputFile             = "isocenter_scorer"',
            "\n"
        ]
        return "\n".join(lines)
