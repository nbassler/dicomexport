from dataclasses import dataclass

from dicomexport.topas_version import DEFAULT_TOPAS_VERSION, TopasVersion


@dataclass(frozen=True)
class TopasExportOptions:
    nstat: int = int(1e6)
    beam_direction: int = -1
    nr_threads: int = 0
    topas_version: TopasVersion = DEFAULT_TOPAS_VERSION
    dose_cube_16bit: bool = True
