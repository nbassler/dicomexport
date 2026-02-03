import mcpl
import subprocess
import tempfile
import math
import sys
import os
import unittest

import numpy as np

from dicomexport.model_plan import Plan

TEST_PDG_PROTON = 2212


class TestPlan(unittest.TestCase):
    def test_plan_initialization(self):
        p = Plan()
        self.assertIsInstance(p, Plan)
        self.assertEqual(p.scaling, 1.0)
        self.assertEqual(p.n_fields, 0)

    def test_plan_fields_list(self):
        p = Plan()
        self.assertIsInstance(p.fields, list)
        self.assertEqual(len(p.fields), 0)


class TestMCPLExport(unittest.TestCase):
    def test_mcpl_export_roundtrip_100(self):
        plan_path = "res/test_plans/temp_160MeV_10x10.dcm"
        bm_path = "res/beam_models/DCPT_beam_model__v2.csv"

        with tempfile.TemporaryDirectory() as td:
            out_path = os.path.join(td, "myoutput.mcpl")

            cmd = [
                sys.executable,
                "dicomexport/main_plan_export.py",
                plan_path,
                out_path,
                f"-b={bm_path}",
                "--export-fmt=mcpl",
                "-v",
                "-N=100",
            ]

            env = dict(os.environ)
            env["PYTHONPATH"] = "." + (os.pathsep + env["PYTHONPATH"] if "PYTHONPATH" in env else "")

            subprocess.run(cmd, check=True, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

            out_field = os.path.join(td, "myoutput_field01.mcpl")
            self.assertTrue(os.path.exists(out_field), f"Expected output file not found: {out_field}")

            m = mcpl.MCPLFile(out_field)
            particles = list(m.particles)
            self.assertEqual(len(particles), 100)

            neg_uz = 0
            for i, p in enumerate(particles):
                with self.subTest(particle=i):
                    self.assertEqual(p.pdgcode, TEST_PDG_PROTON)

                    # direction should be finite and ~unit length
                    self.assertTrue(math.isfinite(p.ux) and math.isfinite(p.uy) and math.isfinite(p.uz))
                    u2 = p.ux * p.ux + p.uy * p.uy + p.uz * p.uz
                    self.assertTrue(np.isclose(u2, 1.0), f"|u|^2={u2}")

                    # positions should be finite
                    self.assertTrue(math.isfinite(p.x) and math.isfinite(p.y) and math.isfinite(p.z))

                    if p.uz < 0.0:
                        neg_uz += 1

            frac_neg = neg_uz / len(particles)

            # main physics sanity: beam should go toward -z (downstream)
            self.assertGreaterEqual(
                frac_neg, 0.99,
                f"Unexpected uz >= 0 (upstream) directions: {len(particles)-neg_uz}/{len(particles)} have uz >= 0 "
                f"(frac_neg={frac_neg:.3f})"
            )


if __name__ == "__main__":
    unittest.main()
