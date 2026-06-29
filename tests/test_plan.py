import math
import os
import subprocess
import sys
import tempfile

import mcpl
import numpy as np
import pytest

from dicomexport.model_plan import Plan
from dicomexport.import_plan import load_plan

TEST_PDG_PROTON = 2212


class TestPlan:
    def test_plan_initialization(self):
        p = Plan()
        assert isinstance(p, Plan)
        assert p.scaling == 1.0
        assert p.n_fields == 0

    def test_plan_fields_list(self):
        p = Plan()
        assert isinstance(p.fields, list)
        assert len(p.fields) == 0

    def test_load_plan_multiple_raises(self, tmp_path):
        sub_a = tmp_path / "sub_a"
        sub_b = tmp_path / "sub_b"
        sub_a.mkdir()
        sub_b.mkdir()
        (sub_a / "RN001.dcm").touch()
        (sub_b / "RN002.dcm").touch()
        with pytest.raises(ValueError, match="Multiple plan files"):
            load_plan(tmp_path)


class TestMCPLExport:
    def test_mcpl_export_roundtrip_100(self):
        plan_path = "res/test_plans/temp_160MeV_10x10.dcm"
        bm_path = "res/beam_models/DCPT_beam_model__v2.csv"

        with tempfile.TemporaryDirectory() as td:
            out_path = os.path.join(td, "myoutput.mcpl")

            cmd = [
                sys.executable,
                "dicomexport/main_plan_export.py",
                plan_path, out_path,
                f"-b={bm_path}",
                "--export-fmt=mcpl",
                "-v", "-N=100",
            ]

            env = dict(os.environ)
            env["PYTHONPATH"] = "." + (os.pathsep + env.get("PYTHONPATH", ""))

            result = subprocess.run(
                cmd, env=env,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
            )
            if result.returncode != 0:
                pytest.fail(f"CLI failed\ncmd={cmd}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}")

            out_field = os.path.join(td, "myoutput_field01.mcpl")
            assert os.path.exists(out_field), f"Expected output file not found: {out_field}"

            particles = list(mcpl.MCPLFile(out_field).particles)
            assert len(particles) == 100

            neg_uz = 0
            for i, p in enumerate(particles):
                assert p.pdgcode == TEST_PDG_PROTON
                assert math.isfinite(p.ux) and math.isfinite(p.uy) and math.isfinite(p.uz)
                assert np.isclose(p.ux**2 + p.uy**2 + p.uz**2, 1.0), \
                    f"particle {i}: direction not unit length"
                assert math.isfinite(p.x) and math.isfinite(p.y) and math.isfinite(p.z)
                if p.uz < 0.0:
                    neg_uz += 1

            frac_neg = neg_uz / len(particles)
            assert frac_neg >= 0.99, \
                f"Too many upstream directions: {len(particles) - neg_uz}/{len(particles)} have uz >= 0 " \
                f"(frac_neg={frac_neg:.3f})"


class TestSpotlistExport:
    @pytest.mark.parametrize("col_count", [5, 6, 7, 9, 11])
    def test_spotlist_export(self, col_count):
        plan_path = "res/test_plans/temp_160MeV_10x10.dcm"
        bm_path = "res/beam_models/DCPT_beam_model__v2.csv"

        with tempfile.TemporaryDirectory() as td:
            out_path = os.path.join(td, "myspotlist.dat")

            cmd = [
                sys.executable,
                "dicomexport/main_plan_export.py",
                plan_path, out_path,
                f"-b={bm_path}",
                "--export-fmt=spotlist",
                "-v",
                f"-nc={col_count}",
            ]

            env = dict(os.environ)
            env["PYTHONPATH"] = "." + (os.pathsep + env.get("PYTHONPATH", ""))

            result = subprocess.run(
                cmd, env=env,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
            )
            if result.returncode != 0:
                pytest.fail(f"CLI failed\ncmd={cmd}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}")

            out_field = os.path.join(td, "myspotlist_field01.dat")
            assert os.path.exists(out_field), f"Expected output file not found: {out_field}"

            with open(out_field, encoding="utf-8") as f:
                data_lines = [line for line in f if not line.startswith("#") and line.strip()]

            for line in data_lines:
                cols = line.strip().split()
                assert len(cols) == col_count, \
                    f"Line has {len(cols)} columns, expected {col_count}"


class TestSpotlistExport6ColBM:
    def test_spotlist_export_6col_bm(self):
        """6-column beam model should produce an 11-column spotlist with zeros in divergence/correlation columns."""
        plan_path = "res/test_plans/temp_160MeV_10x10.dcm"
        bm_path = "res/beam_models/bm_test_6col.csv"

        with tempfile.TemporaryDirectory() as td:
            out_path = os.path.join(td, "myspotlist.dat")

            cmd = [
                sys.executable,
                "dicomexport/main_plan_export.py",
                plan_path, out_path,
                f"-b={bm_path}",
                "--export-fmt=spotlist",
                "-v", "-nc=11",
            ]

            env = dict(os.environ)
            env["PYTHONPATH"] = "." + (os.pathsep + env.get("PYTHONPATH", ""))

            result = subprocess.run(
                cmd, env=env,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
            )
            if result.returncode != 0:
                pytest.fail(f"CLI failed\ncmd={cmd}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}")

            out_field = os.path.join(td, "myspotlist_field01.dat")
            assert os.path.exists(out_field), f"Expected output file not found: {out_field}"

            with open(out_field, encoding="utf-8") as f:
                data_lines = [line for line in f if not line.startswith("#") and line.strip()]

            for line in data_lines:
                cols = line.strip().split()
                assert len(cols) == 11, f"Line has {len(cols)} columns, expected 11"
                for i in range(6, 10):
                    assert cols[i] == "0", \
                        f"Expected column {i + 1} to be 0 for 6-column beam model input"
