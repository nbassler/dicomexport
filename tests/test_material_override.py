"""Structure material overrides: --material-override "ROI=MATERIAL" (issue #94)."""
import functools
import logging
from pathlib import Path

import numpy as np

import pydicom
import pytest
from pydicom.dataset import Dataset
from pydicom.sequence import Sequence

from dicomexport.import_ct import load_ct
from dicomexport.import_rtstruct import load_rs
from dicomexport.main import main as study_main
from dicomexport.material_override import (MaterialOverride, _enters, check_contours, parse_override,
                                           resolve_overrides, topas_structure_name, warn_declared_overrides)
from dicomexport.model_rtstruct import RTStruct, RTStructROI

STUDY = Path(__file__).parent.parent / "res" / "test_studies" / "DCPT_headphantom"
RS_FILE = next(STUDY.glob("RS*.dcm"))


def rtstruct(*names: str) -> RTStruct:
    return RTStruct(rois=[RTStructROI(n, i, (0, 0, 0)) for i, n in enumerate(names, 1)],
                    file_path=Path("RS.dcm"))


class TestNames:

    def test_topas_rewrites_spaces_and_trims(self):
        assert topas_structure_name("  Solid Water \t") == "Solid_Water"

    def test_split_at_the_last_equals_sign(self):
        """A ROI name may contain '='; a TOPAS material name does not."""
        assert parse_override("Ratio=1:2=G4_WATER") == ("Ratio=1:2", "G4_WATER")

    @pytest.mark.parametrize("text", ["BODY", "=G4_WATER", "BODY=", "BODY= "])
    def test_malformed(self, text):
        with pytest.raises(ValueError, match="expected ROI=MATERIAL"):
            parse_override(text)

    @pytest.mark.parametrize("material", ["My Steel", "Steel#2", "Steel?", "'Steel'", "St\u2013eel"])
    def test_a_material_name_a_topas_file_cannot_carry(self, material):
        with pytest.raises(ValueError, match="a material name cannot contain"):
            parse_override(f"BODY={material}")

    def test_a_nist_name_with_a_hyphen_is_fine(self):
        assert parse_override("BODY=G4_A-150_TISSUE") == ("BODY", "G4_A-150_TISSUE")


class TestResolve:

    def test_order_is_kept(self):
        rs = rtstruct("BODY", "Hip implant")
        assert resolve_overrides(["Hip implant=ImplantSteel", "BODY=G4_WATER"], rs) == [
            MaterialOverride("Hip implant", "ImplantSteel"), MaterialOverride("BODY", "G4_WATER")]

    def test_topas_spelling_finds_the_structure(self):
        [o] = resolve_overrides(["Hip_implant=ImplantSteel"], rtstruct("Hip implant"))
        assert (o.roi_name, o.topas_name) == ("Hip implant", "Hip_implant")

    def test_a_missing_structure_is_an_error_listing_the_others(self):
        with pytest.raises(ValueError, match=r"no structure 'Body' in RS.dcm, which has: 'BODY', 'CTV'"):
            resolve_overrides(["Body=G4_WATER"], rtstruct("BODY", "CTV"))

    def test_a_structure_given_twice_is_an_error(self):
        with pytest.raises(ValueError, match="already has an override"):
            resolve_overrides(["BODY=G4_WATER", "BODY=Vacuum"], rtstruct("BODY"))

    def test_structures_topas_cannot_tell_apart(self):
        with pytest.raises(ValueError, match="cannot tell apart"):
            resolve_overrides(["Solid Water=G4_WATER"], rtstruct("Solid Water", "Solid_Water"))

    @pytest.mark.parametrize("name", ["Marker=2", "Marker#2", "Marker?", "Bolus 'A'", "PTV\u201370"])
    def test_a_structure_name_a_topas_file_cannot_carry(self, name):
        """TOPAS rejects = ' ` ? in a value, cuts the line at #, and rewrites typographic dashes."""
        with pytest.raises(ValueError, match="TOPAS cannot match structure.*Rename"):
            resolve_overrides([f"{name}=G4_WATER"], rtstruct(name))

    def test_the_material_is_not_checked(self):
        """TOPAS reports an unknown material; dicomexport does not read material definitions."""
        assert resolve_overrides(["BODY=NoSuchMaterial"], rtstruct("BODY"))[0].material == "NoSuchMaterial"


class TestDeclaredOverrides:
    """The RTSTRUCT's own overrides are not applied, but no longer dropped silently."""

    @pytest.fixture
    def declared_rs(self, tmp_path) -> Path:
        ds = pydicom.dcmread(RS_FILE)
        numbers = {r.ROIName: int(r.ROINumber) for r in ds.StructureSetROISequence}
        obs = Dataset()
        obs.ObservationNumber = 1
        obs.ReferencedROINumber = numbers["Beekley"]
        obs.RTROIInterpretedType = "MARKER"
        obs.ROIInterpreter = ""
        obs.MaterialID = "PMMA"
        prop = Dataset()
        prop.ROIPhysicalProperty = "REL_ELEC_DENSITY"
        prop.ROIPhysicalPropertyValue = "1.16"
        obs.ROIPhysicalPropertiesSequence = Sequence([prop])
        ds.RTROIObservationsSequence = Sequence([obs])
        path = tmp_path / "RS.dcm"
        ds.save_as(path)
        return path

    def test_read(self, declared_rs):
        rois = {r.roi_name: r for r in load_rs(declared_rs).rois}
        assert rois["Beekley"].declared_overrides == ["MaterialID=PMMA", "REL_ELEC_DENSITY=1.16"]
        assert rois["BODY"].declared_overrides == []

    def test_warned_when_not_covered(self, declared_rs, caplog):
        rs = load_rs(declared_rs)
        with caplog.at_level(logging.WARNING):
            warn_declared_overrides(rs, [])
        assert "MaterialID=PMMA, REL_ELEC_DENSITY=1.16 for structure 'Beekley'" in caplog.text

    def test_silent_when_covered(self, declared_rs, caplog):
        rs = load_rs(declared_rs)
        with caplog.at_level(logging.WARNING):
            warn_declared_overrides(rs, resolve_overrides(["Beekley=G4_PLEXIGLASS"], rs))
        assert "declares" not in caplog.text


def modified_rs(tmp_path, edit) -> Path:
    """A copy of the test study's RTSTRUCT, changed by edit(ds, contour_sequence_of)."""
    ds = pydicom.dcmread(RS_FILE)
    numbers = {str(r.ROIName): int(r.ROINumber) for r in ds.StructureSetROISequence}

    def contours_of(name):
        return next(rc for rc in ds.ROIContourSequence if int(rc.ReferencedROINumber) == numbers[name])

    edit(ds, contours_of)
    path = tmp_path / "RS.dcm"
    ds.save_as(path)
    return path


@functools.cache
def slice_z() -> tuple:
    return tuple(img.image_position_patient[2] for img in load_ct(STUDY).images)


def check(path: Path, *names: str) -> None:
    rs = load_rs(path)
    check_contours(resolve_overrides([f"{n}=G4_WATER" for n in names], rs), path, slice_z())


class TestContours:
    """TOPAS fills every contour of 3 or more points and never clears a voxel; refuse what it
    would build differently from the RTSTRUCT."""

    def test_real_structures_pass(self):
        check(RS_FILE, "BODY", "Beekley", "BrainStem")

    def test_a_hole_is_refused(self):
        """The test study's CTV has a hole at z = 9.5 mm, drawn as a contour inside another."""
        with pytest.raises(ValueError, match=r"'CTV'.*z = 9.5 mm one contour lies inside or overlaps another"):
            check(RS_FILE, "CTV")

    @pytest.mark.parametrize("kind", ["CLOSEDPLANAR_XOR", "OPEN_PLANAR", "OPEN_NONPLANAR"])
    def test_other_contour_types_are_refused(self, tmp_path, kind):
        def edit(ds, contours_of):
            contours_of("Beekley").ContourSequence[0].ContourGeometricType = kind
        with pytest.raises(ValueError, match=f"'Beekley'.*has a {kind} contour"):
            check(modified_rs(tmp_path, edit), "Beekley")

    def test_a_structure_without_contours_is_refused(self, tmp_path):
        """TOPAS skips it while reading, then stops: "Required structure ... not found"."""
        def edit(ds, contours_of):
            del contours_of("Beekley").ContourSequence
        with pytest.raises(ValueError, match="'Beekley'.*no closed contour"):
            check(modified_rs(tmp_path, edit), "Beekley")

    def test_a_point_only_structure_is_refused(self, tmp_path):
        """TOPAS ignores contours of fewer than 3 points, so the override would change nothing."""
        def edit(ds, contours_of):
            point = contours_of("Beekley").ContourSequence[0]
            point.ContourGeometricType = "POINT"
            point.NumberOfContourPoints = 1
            point.ContourData = point.ContourData[:3]
            contours_of("Beekley").ContourSequence = [point]
        with pytest.raises(ValueError, match="'Beekley'.*no closed contour"):
            check(modified_rs(tmp_path, edit), "Beekley")

    def test_a_contour_between_ct_slices_is_refused(self, tmp_path):
        """TOPAS places a contour only on a slice at exactly its z, and skips it silently otherwise."""
        def edit(ds, contours_of):
            c = contours_of("Beekley").ContourSequence[0]
            c.ContourData = [v + 0.25 if i % 3 == 2 else v for i, v in enumerate(c.ContourData)]
        with pytest.raises(ValueError, match="'Beekley'.*where the CT has no slice"):
            check(modified_rs(tmp_path, edit), "Beekley")

    def test_roi_sequences_in_another_order_are_refused(self, tmp_path):
        """OpenTOPAS 4.3.0 loses the first structure-set ROI if another ROI's contours come first."""
        def edit(ds, contours_of):
            ds.ROIContourSequence = list(reversed(ds.ROIContourSequence))
        with pytest.raises(ValueError, match="OpenTOPAS 4.3.0 cannot read.*same order"):
            check(modified_rs(tmp_path, edit), "Beekley")

    def test_contours_of_an_undefined_roi_are_refused(self, tmp_path):
        def edit(ds, contours_of):
            contours_of("Beekley").ReferencedROINumber = 999
        with pytest.raises(ValueError, match=r"ROI numbers \[999\]"):
            check(modified_rs(tmp_path, edit), "BODY")

    def rename_beekley(self, tmp_path, charset):
        def edit(ds, contours_of):
            ds.SpecificCharacterSet = charset
            next(r for r in ds.StructureSetROISequence if r.ROIName == "Beekley").ROIName = "Markør"
        return modified_rs(tmp_path, edit)

    def test_a_name_not_stored_as_utf8_is_refused(self, tmp_path):
        """TOPAS compares the stored bytes with the UTF-8 TOPAS file: Latin-1 'ø' never matches."""
        with pytest.raises(ValueError, match="'Markør'.*not stored as UTF-8.*ISO_IR 100"):
            check(self.rename_beekley(tmp_path, "ISO_IR 100"), "Markør")

    def test_a_name_stored_as_utf8_passes(self, tmp_path):
        check(self.rename_beekley(tmp_path, "ISO_IR 192"), "Markør")


class TestOverlap:
    """Holes are refused whichever vertex a contour starts at; neighbours sharing an edge are not."""

    SQUARE = np.array([[0, 0], [10, 0], [10, 10], [0, 10]], float)

    @pytest.mark.parametrize("start", range(4))
    def test_neighbours_sharing_an_edge(self, start):
        right = np.roll(self.SQUARE + [10, 0], start, axis=0)
        assert not _enters(right, self.SQUARE) and not _enters(self.SQUARE, right)

    @pytest.mark.parametrize("start", range(4))
    def test_a_hole(self, start):
        hole = np.roll(self.SQUARE / 5 + 4, start, axis=0)
        assert _enters(hole, self.SQUARE)

    def test_overlapping(self):
        assert _enters(self.SQUARE + 5, self.SQUARE)

    def test_apart(self):
        assert not _enters(self.SQUARE + 20, self.SQUARE)


class TestStudyExport:

    def export(self, tmp_path, *args) -> str:
        assert study_main([str(STUDY), str(tmp_path / "topas.txt"), "-f", "1", "-N", "1000", "--batches", "1",
                           *args]) == 0
        return (tmp_path / "topas_field01.txt").read_text(encoding="utf-8")

    def test_overrides_are_written(self, tmp_path):
        text = self.export(tmp_path, "--material-override", "Beekley=G4_PLEXIGLASS",
                           "--material-override", "BODY=G4_WATER")
        lines = text.splitlines()
        assert f's:Ge/Patient/DicomRTStructFile              = "{RS_FILE.as_posix()}"' in lines
        assert 'sv:Ge/Patient/MaterialByRTStructNames       = 2 "Beekley" "BODY"' in lines
        assert 'sv:Ge/Patient/MaterialByRTStructMaterials   = 2 "G4_PLEXIGLASS" "G4_WATER"' in lines
        assert ["# MATERIAL_OVERRIDE: Beekley=G4_PLEXIGLASS", "# MATERIAL_OVERRIDE: BODY=G4_WATER"] == [
            line for line in lines if line.startswith("# MATERIAL_OVERRIDE:")]

    def test_nothing_without_overrides(self, tmp_path):
        text = self.export(tmp_path)
        assert "MaterialByRTStruct" not in text and "DicomRTStructFile" not in text

    def test_a_structure_topas_would_build_wrongly_stops_the_export(self, tmp_path, caplog):
        assert study_main([str(STUDY), str(tmp_path / "topas.txt"), "--material-override", "CTV=G4_WATER"]) == 2
        assert "lies inside or overlaps another" in caplog.text
        assert not list(tmp_path.iterdir())

    def test_a_missing_structure_stops_the_export(self, tmp_path, caplog):
        assert study_main([str(STUDY), str(tmp_path / "topas.txt"), "--material-override", "Body=G4_WATER"]) == 2
        assert "no structure 'Body'" in caplog.text
        assert not list(tmp_path.iterdir())
