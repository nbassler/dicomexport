"""Target TOPAS version for the generated input files (issue #95).

Parameter names have changed between TOPAS releases, so a file written for current
OpenTOPAS may not run on an older TOPAS. The exporters take the target version as a
`(major, minor)` tuple and gate each such difference on it.
"""
import argparse
import re
from typing import Tuple

TopasVersion = Tuple[int, int]

# Newest TOPAS the output has been verified against (OpenTOPAS 4.2.3). Raise it only
# after checking the newer release for further parameter changes.
DEFAULT_TOPAS_VERSION: TopasVersion = (4, 2)

# OpenTOPAS 4.2.0 introduced EmittanceParticle/EmittanceEnergy/EmittanceEnergySpread
# (TsVGenerator::ResolveGeneratorParameterName). TOPAS 3.9 to 4.1 only know the
# Beam* names for an emittance source, and abort on the Emittance* names.
EMITTANCE_PARAMETER_NAMES_SINCE: TopasVersion = (4, 2)

_VERSION_RE = re.compile(r"^\s*(\d+)\.(\d+)(?:\.p?\d+)?\s*$")


def parse_topas_version(text: str) -> TopasVersion:
    """Parse '3.9', '4.2', '4.2.3' or '4.2.p3' into (major, minor).

    The patch level is accepted but dropped: no parameter name has changed within a
    minor release. Raises argparse.ArgumentTypeError so it can serve as an argparse type.
    """
    m = _VERSION_RE.match(text)
    if not m:
        raise argparse.ArgumentTypeError(
            f"invalid TOPAS version {text!r}: expected MAJOR.MINOR, e.g. 3.9 or 4.2")
    return int(m.group(1)), int(m.group(2))


def format_topas_version(version: TopasVersion) -> str:
    return f"{version[0]}.{version[1]}"


TOPAS_VERSION_HELP = (
    f"TOPAS version the input file is written for, as MAJOR.MINOR "
    f"(default: {format_topas_version(DEFAULT_TOPAS_VERSION)}). Versions below "
    f"{format_topas_version(EMITTANCE_PARAMETER_NAMES_SINCE)} get the emittance source "
    f"as BeamParticle/BeamEnergy/BeamEnergySpread instead of the Emittance* names, "
    f"which they do not recognise.")
