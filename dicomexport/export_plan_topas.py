import logging
from dataclasses import dataclass
from typing import Optional

import numpy as np

from dicomexport.model_plan import Field
from dicomexport.beam_model import BeamModel
from dicomexport.topas_text import TopasText
from dicomexport.topas_export_options import DEFAULTS, TopasExportOptions

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SpotTable:
    """Per-spot TOPAS beam parameters, one array element per spot in delivery order."""
    layer: np.ndarray    # 1-based energy layer number
    energy: np.ndarray   # MeV, at the beam model position
    espread: np.ndarray  # relative energy spread [%]
    posx: np.ndarray     # mm, at the beam model plane
    angx: np.ndarray     # deg
    posy: np.ndarray     # mm
    angy: np.ndarray     # deg
    roty: np.ndarray     # deg, RotY of the nozzle group (includes the nozzle side)
    sigx: np.ndarray     # mm
    sigy: np.ndarray     # mm
    sigxp: np.ndarray    # rad
    sigyp: np.ndarray    # rad
    corx: np.ndarray
    cory: np.ndarray
    weight: np.ndarray   # primaries to simulate, scaled to nstat; not yet rounded

    @property
    def n_spots(self) -> int:
        return int(self.weight.size)


class TopasPlan:
    @staticmethod
    def generate(myfield: Field, bm: BeamModel, test_mode: bool = False,
                 opts: TopasExportOptions = DEFAULTS) -> str:
        """
        Export the field to a topas input file.
        """
        logger.debug(
            f"Generating Topas input for field {myfield.number} with nstat={opts.nstat}")

        # calculate scaling factor for number of particles
        nstat_scale = TopasPlan.calculate_scaling_factor(myfield, opts.nstat)

        # show some information about the field
        TopasPlan.show_plan_data(myfield, bm, nstat=opts.nstat)

        # Every spot's beam parameters, built once and used by every section below.
        table = TopasPlan.spot_table(myfield, bm, opts.nstat, opts.beam_direction)

        # build output lines instead of writing to file
        lines = []
        lines.append(TopasPlan.header(myfield, table, opts, nstat_scale))
        lines.append(TopasText.header2())

        lines.append(TopasText.variables(myfield))
        if test_mode:
            # No patient in test mode: the world only has to hold the beam line and the IsoBox.
            world_hl = TopasText.world_half_lengths(beam_reach=bm.beam_model_position)
            lines.append(TopasText.setup(nr_threads=opts.nr_threads,
                                         **TopasPlan._setup_kwargs(table, opts)))
            lines.append(TopasText.world_setup(world_hl))
            lines.append(TopasText.geometry_gantry())
            lines.append(TopasText.geometry_couch())
            lines.append(TopasText.geometry_dcm_to_iec())
            lines.append(TopasText.geometry_isocenter_scorer())
        if opts.spot_mode == "sources":
            lines.append(TopasText.geometry_range_shifter(myfield, beam_direction=opts.beam_direction))
            lines.append(TopasPlan.sources_string(
                myfield, bm, opts.nstat, beam_direction=opts.beam_direction,
                topas_version=opts.topas_version, table=table))
        else:
            lines.append(TopasText.geometry_beam_position_timefeature(
                bm.beam_model_position, beam_direction=opts.beam_direction))
            lines.append(TopasText.geometry_range_shifter(myfield, beam_direction=opts.beam_direction))
            lines.append(TopasText.field_beam_timefeature(topas_version=opts.topas_version))

            lines.append(TopasPlan.time_features_string(
                myfield, bm, opts.nstat, beam_direction=opts.beam_direction, table=table))

        topas_text = "".join(lines)
        return topas_text

    @staticmethod
    def _setup_kwargs(table: Optional["SpotTable"], opts: TopasExportOptions) -> dict:
        """Setup-block overrides for the spot mode: sources mode reports progress per event."""
        if opts.spot_mode == "sources" and table is not None:
            return {"show_history_interval": TopasPlan.history_interval(table)}
        return {}

    @staticmethod
    def spot_table(myfield: Field, bm: BeamModel, nstat: int = DEFAULTS.nstat,
                   beam_direction: int = DEFAULTS.beam_direction) -> "SpotTable":
        """
        Per-spot beam parameters at the beam model plane, as TOPAS needs them.

        Both spot modes are written from this one table, so the time-feature and the
        one-source-per-spot file place every spot identically (issue #88).
        """

        n_spots = myfield.n_spots
        layer_index = np.zeros(n_spots, dtype=int)
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
        for _layer_nr, mylayer in enumerate(myfield.layers, start=1):

            # layer.espread is an absolute energy spread in MeV at the beam model position;
            # convert it to a relative (%) spread for TOPAS (which expects relative energy spread).
            espread_percent = (mylayer.espread / mylayer.energy_measured) * 100.0  # [%]
            # The beam model depends on the layer energy only: evaluate it once per layer.
            e_nom = mylayer.energy_nominal
            optics = (bm.f_sx(e_nom), bm.f_sy(e_nom), bm.f_divx(e_nom), bm.f_divy(e_nom),
                      bm.f_corx(e_nom), bm.f_cory(e_nom))

            for spot in mylayer.spots:
                layer_index[_spot_index] = _layer_nr
                energies_real[_spot_index] = mylayer.energy_measured  # actual energies
                espreads[_spot_index] = espread_percent
                posx[_spot_index] = spot.x * \
                    (sad_x - bm.beam_model_position) / sad_x
                angx[_spot_index] = np.degrees(np.arctan(spot.x / sad_x))
                posy[_spot_index] = spot.y * \
                    (sad_y - bm.beam_model_position) / sad_y
                angy[_spot_index] = np.degrees(np.arctan(spot.y / sad_y))
                (sigx[_spot_index], sigy[_spot_index], sigxp[_spot_index], sigyp[_spot_index],
                 corx[_spot_index], cory[_spot_index]) = optics
                nparts[_spot_index] = spot.mu * mylayer.mu_to_part_coef
                _spot_index += 1

        # Defence in depth, as for the SAD above: the DICOM importer already refuses negative
        # spot weights, but other plan sources might not, and the spot modes would treat one
        # differently (dropped vs. a negative NumberOfHistoriesInRun).
        if (nparts < 0.0).any():
            raise ValueError(
                f"Field {myfield.number}: {int((nparts < 0.0).sum())} spots have a negative "
                f"weight. Cannot export.")

        nstat_scale = TopasPlan.calculate_scaling_factor(myfield, nstat)

        # RotY of the beam nozzle group per spot.
        # TOPAS rotation parameters are passive (the local->world map uses the inverse
        # matrix), so the IEC-correct nozzle sits at gantry-local -Z with no 180° flip:
        #   neg-Z (beam_direction=-1): -angx          (IEC 61217, default; issue #66)
        #   pos-Z (beam_direction=1):  180.0 - angx  (source mirrored to gantry+180°,
        #                                             non-patient research setups only)
        if beam_direction == 1:
            beam_pos_roty = 180.0 - angx
        else:
            beam_pos_roty = -angx

        return SpotTable(
            layer=layer_index, energy=energies_real, espread=espreads,
            posx=posx, angx=angx, posy=posy, angy=angy, roty=beam_pos_roty,
            sigx=sigx, sigy=sigy, sigxp=sigxp, sigyp=sigyp, corx=corx, cory=cory,
            weight=nparts * (1.0 / nstat_scale))  # same expression as before #88, so rounding is unchanged

    @staticmethod
    def time_features_string(myfield: Field, bm: BeamModel, nstat: int = DEFAULTS.nstat,
                             beam_direction: int = DEFAULTS.beam_direction,
                             table: Optional["SpotTable"] = None) -> str:
        """
        Build the TIME FEATURES section for a Topas file and return as a string.

        Pass the field's ``table`` if it is already built, to avoid building it again.
        """
        t = table if table is not None else TopasPlan.spot_table(myfield, bm, nstat, beam_direction)
        n_spots = t.n_spots
        times = np.arange(1, n_spots + 1, dtype=float)

        lines = []
        lines.append("##############################################\n")
        lines.append("###  T  I  M  E    F  E  A  T  U  R  E  S  ###\n")
        lines.append("##############################################\n\n")

        lines.append(f"i:Tf/NumberOfSequentialTimes         = {n_spots}\n")
        lines.append(f"d:Tf/TimelineStart                   = {1} s\n")
        lines.append(
            f"d:Tf/TimelineEnd                     = {n_spots+1} s\n\n")

        lines.append(_topas_array(times, t.energy, "Energy", "f", 3, "MeV"))
        lines.append(_topas_array(times, t.espread, "EnergySpread", "f", 5, ""))
        lines.append(_topas_array(times, t.posx, "spotPositionX", "f", 2, "mm"))
        lines.append(_topas_array(times, t.angx, "spotAngleX", "f", 3, "deg"))
        lines.append(_topas_array(times, t.roty, "BeamPositionRotY", "f", 3, "deg"))
        lines.append(_topas_array(times, t.posy, "spotPositionY", "f", 2, "mm"))
        lines.append(_topas_array(times, t.angy, "spotAngleY", "f", 3, "deg"))
        lines.append(_topas_array(times, t.sigx, "SigmaX", "f", 5, "mm"))
        lines.append(_topas_array(times, t.sigy, "SigmaY", "f", 5, "mm"))
        lines.append(_topas_array(times, t.sigxp, "SigmaXprime", "f", 5, ""))
        lines.append(_topas_array(times, t.sigyp, "SigmaYprime", "f", 5, ""))
        lines.append(_topas_array(times, t.corx, "CorrelationX", "f", 5, ""))
        lines.append(_topas_array(times, t.cory, "CorrelationY", "f", 5, ""))
        lines.append(_topas_array(times, t.weight, "spotWeight", "f", 0, ""))

        return "".join(lines)

    @staticmethod
    def spot_histories(t: "SpotTable") -> np.ndarray:
        """Histories per spot, rounded exactly as the time feature writes spotWeight (".0f")."""
        return np.array([int(f"{w:.0f}") for w in t.weight], dtype=np.int64)

    @staticmethod
    def sources_string(myfield: Field, bm: BeamModel, nstat: int = DEFAULTS.nstat,
                       beam_direction: int = DEFAULTS.beam_direction,
                       topas_version=DEFAULTS.topas_version,
                       table: Optional["SpotTable"] = None) -> str:
        """
        One Group plus one Emittance source per spot, instead of a time feature (issue #88).

        TOPAS runs as many events as the largest NumberOfHistoriesInRun, and each source
        fires only in events below its own count, so the whole field is one Geant4 run with
        exactly the primaries of the time feature. The time feature runs one run per spot,
        and TOPAS merges every scorer after every run; with a full RTDOSE grid that merge
        dominates the run time.

        The Groups have no solid: they only place and tilt each source, exactly as
        Ge/BeamPosition does per spot in time-feature mode.
        """
        t = table if table is not None else TopasPlan.spot_table(myfield, bm, nstat, beam_direction)
        histories = TopasPlan.spot_histories(t)
        keep = histories > 0
        if not keep.any():
            raise ValueError(
                f"Field {myfield.number}: no spot gets a single history at -N {nstat}. "
                f"Increase -N.")
        if not keep.all():
            # The time feature keeps these spots but runs them with 0 histories, so dropping
            # them delivers the same primaries.
            logger.warning(
                "Field %d: %d of %d spots round to 0 histories at -N %d and are left out "
                "(%.3g of %.3g primaries). Increase -N to keep them.",
                myfield.number, int((~keep).sum()), t.n_spots, nstat,
                float(t.weight[~keep].sum()), float(t.weight.sum()))

        transz = TopasText.nozzle_transz(bm.beam_model_position, beam_direction)
        prefix = TopasText.source_parameter_prefix(topas_version)
        width = max(4, len(str(t.n_spots)))

        def row(key: str, value: str) -> str:
            return f"{key:<44} = {value}"

        lines = [
            "##############################################",
            "###   B E A M :   O N E   S O U R C E      ###",
            "###          P E R   S P O T               ###",
            "##############################################",
            f"# {int(keep.sum())} spots. TOPAS runs {int(histories.max())} events in a single run;",
            "# each spot fires in the events below its NumberOfHistoriesInRun. TOPAS's log",
            "# calls these events \"History: N\": one event holds one proton from every spot",
            "# still active, so it is not one proton.",
            "",
        ]
        layer = None
        for i in np.flatnonzero(keep):
            if t.layer[i] != layer:
                layer = t.layer[i]
                lines.append(f"# Energy layer {layer}: {t.energy[i]:.3f} MeV")
            g = f"Spot{i + 1:0{width}d}"
            p = f"Ge/{g}/"
            s = f"So/{g}/"
            lines += [
                row(f"s:{p}Parent", '"Gantry"'),
                row(f"s:{p}Type", '"Group"'),
                row(f"d:{p}TransX", f"{t.posx[i]:.2f} mm"),
                row(f"d:{p}TransY", f"{-t.posy[i]:.2f} mm"),
                row(f"d:{p}TransZ", f"{transz} mm"),
                row(f"d:{p}RotX", f"{-t.angy[i]:.3f} deg"),
                row(f"d:{p}RotY", f"{t.roty[i]:.3f} deg"),
                row(f"d:{p}RotZ", "0.00 deg"),
                row(f"s:{s}Type", '"Emittance"'),
                row(f"s:{s}Component", f'"{g}"'),
                row(f"s:{s}{prefix}Particle", '"proton"'),
                row(f"d:{s}{prefix}Energy", f"{t.energy[i]:.3f} MeV"),
                row(f"u:{s}{prefix}EnergySpread", f"{t.espread[i]:.5f}"),
                row(f"s:{s}Distribution", '"BiGaussian"'),
                row(f"d:{s}SigmaX", f"{t.sigx[i]:.5f} mm"),
                row(f"d:{s}SigmaY", f"{t.sigy[i]:.5f} mm"),
                row(f"u:{s}SigmaXprime", f"{t.sigxp[i]:.5f}"),
                row(f"u:{s}SigmaYprime", f"{t.sigyp[i]:.5f}"),
                row(f"u:{s}CorrelationX", f"{t.corx[i]:.5f}"),
                row(f"u:{s}CorrelationY", f"{t.cory[i]:.5f}"),
                row(f"i:{s}NumberOfHistoriesInRun", f"{histories[i]}"),
                "",
            ]
        return "\n".join(lines) + "\n"

    @staticmethod
    def history_interval(t: "SpotTable") -> int:
        """Ts/ShowHistoryCountAtInterval for sources mode: about 100 progress lines per field.

        In sources mode a history is an event, and a field has only as many events as its
        largest spot weight -- a few hundred, not the ~1e5 of the time feature.
        """
        return max(1, TopasPlan.events_per_run(t) // 100)

    @staticmethod
    def events_per_run(t: "SpotTable") -> int:
        """Events in the single run of sources mode: the largest spot's history count."""
        return int(TopasPlan.spot_histories(t).max())

    @staticmethod
    def header(myfield: Field, table: Optional["SpotTable"], opts: TopasExportOptions,
               nstat_scale: float) -> str:
        """TopasText.header with the spot layout filled in (issue #88)."""
        layout, simulated = {}, None
        if table is not None:
            histories = TopasPlan.spot_histories(table)
            # The rounded spot weights, which differ from REQUESTED_HISTORIES. Plan scaling
            # needs this in both modes.
            simulated = int(histories.sum())
            if opts.spot_mode == "sources":
                layout = {"SPOTS": int((histories > 0).sum()), "RUNS": 1,
                          "EVENTS_PER_RUN": int(histories.max())}
            else:
                # The time feature runs every spot, even one with 0 histories.
                layout = {"SPOTS": int(histories.size), "RUNS": int(histories.size)}
        return TopasText.header(myfield, nstat_scale, opts.nstat, spot_mode=opts.spot_mode,
                                simulated_histories=simulated, layout=layout)

    @staticmethod
    def calculate_scaling_factor(myfield: Field, nstat: int = DEFAULTS.nstat) -> float:
        """
        Calculate the scaling factor for the number of particles in the field.
        """
        total_particles = myfield.n_particles
        nstat_scale = 1.0 / (nstat / total_particles) * myfield.scaling
        return nstat_scale

    @staticmethod
    def show_plan_data(myfield: Field, bm: BeamModel, nstat: int = DEFAULTS.nstat) -> None:
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
