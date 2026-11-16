"""Options that shape a TOPAS export, passed down as one object (issue #116).

The defaults here are the only copy: the CLI parsers read theirs from
TopasExportOptions(), and the exporters take an instance instead of separate keywords.
The TopasText generators keep explicit arguments, so they stay simple to unit-test.
"""
from dataclasses import dataclass
from typing import Optional

from dicomexport.topas_version import DEFAULT_TOPAS_VERSION, TopasVersion

# CLI name of each nozzle side, keyed by beam_direction. The order is the --help order.
NOZZLE_SIDES = {1: "pos-z", -1: "neg-z"}

# How TOPAS steps through the spots of a field (issue #88).
#   sources:     one Emittance source per spot, the whole field in one Geant4 run.
#   timefeature: one source stepped through the spots by a time feature, one run per spot.
SPOT_MODES = ("sources", "timefeature")

# Sources mode splits a field into this many identical runs (batches) unless told otherwise,
# so that a consumer can estimate the statistical uncertainty by batch means (issue #121).
DEFAULT_BATCHES = 10


@dataclass(frozen=True)
class TopasExportOptions:
    # Target number of primaries for the simulation; spot weights are scaled to it.
    nstat: int = int(1e6)
    # -1: nozzle on gantry-local -Z, IEC 61217 (issue #66). +1: mirrored, research only.
    beam_direction: int = -1
    # Ts/NumberOfThreads, passed through verbatim (issue #85).
    nr_threads: int = 0
    # TOPAS release the file is written for (issue #95).
    topas_version: TopasVersion = DEFAULT_TOPAS_VERSION
    # Write the DICOM dose cube at 16 instead of 32 bits per pixel (issue #111).
    dose_cube_16bit: bool = False
    # One source per spot, or a time feature stepping one source (issue #88).
    spot_mode: str = "sources"
    # Identical runs per field in sources mode (issue #121). None: DEFAULT_BATCHES in
    # sources mode, 1 in timefeature mode, which already runs one spot per run.
    batches: Optional[int] = None

    def __post_init__(self):
        if self.beam_direction not in NOZZLE_SIDES:
            raise ValueError(f"beam_direction must be -1 or 1, got {self.beam_direction!r}")
        if self.spot_mode not in SPOT_MODES:
            raise ValueError(f"spot_mode must be one of {SPOT_MODES}, got {self.spot_mode!r}")
        if self.batches is not None and self.batches < 1:
            raise ValueError(f"batches must be at least 1, got {self.batches}")
        if self.spot_mode != "sources" and (self.batches or 1) > 1:
            raise ValueError(f"batches > 1 needs spot_mode 'sources', got {self.spot_mode!r}")

    @property
    def n_batches(self) -> int:
        """Runs the field is split into: the batches setting resolved for the spot mode."""
        if self.batches is not None:
            return self.batches
        return DEFAULT_BATCHES if self.spot_mode == "sources" else 1

    @property
    def nozzle_side(self) -> str:
        return NOZZLE_SIDES[self.beam_direction]

    @staticmethod
    def beam_direction_of(nozzle_side: str) -> int:
        """Map a --nozzle-side value back to beam_direction."""
        return {side: d for d, side in NOZZLE_SIDES.items()}[nozzle_side]


DEFAULTS = TopasExportOptions()
