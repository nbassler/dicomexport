"""Structure material overrides: --material-override "ROI=MATERIAL" (issue #94)."""
import logging
from pathlib import Path

import pydicom
import pytest
from pydicom.dataset import Dataset
from pydicom.sequence import Sequence

from dicomexport.import_rtstruct import load_rs
from dicomexport.main import main as study_main
from dicomexport.material_override import (MaterialOverride, parse_override, resolve_overrides,
                                           topas_structure_name, warn_declared_overrides)
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

    def test_a_missing_structure_stops_the_export(self, tmp_path, caplog):
        assert study_main([str(STUDY), str(tmp_path / "topas.txt"), "--material-override", "Body=G4_WATER"]) == 2
        assert "no structure 'Body'" in caplog.text
        assert not list(tmp_path.iterdir())
