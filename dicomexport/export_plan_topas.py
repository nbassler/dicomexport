import logging
import numpy as np

from dicomexport.model_plan import Field
from dicomexport.beam_model import BeamModel
from dicomexport.topas_text import TopasText

logger = logging.getLogger(__name__)


class TopasPlan:
    @staticmethod
    def generate(myfield: Field, bm: BeamModel,
                 nstat=100000, test_mode=False, beam_direction: int = 1) -> str:
        """
        Export the field to a topas input file.
        """
        logger.debug(
            f"Generating Topas input for field {myfield.number} with nstat={nstat}")

        # calculate scaling factor for number of particles
        nstat_scale = TopasPlan.calculate_scaling_factor(myfield, nstat)

        # show some information about the field
        TopasPlan.show_plan_data(myfield, bm, nstat=nstat)

        # build output lines instead of writing to file
        lines = []
        lines.append(TopasText.header(myfield, nstat_scale, nstat))
        lines.append(TopasText.header2())

        lines.append(TopasText.variables(myfield))
        if test_mode:
            # No patient in test mode: the world only has to hold the beam line and the IsoBox.
            world_hl = TopasText.world_half_lengths(beam_reach=bm.beam_model_position)
            lines.append(TopasText.setup())
            lines.append(TopasText.world_setup(world_hl))
            lines.append(TopasText.geometry_gantry())
            lines.append(TopasText.geometry_couch())
            lines.append(TopasText.geometry_dcm_to_iec())
            lines.append(TopasText.geometry_isocenter_scorer())
        lines.append(TopasText.geometry_beam_position_timefeature(
            bm.beam_model_position, beam_direction=beam_direction))
        lines.append(TopasText.geometry_range_shifter(myfield, beam_direction=beam_direction))
        lines.append(TopasText.field_beam_timefeature())

        lines.append(TopasPlan.time_features_string(
            myfield, bm, nstat, beam_direction=beam_direction))

        topas_text = "".join(lines)
        return topas_text

    @staticmethod
    def time_features_string(myfield: Field, bm: BeamModel, nstat: int = int(1e6),
                             beam_direction: int = 1) -> str:
        """
        Build the TIME FEATURES section for a Topas file and return as a string.
        """

        n_spots = myfield.n_spots
        times = np.zeros(n_spots)
        energies_real = np.zeros(n_spots)  # actual energies at the beam model position
        espreads = np.zeros(n_spots)
        posx = np.zeros(n_spots)
        angx = np.zeros(n_spots)
        posy = np.zeros(n_spots)
        angy = np.zeros(n_spots)
        sigx = np.zeros(n_spots)
        sigy = np.zeros(n_spots)
        sigxp = np.zeros(n_spots)
        sigyp = np.zeros(n_spots)
        corx = np.zeros(n_spots)
        cory = np.zeros(n_spots)
        nparts = np.zeros(n_spots)

        sad_x, sad_y = myfield.sad

        # Defence in depth for issue #79: a zero SAD used to reach the divisions below
        # and emit inf spot positions in a file that otherwise looked fine. The plan
        # importer now refuses to produce one, so this should be unreachable from
        # DICOM -- but fail loudly rather than write inf.
        # np.isfinite is required, not just a positivity test: nan fails "<= 0.0" and
        # inf passes it, yet both yield nan geometry downstream (issue #79).
        if not all(np.isfinite(v) and v > 0.0 for v in (sad_x, sad_y)):
            raise ValueError(
                f"Field {myfield.number}: source-to-axis distance must be finite and "
                f"positive, got {sad_x} / {sad_y} mm. Cannot compute spot positions "
                f"or angles.")

        _spot_index = 0
        for mylayer in myfield.layers:

            # layer.espread is an absolute energy spread in MeV at the beam model position;
            # convert it to a relative (%) spread for TOPAS (which expects relative energy spread).
            espread_percent = (mylayer.espread / mylayer.energy_measured) * 100.0  # [%]

            for spot in mylayer.spots:
                times[_spot_index] = _spot_index + 1
                energies_real[_spot_index] = mylayer.energy_measured  # actual energies
                espreads[_spot_index] = espread_percent
                posx[_spot_index] = spot.x * \
                    (sad_x - bm.beam_model_position) / sad_x
                angx[_spot_index] = np.degrees(np.arctan(spot.x / sad_x))
                posy[_spot_index] = spot.y * \
                    (sad_y - bm.beam_model_position) / sad_y
                angy[_spot_index] = np.degrees(np.arctan(spot.y / sad_y))
                sigx[_spot_index] = bm.f_sx(mylayer.energy_nominal)
                sigy[_spot_index] = bm.f_sy(mylayer.energy_nominal)
                sigxp[_spot_index] = bm.f_divx(mylayer.energy_nominal)
                sigyp[_spot_index] = bm.f_divy(mylayer.energy_nominal)
                corx[_spot_index] = bm.f_corx(mylayer.energy_nominal)
                cory[_spot_index] = bm.f_cory(mylayer.energy_nominal)
                nparts[_spot_index] = spot.mu * mylayer.mu_to_part_coef
                _spot_index += 1

        nstat_scale = TopasPlan.calculate_scaling_factor(myfield, nstat)
        inv_nstat_scale = 1.0 / nstat_scale

        lines = []
        lines.append("##############################################\n")
        lines.append("###  T  I  M  E    F  E  A  T  U  R  E  S  ###\n")
        lines.append("##############################################\n\n")

        lines.append(f"i:Tf/NumberOfSequentialTimes         = {n_spots}\n")
        lines.append(f"d:Tf/TimelineStart                   = {1} s\n")
        lines.append(
            f"d:Tf/TimelineEnd                     = {n_spots+1} s\n\n")

        # Pre-compute BeamPositionRotY (RotY of the beam nozzle group) per spot.
        # TOPAS rotation parameters are passive (the local->world map uses the inverse
        # matrix), so the IEC-correct nozzle sits at gantry-local -Z with no 180° flip:
        #   neg-Z (beam_direction=-1): -angx          (IEC 61217, default; issue #66)
        #   pos-Z (beam_direction=1):  180.0 - angx  (source mirrored to gantry+180°,
        #                                             non-patient research setups only)
        if beam_direction == 1:
            beam_pos_roty = 180.0 - angx
        else:
            beam_pos_roty = -angx

        lines.append(_topas_array(times, energies_real, "Energy", "f", 3, "MeV"))
        lines.append(_topas_array(times, espreads, "EnergySpread", "f", 5, ""))
        lines.append(_topas_array(times, posx, "spotPositionX", "f", 2, "mm"))
        lines.append(_topas_array(times, angx, "spotAngleX", "f", 3, "deg"))
        lines.append(_topas_array(times, beam_pos_roty, "BeamPositionRotY", "f", 3, "deg"))
        lines.append(_topas_array(times, posy, "spotPositionY", "f", 2, "mm"))
        lines.append(_topas_array(times, angy, "spotAngleY", "f", 3, "deg"))
        lines.append(_topas_array(times, sigx, "SigmaX", "f", 5, "mm"))
        lines.append(_topas_array(times, sigy, "SigmaY", "f", 5, "mm"))
        lines.append(_topas_array(times, sigxp, "SigmaXprime", "f", 5, ""))
        lines.append(_topas_array(times, sigyp, "SigmaYprime", "f", 5, ""))
        lines.append(_topas_array(times, corx, "CorrelationX", "f", 5, ""))
        lines.append(_topas_array(times, cory, "CorrelationY", "f", 5, ""))
        lines.append(_topas_array(times, nparts *
                     inv_nstat_scale, "spotWeight", "f", 0, ""))

        return "".join(lines)

    @staticmethod
    def calculate_scaling_factor(myfield: Field, nstat: int = int(1e6)) -> float:
        """
        Calculate the scaling factor for the number of particles in the field.
        """
        total_particles = myfield.n_particles
        nstat_scale = 1.0 / (nstat / total_particles) * myfield.scaling
        return nstat_scale

    @staticmethod
    def show_plan_data(myfield: Field, bm: BeamModel, nstat: int = int(1e6)) -> None:
        sad_x, sad_y = myfield.sad
        nstat_scale = TopasPlan.calculate_scaling_factor(myfield, nstat)

        # show some information about the field
        logger.info(
            f"Beam model position:          {bm.beam_model_position} mm upstream of isocenter")
        logger.info(
            f"SAD X/Y:                      {sad_x:.2f} mm / {sad_y:.2f} mm")
        logger.info(
            f"Proton budget for this plan:  {myfield.n_particles:.3e} protons")
        logger.info(f"Requested histories:          {nstat:.3e}")
        logger.info(f"Scaling factor:               {nstat_scale:.4e}")
        logger.info(f"Number of spots:              {myfield.n_spots}")
        logger.info(f"Number of energy layers:      {myfield.n_layers}")
        logger.debug(
            f"Beam Meterset Weight:         {myfield.meterset_weight_final:.2f}")
        logger.info(f"Beam Meterset:                {myfield.cum_mu:.2f} MU")


def _topas_array(time_arr: np.ndarray, arr: np.ndarray, name: str, fmt: str = "f", precision: int = 0, unit=""):
    """generate string of time data."""
    s = ""
    n_spots = arr.size
    s += f"s:Tf/{name}/Function                 = \"Step\"\n"
    if unit == "":
        _pre = "uv"
    else:
        _pre = "dv"

    _ft = " ".join(map(str, time_arr.astype(int)))
    _fa = " ".join(f"{x:.{precision}{fmt}}" for x in arr)
    s += f"dv:Tf/{name}/Times                   = {n_spots} {_ft} s\n"
    s += f"{_pre}:Tf/{name}/Values                   = {arr.size} {_fa} {unit}\n"
    s += "\n\n"
    return s
