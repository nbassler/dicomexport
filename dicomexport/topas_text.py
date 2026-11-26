import datetime
import getpass  # used for recording the user who generated the file
import logging
import re
from collections.abc import Sequence
from pathlib import Path
from typing import Optional, Tuple

from dicomexport.config import Include
from dicomexport.material_override import MaterialOverride
from dicomexport.model_plan import Field
from dicomexport.model_ct import CTModel
from dicomexport.model_rtstruct import RTStruct
from dicomexport.topas_export_options import DEFAULTS
from dicomexport.topas_version import EMITTANCE_PARAMETER_NAMES_SINCE, TopasVersion
from dicomexport.__version__ import __version__

logger = logging.getLogger(__name__)


def _range_shifter_material_name(base_material: str) -> str:
    """Name for the density-adjusted variant of ``base_material``.

    TOPAS reserves the ``G4_`` prefix for the NIST database, so a variant of ``G4_LEXAN``
    cannot keep it; anything but letters and digits is dropped because the name is a
    parameter path segment.
    """
    stem = re.sub(r"[^A-Za-z0-9]", "", base_material[3:] if base_material.startswith("G4_") else base_material)
    return f"RangeShifter{stem or 'Material'}"


# Air padding added around everything that must fit inside the world volume [mm].
# An oversized world is cheap and is more correct for out-of-field dosimetry: particles
# leaving the world are killed rather than allowed to scatter back into the patient.
WORLD_MARGIN = 500.0


class TopasText:
    @staticmethod
    def header(field: Field, nstat_scale: float, nstat: int,
               spot_mode: str = DEFAULTS.spot_mode, simulated_histories: Optional[int] = None,
               layout: Optional[dict] = None) -> str:
        """File header. Its "# KEY: value" lines are read by downstream tools (pregdos).

        In the header, a history is always one primary proton:
          REQUESTED_HISTORIES  what -N asked for
          SIMULATED_HISTORIES  what TOPAS actually simulates: the sum of the rounded spot
                               weights. Plan scaling divides by this, not by REQUESTED.
        SPOT_MODE says how TOPAS steps through the spots (issue #88). ``layout`` adds:
          SPOTS                spots simulated
          RUNS                 what TOPAS's "Run: N" counts: in sources mode the number of
                               identical batches (issue #121), otherwise SPOTS
          EVENTS_PER_RUN       sources mode only: events in each run, each holding one proton
                               from every spot still active. TOPAS's log calls these
                               "History: N" and its Standard_Deviation is per event.
        """
        lines = [
            f"# Topas input file for field {field.number}",
            '# ' + '-' * 40,
            f"# BEAM_NUMBER: {field.number}",
            f"# BEAM_NAME: {field.name}",
            f"# SOP_INSTANCE_UID {field.sop_instance_uid}",
            "# ",
            f"# TOTAL_NUMBER_OF_PARTICLES: {field.n_particles:.0f}",
            f"# TOTAL_MU: {field.cum_mu:.2f}",
            f"# REQUESTED_HISTORIES: {nstat:.0f}",
        ]
        if simulated_histories is not None:
            lines.append(f"# SIMULATED_HISTORIES: {simulated_histories}")
        lines += [
            f"# PARTICLE_SCALING: {nstat_scale:.2f}",
            "# ",
            f"# SPOT_MODE: {spot_mode}",
        ]
        for key, value in (layout or {}).items():
            lines.append(f"# {key}: {value}")
        lines.append("#\n")
        return "\n".join(lines)

    @staticmethod
    def header2(sources: Optional[Sequence[tuple[str, str]]] = None) -> str:
        """Generation date, user and version, and the data files the export used.

        ``sources`` are (key, value) pairs written as "# KEY: value" lines, like those of
        header(), for downstream tools (issue #112): CONFIG_DIR, BEAM_MODEL,
        RANGE_SHIFTER_CATALOG, and one INCLUDE or INCLUDE_INLINE per included file.
        """

        lines = [
            f"# Generated {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')} by user '{getpass.getuser()}'",
            f"# using dicomexport {__version__}",
            "# https://github.com/nbassler/dicomexport",
        ]
        lines += [f"# {key}: {value}" for key, value in (sources or [])]
        lines.append("#\n")

        return "\n".join(lines)

    @staticmethod
    def includes(includes: Sequence[Include]) -> str:
        """The files given with -s (an includeFile line each) and -S (pasted), in that order.

        Between the marker lines are the original UTF-8 bytes and one framing LF before the
        end marker. The checksum covers the original bytes.
        """
        lines = [
            "##############################################",
            "###          INCLUDED FILES                ###",
            "##############################################",
        ]
        for inc in includes:
            if inc.inline:
                assert inc.text is not None
                lines.append(f"# BEGIN INCLUDE_INLINE: {inc.path} sha256={inc.sha256}")
                lines.append(inc.text)
                lines.append(f"# END INCLUDE_INLINE: {inc.path}")
            else:
                lines.append(f"includeFile                          = {inc.path}")
        lines.append("\n")
        return "\n".join(lines)

    @staticmethod
    def include_sources(includes: Sequence[Include]) -> list[tuple[str, str]]:
        """The header lines naming each included file, as (key, value) pairs for header2()."""
        return [("INCLUDE_INLINE", f"{inc.path} sha256={inc.sha256}") if inc.inline else ("INCLUDE", inc.path)
                for inc in includes]

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
    def setup(show_history_interval: int = 100000, nr_threads: int = DEFAULTS.nr_threads) -> str:
        """
        Generate the TOPAS setup section.

        show_history_interval: Interval at which the history count is shown.
        nr_threads: value for Ts/NumberOfThreads. 0 means all cores, -1 all but one,
            and N > 0 exactly N. TOPAS resolves non-positive values as
            `cores + nr_threads` (TsSequenceManager.cc), on the machine that RUNS the
            file, so the choice is safe to export on one node and run on another.
            A non-MT TOPAS build ignores any value other than 1.
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
    def material_overrides(overrides: Sequence[MaterialOverride], rtstruct_path: Path) -> str:
        """The structures whose material replaces the CT conversion (--material-override, #94).

        TOPAS gives the first listed structure precedence where structures overlap. It is
        told which RTSTRUCT to use, the one whose names dicomexport checked; otherwise it
        takes the first RTSTRUCT it finds in DicomDirectory. The path is written verbatim
        with POSIX separators, like DicomDirectory (#63).
        """
        def vector(values: list) -> str:
            return f"{len(values)} " + " ".join(f'"{v}"' for v in values)

        lines = [
            "##############################################",
            "###   M A T E R I A L   O V E R R I D E S  ###",
            "##############################################",
            f's:Ge/Patient/DicomRTStructFile              = "{rtstruct_path.as_posix()}"',
            f"sv:Ge/Patient/MaterialByRTStructNames       = {vector([o.topas_name for o in overrides])}",
            f"sv:Ge/Patient/MaterialByRTStructMaterials   = {vector([o.material for o in overrides])}",
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
    def nozzle_transz(beam_model_position: float, beam_direction: int) -> str:
        """TransZ of the nozzle group, as written: +bmp on the pos-z side, -bmp on neg-z (#66)."""
        return f"{beam_model_position}" if beam_direction == 1 else f"-{beam_model_position}"

    @staticmethod
    def source_parameter_prefix(topas_version: TopasVersion = DEFAULTS.topas_version) -> str:
        """Prefix of the particle, energy and energy spread parameters of an emittance source.

        They are inherited from TsVGenerator. OpenTOPAS 4.2 renamed them for non-beam
        sources: there BeamParticle/BeamEnergy/BeamEnergySpread still work but warn on every
        run (issue #65). TOPAS 3.9 to 4.1 only know the Beam* names and abort on the
        Emittance* ones (issue #95). The parameters the emittance generator reads itself --
        Distribution, SigmaX/Y, SigmaXprime/Yprime, CorrelationX/Y -- were never renamed.
        """
        return "Emittance" if topas_version >= EMITTANCE_PARAMETER_NAMES_SINCE else "Beam"

    @staticmethod
    def geometry_beam_position_timefeature(beam_model_position: float = 500.0,
                                           beam_direction: int = DEFAULTS.beam_direction) -> str:
        # RotY is pre-computed per spot into the BeamPositionRotY time feature.
        # TOPAS rotation parameters are passive (TsVGeometryComponent composes
        # fRotRelToWorld = R_child * R_parent and the local->world map uses the inverse),
        # so the IEC-correct nozzle sits at gantry-local -Z emitting along its +Z:
        #   neg-Z (beam_direction=-1): TransZ=-bmp, RotY=-angx   (IEC 61217, default).
        #     Verified against OpenTOPAS 4.2.3: gantry 0 enters an HFS patient anterior,
        #     gantry 90 from the patient's left (issue #66).
        #   pos-Z (beam_direction=1):  TransZ=+bmp, RotY=180-angx. Source mirrored to
        #     gantry+180°; only for non-patient research setups.
        transz = TopasText.nozzle_transz(beam_model_position, beam_direction)
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
    def geometry_range_shifter(myfield: Field, beam_direction: int = DEFAULTS.beam_direction) -> str:
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
        if not rs.material:
            # A slab has to be made of something. Without a material the TsBox would be
            # handed Material = "None", which TOPAS cannot resolve -- the export would
            # look complete and then fail at run time. The catalog loader rejects an
            # empty material outright, so this is defence in depth against a hand-built
            # catalog; refuse the geometry the same way a zero-thickness device is.
            logger.warning(
                "Field %d: range shifter %r has no material; emitting no geometry.",
                myfield.number, rs.id)
            return ""
        transz = beam_direction * (rs.isocenter_distance + rs.thickness * 0.5)

        lines = [
            "##############################################",
            "###        R A N G E   S H I F T E R       ###",
            "##############################################",
        ]

        material = rs.material
        if rs.density is not None:
            # A TsBox takes a material, and a TOPAS material carries its own density, so a
            # stated density can only be applied by defining a variant material. A
            # single-component BuildFromMaterials is the documented way to say "this
            # composition, that density" -- TOPAS has no parameter that rescales the
            # density of a material in place.
            #
            # The variant inherits the composition of the base material but NOT its mean
            # excitation energy: Geant4 recomputes I from the elements, which for Lexan
            # gives 71.71 eV against the tabulated 73.1 (measured with TOPAS 4.2.p3).
            # That is a ~0.3% shift in stopping power -- a third of the size of the 1%
            # density change being modelled, and in the same direction, so leaving it
            # alone would quietly eat a quarter of the effect. Carry I over explicitly.
            material = _range_shifter_material_name(rs.material)
            lines += [
                f'{f"b:Ma/{material}/BuildFromMaterials":<36} = "True"',
                f'{f"sv:Ma/{material}/Components":<36} = 1 "{rs.material}"',
                f'{f"uv:Ma/{material}/Fractions":<36} = 1 1.0',
                f'{f"d:Ma/{material}/Density":<36} = {rs.density:.4f} g/cm3',
            ]
            if rs.material.startswith("G4_"):
                # A NIST material has no Ma/ parameters to point at, so there is nothing
                # to reference and no way to recover I from here. Say so rather than
                # emitting a material that looks right and stops slightly too hard.
                logger.warning(
                    "Field %d: range shifter %r overrides the density of NIST material %r. Geant4 will "
                    "recompute its mean excitation energy from the elements instead of using the NIST "
                    "value, which shifts stopping power by ~1%%. Define the material yourself with an "
                    "explicit MeanExcitationEnergy and name that in the catalog instead.",
                    myfield.number, rs.id, rs.material)
            else:
                # A TOPAS-defined material carries its I as an ordinary parameter, so the
                # variant can point at it and stay correct if the base is ever revised.
                lines.append(
                    f'{f"d:Ma/{material}/MeanExcitationEnergy":<36} = 1.0 * Ma/{rs.material}/MeanExcitationEnergy eV')
            lines.append("")

        lines += [
            's:Ge/RangeShifter/Parent             = "Gantry"',
            's:Ge/RangeShifter/Type               = "TsBox"',
            f's:Ge/RangeShifter/Material           = "{material}"',
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
    def field_beam_timefeature(topas_version: TopasVersion = DEFAULTS.topas_version) -> str:
        prefix = TopasText.source_parameter_prefix(topas_version)
        lines = [
            "##############################################",
            "###               B  E  A  M               ###",
            "##############################################",
            's:So/Field/Type                      = "Emittance"',
            's:So/Field/Component                 = "BeamPosition"',
            f'{f"s:So/Field/{prefix}Particle":<36} = "proton"',
            f'{f"d:So/Field/{prefix}Energy":<36} = Tf/Energy/Value MeV',
            f'{f"u:So/Field/{prefix}EnergySpread":<36} = Tf/EnergySpread/Value',
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
    def scorer_setup_dicom(dose_to_water: bool = True, topas_output_path: str = "",
                           dose_cube_16bit: bool = DEFAULTS.dose_cube_16bit,
                           dlet: bool = DEFAULTS.dlet, tlet: bool = DEFAULTS.tlet) -> str:
        """DICOM dose scorer on the RTDOSE grid.

        dose_cube_16bit: write the cube with 16 instead of 32 bits per pixel. TOPAS scales
            the field's peak to the largest stored value and truncates on the cast
            (TsVBinnedScorer.cc), so at 16 bits every voxel below ~1.5e-5 of the peak is
            written as 0, which can remove low-level out-of-field dose. 32 bits only doubles the file
            size (issue #111).
        dlet, tlet: also score dose- and track-averaged proton LET on the same grid, see
            let_scorer_dicom().
        """
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
        bits32 = "F" if dose_cube_16bit else "T"
        lines.append(f'b:Sc/Dose/DICOMOutput32BitsPerPixel  = "{bits32}"')
        lines.append('')
        if dlet:
            lines.append(TopasText.let_scorer_dicom("LETd", "Dose", topas_output_path))
        if tlet:
            lines.append(TopasText.let_scorer_dicom("LETt", "Track", topas_output_path))
        lines.append('\n')
        return "\n".join(lines)

    @staticmethod
    def let_scorer_dicom(name: str, weight_by: str, topas_output_path: str = "") -> str:
        """TOPAS's built-in ProtonLET scorer on the RTDOSE grid, written as a DICOM cube.

        The known limits of TsScoreProtonLET (OpenTOPAS 4.2.3) are documented in the README:
        only proton steps are scored, the value is dE/dx / density of the voxel's own
        material (MeV/mm/(g/cm3), no conversion to water), and with UsePreStepLookup the
        electronic stopping power at the pre-step energy is used, so the result depends on
        the step length and with it on the voxel size.

        UsePreStepLookup is set for both weightings: it is the less noisy variant. TOPAS
        aborts if MaxScoredLET or NeglectSecondariesBelowDensity is set together with it,
        so neither is written. OutputAfterRun is not set, so with batches the LET still
        accumulates over all runs and is written once, correctly weighted.

        The cube is always 32 bits per pixel: LET spikes would set the scale, and at 16
        bits low values in the field would be written as 0.

        Units and the DICOM header, a deliberate choice: the series is labelled keV/um, not
        MeV/mm/(g/cm3). The two are numerically the same at density 1 (1 MeV/mm = 1 keV/um),
        and keV/um is what the clinical users read. dicomexport does not try to make the
        cube a valid dose: TOPAS writes DoseUnits only for a Gy quantity
        (TsVBinnedScorer.cc), so the LET cube has no DoseUnits, DoseType or
        DoseSummationType, and a TOPAS input file cannot set them. Planning systems such as
        Eclipse load only Gy cubes, so clinics import LET as a "Gy" cube that is read as
        keV/um. The README describes that import (the clinical RTDOSE as a template, as in
        PregDos); it is left to the user on purpose, because dicomexport writes TOPAS input
        and does no postprocessing.
        SeriesDescription is the one label TOPAS lets us set, so it says "not dose".
        """
        out = f"{topas_output_path}_{name}" if topas_output_path else name
        sc = f"Sc/{name}"
        return "\n".join([
            f"# {name}: TOPAS ProtonLET, protons only, mass LET in the voxel's own material,",
            "# in MeV/mm/(g/cm3), i.e. keV/um at density 1. Not converted to water. See README.",
            '# TOPAS writes no DoseUnits for a non-dose quantity; the description says what it is.',
            f's:{sc}/SeriesDescription          = "{name} [keV/um] - not dose"',
            f's:{sc}/Quantity                   = "ProtonLET"',
            f's:{sc}/WeightBy                   = "{weight_by}"',
            f'b:{sc}/UsePreStepLookup           = "True"',
            f's:{sc}/Component                  = "Patient/RTDoseGrid"',
            f's:{sc}/ReferencedDicomPatient     = "Patient"',
            f's:{sc}/IfOutputFileAlreadyExists  = "Overwrite"',
            f's:{sc}/OutputType                 = "DICOM"',
            f's:{sc}/OutputFile                 = "{out}"',
            f'b:{sc}/DICOMOutput32BitsPerPixel  = "T"',
            '',
        ])

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
