import copy
import logging
import numpy as np
from pathlib import Path

from dicomexport.model_plan import (Plan, Field, Layer, Spot, RangeShifter,
                                    RS_CATALOG, NO_RANGE_SHIFTER_ID)

logger = logging.getLogger(__name__)


def load_plan_dicom(file_dcm: Path, rs_catalog: dict | None = None) -> Plan:
    """Load DICOM RTPLAN.

    Args:
        file_dcm: the plan file.
        rs_catalog: range shifter catalog to resolve RangeShifterID against.
            None uses the built-in RS_CATALOG; a loaded catalog replaces it
            entirely (see model_plan.load_range_shifter_catalog).
    """
    catalog = RS_CATALOG if rs_catalog is None else rs_catalog

    p = Plan()
    try:
        import pydicom as dicom

    except ImportError:
        logger.error("pydicom is not installed, cannot read DICOM files.")
        logger.error(
            "Please install pymchelper[dicom] or pymchelper[all] to us this feature.")
        return p
    d = dicom.dcmread(file_dcm)

    # Check if the file is an RTPLAN
    if d.Modality != "RTPLAN":
        logger.error(
            "File %s is not a valid RTPLAN file (Modality: %s)", file_dcm, d.Modality)
        raise ValueError("File is not a valid RTPLAN DICOM file.")

    # Check also the SOP Class UID
    if d.SOPClassUID != '1.2.840.10008.5.1.4.1.1.481.8':
        logger.error(
            "File %s is not a valid RTPLAN file (SOP Class UID: %s)", file_dcm, d.SOPClassUID)
        raise ValueError("File is not a valid RTPLAN DICOM file.")

    # optional attributes that may not be present in all RTPLAN files and can default to empty strings
    p.patient_id = getattr(d, 'PatientID', '')
    p.patient_name = getattr(d, 'PatientName', '')
    p.patient_initials = getattr(d, 'PatientInitials', '')
    p.patient_firstname = getattr(d, 'PatientFirstName', '')
    p.plan_label = getattr(d, 'RTPlanLabel', '')
    p.plan_date = getattr(d, 'RTPlanDate', '')

    # mandatory attributes, code will raise an error if they are not present
    p.sop_instance_uid = d['SOPInstanceUID'].value

    espread = 0.0  # will be set by beam model
    fraction_group = d['FractionGroupSequence'][0]
    n_referenced = int(fraction_group['NumberOfBeams'].value)
    logger.debug("Fraction group references %i beams", n_referenced)

    # Dose and meterset live in the fraction group, keyed by ReferencedBeamNumber.
    # That sequence is NOT necessarily in the same order as IonBeamSequence -- plans
    # occur with the references out of order (e.g. 4, 5, 1, 2, 3) -- so pairing the two
    # positionally silently puts dose and MU on the wrong beams (issue #75).
    delivery, referenced = _referenced_beam_delivery(fraction_group)

    ibs = d['IonBeamSequence']  # ion beam sequence, contains all beams defined by the plan

    for ibm in ibs.value:
        field_nr = int(ibm['BeamNumber'].value)
        beam_name = str(ibm['BeamName'].value) if 'BeamName' in ibm else ''

        if field_nr not in delivery:
            if field_nr in referenced:
                # _referenced_beam_delivery() already warned why; do not repeat it.
                logger.debug("Skipping beam %d ('%s'): no BeamMeterset.", field_nr, beam_name)
            else:
                logger.warning(
                    "Skipping beam %d ('%s'): the fraction group does not reference it, "
                    "so it is not part of this fraction.", field_nr, beam_name)
            continue

        myfield = Field()
        myfield.number = field_nr
        myfield.sop_instance_uid = p.sop_instance_uid
        myfield.dose, myfield.cum_mu = delivery[field_nr]
        p.fields.append(myfield)
        logger.debug("Appending beam number %d ('%s')...", field_nr, beam_name)

        myfield.name = beam_name
        # each layer has 2 control points
        n_layers = int(ibm['NumberOfControlPoints'].value) // 2
        myfield.meterset_weight_final = float(
            ibm['FinalCumulativeMetersetWeight'].value)
        myfield.meterset_per_weight = myfield.cum_mu / myfield.meterset_weight_final

        icps = ibm['IonControlPointSequence']  # layers for given field number
        logger.debug("Found %i layers in field number %i", n_layers, field_nr)

        cmu = 0.0

        # If range shifters are present, build the RS lookup dictionary
        logger.debug(
            "Checking for Range Shifter Sequence in field number %i", field_nr)

        rs_dict: dict[int, RangeShifter] = {}
        if 'RangeShifterSequence' in ibm:
            for rs_item in ibm['RangeShifterSequence']:
                rs = _build_range_shifter(rs_item, catalog, field_nr)
                rs_dict[rs.number] = rs

        layer_nr = 1
        logger.debug(f"Processing field number: {field_nr}")

        # Source-to-axis distances: a machine property of the beam, so it is resolved
        # once here and stored on the Field as the single source of truth for the
        # divergence geometry that the exporters back-project with (issue #79).
        myfield.sad = _resolve_sad(ibm, icps, field_nr)

        # init some values which may only be changed once or not at all.
        snout_position = 0.0
        isocenter = (0.0, 0.0, 0.0)
        gantry_angle = 0.0
        couch_angle = 0.0
        energy = 0.0
        size_x = 0.0  # dicom values are in FWHM mm, but will be ignored, if beam model is available.
        size_y = 0.0

        for icp_index, icp in enumerate(icps):
            logger.debug(f"  Processing control point index: {icp_index}")
            # Several attributes are only set once at the first ion control point.
            # The strategy here is then to still set them for every layer, even if they do not change.
            # This is to ensure that the field object has all necessary attributes set.
            # But also enables future stuff like arc therapy, where these values may change per layer.

            # check snout position
            if 'SnoutPosition' in icp:
                snout_position = float(icp['SnoutPosition'].value)

            if 'RangeShifterSettingsSequence' in icp:
                for rss in icp['RangeShifterSettingsSequence']:
                    if getattr(rss, 'RangeShifterSetting', None) == "IN":
                        # lookup range shifter by number, and make a copy of it
                        _rs_number = rss['ReferencedRangeShifterNumber'].value
                        _rs = rs_dict[_rs_number]
                        myfield.range_shifter = copy.deepcopy(_rs)
                        # set remaining attributes
                        myfield.range_shifter.is_inserted = True
                        # (300A,0366), not 'WaterEquivalentThickness', which is a different tag
                        myfield.range_shifter.water_equivalent_thickness = float(
                            rss.get('RangeShifterWaterEquivalentThickness', 0.0) or 0.0)
                        myfield.range_shifter.isocenter_distance = _rs_isocenter_distance(
                            rss, myfield.number)

            # isocenter position and gantry counch angles are stored in each layer,
            # for now we assume they are the same for all layers in a field,
            # ideally these attributes should be stored in the layer object
            # then conversion can change it to a field level for topas export.
            if 'IsocenterPosition' in icp:
                isocenter = tuple(float(v)
                                  for v in icp['IsocenterPosition'].value)
                # check that length is 3.
                if len(isocenter) != 3:
                    logger.error(
                        "IsocenterPosition must have exactly 3 values, found %d in control point index %i",
                        len(isocenter), icp_index)
                    raise ValueError(
                        "Invalid DICOM plan: IsocenterPosition has incorrect number of values.")

            if 'GantryAngle' in icp:
                gantry_angle = float(icp['GantryAngle'].value)
            if 'PatientSupportAngle' in icp:
                couch_angle = float(icp['PatientSupportAngle'].value)

            # Nominal beam energy seems to be a special case, which can be set in
            # every control point, even if it does not change, or it can be set once
            # together with gantry angle etc.

            if 'NominalBeamEnergy' in icp:
                # Nominal energy in MeV
                energy = float(icp['NominalBeamEnergy'].value)

            # The remaining attributes are required for each control point.
            # Therefore we check them one by one and raise an error if any is missing.

            if 'NumberOfScanSpotPositions' in icp:
                # number of spots
                nspots = int(icp['NumberOfScanSpotPositions'].value)
            else:
                logger.error(
                    "NumberOfScanSpotPositions not found in control point index %i", icp_index)
                raise ValueError(
                    "Invalid DICOM plan: NumberOfScanSpotPositions missing.")

            if 'ScanSpotPositionMap' in icp:  # Extract spot MU and scale [MU]
                pos = np.array(
                    icp['ScanSpotPositionMap'].value).reshape(nspots, 2)
            else:
                logger.error(
                    "ScanSpotPositionMap not found in control point index %i", icp_index)
                raise ValueError(
                    "Invalid DICOM plan: ScanSpotPositionMap missing.")

            if 'ScanSpotMetersetWeights' in icp:
                mu = np.array(icp['ScanSpotMetersetWeights'].value).reshape(
                    nspots) * myfield.meterset_per_weight
            else:
                logger.error(
                    "ScanSpotMetersetWeights not found in control point index %i", icp_index)
                raise ValueError(
                    "Invalid DICOM plan: ScanSpotMetersetWeights missing.")

            # Extract spot nominal sizes [mm FWHM]
            if 'ScanningSpotSize' in icp:
                size_x, size_y = icp['ScanningSpotSize'].value

            logger.debug(
                "Found %i spots in layer number %i at energy %f", nspots, layer_nr, energy)
            nrepaint = int(icp['NumberOfPaintings'].value)  # number of spots

            spots = [Spot(x=x, y=y, mu=mu_val, size_x=size_x, size_y=size_y)
                     for (x, y), mu_val in zip(pos, mu)]

            # only append layer, if sum of mu are larger than 0
            sum_mu = np.sum(mu)

            if sum_mu > 0.0:
                cmu += sum_mu
                myfield.layers.append(Layer(
                    spots=spots,
                    energy_nominal=energy,
                    energy_measured=energy,
                    espread=espread,
                    cum_mu=cmu,
                    repaint=nrepaint,
                    mu_to_part_coef=0.0,
                    isocenter=isocenter,
                    gantry_angle=gantry_angle,
                    couch_angle=couch_angle,
                    snout_position=snout_position,
                    number=layer_nr
                ))
                layer_nr += 1
            else:
                logger.debug("Skipping empty layer index %i", icp_index)

    # The loop above visits IonBeamSequence, so a beam the fraction group delivers MU on
    # but which the plan never defines would otherwise be dropped without a word, and the
    # export would silently under-deliver.
    undefined = sorted(set(delivery) - {f.number for f in p.fields})
    if undefined:
        logger.warning(
            "The fraction group delivers monitor units on beam(s) %s (%s MU) that "
            "IonBeamSequence does not define. They cannot be exported, so this plan is "
            "incomplete: the exported fields deliver less than the plan prescribes.",
            ", ".join(str(n) for n in undefined),
            ", ".join(f"{delivery[n][1]:.1f}" for n in undefined))

    return p


#: Relative tolerance when comparing the two DICOM sources of the source-axis distance.
_SAD_AGREEMENT_RTOL = 1e-3


def _is_usable_sad(values) -> bool:
    """True if both distances are finite and positive.

    NaN and inf must be rejected explicitly: ``nan <= 0.0`` is False, and inf passes a
    plain positivity test while ``(inf - D) / inf`` then yields nan, so either would
    slip through into the divergence maths (issue #79).
    """
    return all(np.isfinite(v) and v > 0.0 for v in values)


def _referenced_beam_delivery(fraction_group) -> tuple[dict[int, tuple[float, float]], set[int]]:
    """
    Read what the fraction group prescribes per beam.

    Returns ``(delivery, referenced)`` where ``delivery`` maps ReferencedBeamNumber ->
    (beam dose [Gy], beam meterset [MU]) and ``referenced`` is every number the sequence
    mentions at all. The caller needs both so it can tell a beam that was referenced but
    delivers nothing from one that is not part of this fraction -- different situations
    that warrant different messages.

    Only beams that carry a BeamMeterset reach ``delivery``: without monitor units
    nothing is delivered and there is nothing to export.

    BeamDose is treated as informational and defaults to 0.0 when absent. Building a
    plan needs only the MU, and some planning systems leave the dose off beams they
    still deliver, so requiring it would reject usable plans (issue #75).
    """
    delivery: dict[int, tuple[float, float]] = {}
    referenced: set[int] = set()

    for rb in fraction_group['ReferencedBeamSequence']:
        number = int(rb['ReferencedBeamNumber'].value)
        referenced.add(number)

        meterset = rb.get('BeamMeterset', None)
        if meterset is None:
            logger.warning(
                "Referenced beam %d has no BeamMeterset; it delivers no monitor units "
                "and will not be exported.", number)
            continue

        dose = rb.get('BeamDose', None)
        if dose is None:
            logger.info(
                "Referenced beam %d has no BeamDose; recording 0.0 Gy. The meterset is "
                "what the export needs, so the beam is kept.", number)

        delivery[number] = (float(dose) if dose is not None else 0.0, float(meterset))

    if not delivery:
        raise ValueError(
            "No beam in the fraction group has a BeamMeterset, so the plan delivers "
            "nothing that can be exported.")
    return delivery, referenced


def _virtual_source_axis_distances(ibm, field_nr: int) -> tuple[float, float] | None:
    """
    Read VirtualSourceAxisDistances (300A,030A) from an IonBeamSequence item.

    This is Type 1 in the RT Ion Beams module and is the vendor-neutral source of the
    (x, y) source-to-axis distances. Returns None if absent or unusable, so the caller
    can fall back rather than fail here.
    """
    vsad = getattr(ibm, 'VirtualSourceAxisDistances', None)
    if vsad is None:
        return None
    try:
        values = [float(v) for v in vsad]
    except (TypeError, ValueError):
        logger.warning("Field %d: VirtualSourceAxisDistances is not numeric (%r); ignoring it.",
                       field_nr, vsad)
        return None
    if len(values) != 2:
        logger.warning("Field %d: VirtualSourceAxisDistances should have 2 values, found %d; ignoring it.",
                       field_nr, len(values))
        return None
    if not _is_usable_sad(values):
        logger.warning("Field %d: VirtualSourceAxisDistances must be finite and positive, got %s; ignoring it.",
                       field_nr, values)
        return None
    return (values[0], values[1])


def _lateral_spreading_device_distances(
        ibm, icps, field_nr: int) -> tuple[tuple[float, float] | None, bool]:
    """
    Read the (x, y) IsocenterToLateralSpreadingDeviceDistance, if the plan has one.

    Returns ``(distances_or_None, all_magnets)``. ``all_magnets`` is True only when
    every referenced device is of LateralSpreadingDeviceType MAGNET, i.e. the plan
    explicitly names the deflection magnets that bend the scanned beam. A SCATTERER
    is a different thing and must not be used as a scanning pivot, so it reports
    False and the caller falls back to the virtual source.

    Distances are None when no control point carries a
    LateralSpreadingDeviceSettingsSequence, the normal case for pure PBS plans
    (e.g. RayStation).
    """
    device_types = {
        getattr(d, 'LateralSpreadingDeviceNumber', None): getattr(d, 'LateralSpreadingDeviceType', None)
        for d in getattr(ibm, 'LateralSpreadingDeviceSequence', [])
    }

    for icp in icps:
        if 'LateralSpreadingDeviceSettingsSequence' not in icp:
            continue
        lss = icp['LateralSpreadingDeviceSettingsSequence']
        if len(lss.value) != 2:
            logger.error("LateralSpreadingDeviceSettingsSequence should contain exactly 2 elements, found %d.",
                         len(lss.value))
            raise ValueError(
                "Invalid LateralSpreadingDeviceSettingsSequence in DICOM plan.")

        referenced = [getattr(s, 'ReferencedLateralSpreadingDeviceNumber', None) for s in lss]
        types = [device_types.get(ref) for ref in referenced]
        all_magnets = bool(types) and all(t == 'MAGNET' for t in types)
        if not all_magnets:
            logger.debug("Field %d: lateral spreading device types %s are not both MAGNET.",
                         field_nr, types)

        distances = (float(lss[0]['IsocenterToLateralSpreadingDeviceDistance'].value),
                     float(lss[1]['IsocenterToLateralSpreadingDeviceDistance'].value))
        if not _is_usable_sad(distances):
            logger.warning("Field %d: lateral spreading device distances must be finite and "
                           "positive, got %s; ignoring them.", field_nr, list(distances))
            return None, False
        return distances, all_magnets
    return None, False


def _resolve_sad(ibm, icps, field_nr: int) -> tuple[float, float]:
    """
    Determine the (x, y) source-to-axis distances for one beam.

    Both exporters use this as the pivot the scanned ray turns about, so what is
    wanted is the effective deflection point.

    When the plan explicitly names its deflection magnets (LateralSpreadingDeviceType
    MAGNET, as Varian/DCPT do), those distances are used: an explicit inflection point
    beats a derived one, and this keeps such plans bit-identical to previous releases.
    Otherwise VirtualSourceAxisDistances is used -- it is required for ion beams and,
    for a scanned beam, is defined as that same effective deflection point. A SCATTERER
    is never used as a scanning pivot.

    Pure PBS plans (e.g. RayStation) write no lateral spreading device at all. Reading
    only that optional sequence is what made SAD fall back to 0.0 and produce inf spot
    positions downstream (issue #79).

    Raises ValueError if neither source yields a usable distance, rather than letting a
    zero reach the divergence maths.
    """
    vsad = _virtual_source_axis_distances(ibm, field_nr)
    lsd, lsd_is_magnet = _lateral_spreading_device_distances(ibm, icps, field_nr)

    # A non-magnet device (a scatterer) is not the pivot a scanned ray turns about, so
    # it is never used as one -- not even as a last resort when VSAD is missing.
    prefer_lsd = lsd is not None and lsd_is_magnet
    sad = lsd if prefer_lsd else vsad

    if not prefer_lsd and vsad is not None:
        reason = ("no lateral spreading device in plan" if lsd is None
                  else "lateral spreading device is not a deflection magnet")
        logger.info(
            "Field %d: %s; taking the source-to-axis distance from "
            "VirtualSourceAxisDistances (%.2f / %.2f mm).",
            field_nr, reason, vsad[0], vsad[1])

    if vsad is not None and lsd is not None:
        if not np.allclose(vsad, lsd, rtol=_SAD_AGREEMENT_RTOL):
            logger.warning(
                "Field %d: VirtualSourceAxisDistances %s disagree with the lateral "
                "spreading device distances %s. Using %s.",
                field_nr, list(vsad), list(lsd),
                "the deflection magnets" if prefer_lsd else "VirtualSourceAxisDistances")

    if sad is None:
        detail = ("a lateral spreading device is present but is not a deflection magnet, "
                  "so it cannot serve as the scanning pivot"
                  if lsd is not None else
                  "no LateralSpreadingDeviceSettingsSequence is present either")
        raise ValueError(
            f"Field {field_nr}: no usable source-to-axis distance in the plan. "
            f"VirtualSourceAxisDistances (300A,030A) is missing or unusable, and "
            f"{detail}. The beam divergence cannot be determined.")
    if not _is_usable_sad(sad):
        raise ValueError(
            f"Field {field_nr}: source-to-axis distance must be finite and positive, "
            f"got {sad[0]} / {sad[1]} mm.")

    logger.debug("Field %d: SAD X/Y = %.2f / %.2f mm (source: %s)", field_nr, sad[0], sad[1],
                 "deflection magnets" if prefer_lsd else "VirtualSourceAxisDistances")
    return sad


def _rs_isocenter_distance(rss, field_number: int) -> float:
    """
    Distance from the isocenter to the range shifter, positive upstream.

    IBA plans store every distance along the beam line as positive upstream (snout position,
    scanning magnets), but some vendors write IsocenterToRangeShifterDistance with the
    opposite sign. A negative value would place the range shifter downstream of the
    isocenter, i.e. inside the patient, so take the magnitude and warn when flipping.
    """
    distance = float(rss.get('IsocenterToRangeShifterDistance', 0.0))

    if distance < 0.0:
        logger.warning(
            "Field %i: IsocenterToRangeShifterDistance is negative (%.2f mm), which would place "
            "the range shifter downstream of the isocenter. Assuming a sign convention where "
            "upstream is negative, and using %.2f mm instead.",
            field_number, distance, -distance)
        distance = -distance

    return distance


def _build_range_shifter(rs_item, catalog: dict | None = None,
                         field_nr: int | None = None) -> RangeShifter:
    if 'RangeShifterNumber' not in rs_item:
        raise ValueError("RangeShifterNumber not found in DICOM plan")

    if 'RangeShifterID' not in rs_item:
        raise ValueError("RangeShifterID not found in DICOM plan")

    number = int(rs_item['RangeShifterNumber'].value)
    rs_id = str(rs_item['RangeShifterID'].value)
    rs_type = str(rs_item['RangeShifterType'].value) if 'RangeShifterType' in rs_item else ""

    # "No shifter" describes the absence of a device, so it is answered here rather than
    # looked up. Resolving it from a catalog entry would make the guarantee depend on
    # what the catalog happens to contain, and a hand-built dict passed programmatically
    # would break it.
    if rs_id == NO_RANGE_SHIFTER_ID:
        return RangeShifter(id=rs_id, number=number, type=rs_type,
                            thickness=0.0, material=None)

    # matching is intentionally case-sensitive: IDs are site-local labels used verbatim
    catalog = RS_CATALOG if catalog is None else catalog
    if rs_id not in catalog:
        where = f" on beam {field_nr}" if field_nr is not None else ""
        known = ", ".join(sorted(k for k in catalog if k != NO_RANGE_SHIFTER_ID)) or "(none)"
        source = ("the built-in catalog" if catalog is RS_CATALOG
                  else "the range shifter catalog supplied with --range-shifter-catalog")
        raise ValueError(
            f"Unknown RangeShifterID '{rs_id}'{where}. It is not in {source}, which "
            f"defines: {known}. A DICOM plan gives no thickness or material, so the "
            f"shifter has to be looked up. Supply a catalog listing every shifter this "
            f"plan uses with --range-shifter-catalog FILE; see "
            f"res/range_shifters/README.md for the format and examples.")

    spec = catalog[rs_id]
    return RangeShifter(
        id=rs_id,
        number=number,
        type=rs_type,
        thickness=spec["thickness"],
        material=spec["material"],
        # keep other fields at dataclass defaults
        # water_equivalent_thickness=..., density=..., etc
    )
