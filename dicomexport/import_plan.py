import logging
from pathlib import Path

from dicomexport.dicom_scan import RTPLAN, scan_study, exactly_one
from dicomexport.model_plan import Plan
from dicomexport.import_plan_pld import load_plan_pld
from dicomexport.import_plan_dicom import load_plan_dicom
from dicomexport.import_plan_rst import load_plan_rst

logger = logging.getLogger(__name__)


def load_plan(path: Path, **kwargs) -> Plan:
    """
    Load a treatment plan from a file (PLD, DICOM RT Ion Plan, RST) and return a Plan object.
    """

    # If path is a directory, find the plan by Modality header (issue #77) rather
    # than an RN*.dcm glob, which missed RayStation's RP*.dcm. The .pld and .rst
    # globs stay: those are not DICOM and carry no Modality tag.
    if path.is_dir():
        plan_files = sorted(
            scan_study(path).get(RTPLAN) +
            list(path.glob('**/*.pld')) +
            list(path.glob('**/*.rst'))
        )
        path = exactly_one(
            plan_files, "plan files", path, "Please pass the specific plan file.")
        logger.info("Using plan file: %s", path.name)

    suffix = path.suffix.lower()
    if suffix == '.pld':
        return load_plan_pld(path, **kwargs)
    elif suffix == '.dcm':
        return load_plan_dicom(path, **kwargs)
    elif suffix == '.rst':
        return load_plan_rst(path, **kwargs)
    else:
        raise ValueError(f"Unsupported plan file format: {suffix}")
