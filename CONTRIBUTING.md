# Contributing

## Getting started

Clone the repository and install in editable mode with all test dependencies:

```bash
pip install -e ".[test]"
```

Run the test suite:

```bash
pytest
```

---

## Beam-direction integration test

### Background

The `plan-export --test-mode` flag generates a **self-contained** Topas input file for verifying beam direction — no DICOM CT or patient geometry is needed. It produces:

- A 400 × 400 × 400 mm water box (`IsoBox`) centred at the IEC isocenter (World origin).
- A `DoseToWater` scorer on `IsoBox` that writes `isocenter_scorer.csv`.
- The complete gantry / couch / DCM-to-IEC coordinate frame.

This catches a beam that misses the isocenter entirely (e.g. a sign error in `BeamPosition/TransZ` combined with a wrong `RotY`): if the beam goes nowhere near the isocenter, the scorer records zero dose.

It does **not** catch a beam that is mirrored to the opposite side of the isocenter, since both directions still converge there — that was issue #66. The side the beam enters from is covered by `tests/test_topas_beam_direction.py`, which runs automatically under `pytest` when a `topas` executable is on `PATH` and is skipped otherwise.

### Running the test locally

**1. Generate the Topas input:**

```bash
plan-export res/test_plans/temp_160MeV_10x10.dcm topas_beamcheck.txt \
  -b res/beam_models/DCPT_beam_model__v2.csv \
  --test-mode -N 1000 -f 1
```

**2. Run the simulation with the [OpenTOPAS](https://github.com/OpenTOPAS/OpenTOPAS) Docker image:**

```bash
docker run --rm \
  -v "$PWD":/work \
  -w /work \
  opentopasmcpro/opentopas:latest \
  topas topas_beamcheck_field01.txt
```

**3. Check the result:**

```bash
python tests/check_isocenter.py
# exits 0 if dose > 0 at isocenter
# exits 1 and prints an error if all voxels are zero (beam missed)
```

### Running via GitHub Actions

The workflow is defined in `.github/workflows/topas-integration.yml` and is **manual-trigger only** (not run on every commit, due to the size of the Docker image). Trigger it from the _Actions_ tab → _Topas beam-direction check_ → _Run workflow_.

### Notes

- `--test-mode` is only available on `plan-export`, not on the full study export (`dicomexport`).
- Do **not** combine a `--test-mode` output file with a separately generated DICOM patient geometry in one Topas run — the `IsoBox` water volume and the DICOM patient volume would overlap and cause Topas geometry errors.
