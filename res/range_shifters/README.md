# Range shifter catalogs

A range shifter is described in a DICOM RT Ion Plan by an ID, a type and a distance from
the isocenter — but never by a thickness, a material or a density. Those are properties
of the physical device, so dicomexport must look them up.

dicomexport carries a small built-in catalog (`RS_CATALOG` in `dicomexport/model_plan.py`)
covering the shifters it has met so far. When a plan names a shifter that is not in it,
supply your own catalog:

```bash
dicomexport ... --range-shifter-catalog res/range_shifters/rs_dcpt.csv
```

## The file replaces the built-in catalog, it does not extend it

Whatever the file defines is the *complete* set of known shifters for that run. This is
deliberate:

- an export then depends on exactly one source, so two dicomexport releases cannot give
  different geometry from the same inputs;
- IDs are site-local labels with no shared registry, so merging invites a silent
  collision between your `RS_2CM` and someone else's.

The practical consequence: list every shifter your plan uses, not only the one that was
missing. A plan can use different shifters on different fields — at DCPT a plan may have
one field with no shifter, one with 3 cm and one with 5 cm — and all of them must be in
the file.

`RangeShifterID` values of `None`, meaning no shifter, always resolve and never need to
be listed.

## Format

Comma-separated, one shifter per row, `#` starts a comment:

```csv
# id, thickness [mm], material, density [g/cm3] (optional)
RS_5CM,50.0,Lexan
RS51,44.4,Lexan,1.19
```

| Column | Meaning |
| --- | --- |
| `id` | `RangeShifterID` (300A,0318) exactly as written in the plan. Case-sensitive. |
| `thickness` | Physical thickness along the beam, in mm — **not** water-equivalent thickness. |
| `material` | Material name passed through to the Monte Carlo code, e.g. `Lexan`. Required — a shifter with no material cannot be exported, so an empty one is rejected when the file is read rather than at export time. |
| `density` | *Optional.* Density of that material in g/cm³. Leave empty, or omit the column entirely, to use the density the Monte Carlo code has tabulated for the material. |

Three-column files stay valid; the density column was added later.

**Never infer a thickness from an ID.** The names are site-local and inconsistent:
`RS_2CM`/`RS_3CM`/`RS_5CM` are physical centimetres, but Skandion's `RS_3.5` is 30.62 mm
of Lexan because the name quotes a water-equivalent thickness instead, and WPE's `RS51`
is 44.4 mm.

Some plans also carry `RangeShifterWaterEquivalentThickness` (300A,0366) per control
point. dicomexport records it when present, but never derives the physical thickness
from it: that conversion needs a stopping-power assumption, and now also a density, both
of which the tag leaves you to guess. It is useful as a *check* — DCPT's `RS_5CM` gives a
WET/thickness ratio of 1.14 and CCB's `RS_Block` 1.15, both consistent with Lexan — but a
ratio far from the material's own is a sign that the catalogued thickness is wrong, not a
number to compute with.

## Density

Nominally identical plastic is not cast at an identical density. WPE's `RS51` and `RS25`
are Lexan at 1.19 g/cm³, where the ICRU/NIST tabulation gives 1.20 — a 1% difference in
density is a 1% difference in stopping power, which is worth carrying through to a range
calculation. So the column exists for a density a centre *states*, and for nothing else.

Leave it empty when the centre says nothing. TOPAS materials carry their own density and
nothing rescales one in place, so a stated density makes the exporter define a variant
material next to the range shifter geometry:

```
b:Ma/RangeShifterLexan/BuildFromMaterials = "True"
sv:Ma/RangeShifterLexan/Components        = 1 "Lexan"
uv:Ma/RangeShifterLexan/Fractions         = 1 1.0
d:Ma/RangeShifterLexan/Density            = 1.1900 g/cm3
d:Ma/RangeShifterLexan/MeanExcitationEnergy = 1.0 * Ma/Lexan/MeanExcitationEnergy eV
s:Ge/RangeShifter/Material                = "RangeShifterLexan"
```

That last line is not decoration. A material rebuilt with `BuildFromMaterials` does **not**
inherit the mean excitation energy of the material it was built from — Geant4 recomputes
`I` from the elements, which for Lexan gives 71.71 eV against the tabulated 73.1. Measured
with TOPAS 4.2.p3, 2000 protons of 100 MeV through 44.4 mm of Lexan, scoring the residual
energy that reaches a downstream absorber:

| slab material | residual energy [MeV] |
| --- | --- |
| `Lexan`, i.e. 1.20 g/cm³ | 102019.8 |
| rebuilt at 1.19, `I` recomputed | 102719.5 |
| rebuilt at 1.19, `I` carried over | 102946.6 |

Losing `I` moves stopping power ~0.3% in the *same* direction as the 1% density change, so
it silently ate a quarter of the effect being modelled. Referencing the base material's
parameter fixes it and keeps the variant correct if the base is ever revised: rebuilding
at the tabulated 1.20 g/cm³ then reproduces plain `Lexan` to six significant figures.

**This does not work for NIST materials.** A `G4_`-prefixed material has no `Ma/`
parameters to point at, so `I` cannot be recovered — for `G4_WATER` the recomputation
costs ~1%. dicomexport warns when a density override names one. If you need a density
override on a NIST material, define the material yourself with an explicit
`MeanExcitationEnergy` and name *that* in the catalog.

## Files here

| File | Site | |
| --- | --- | --- |
| `rs_dcpt.csv` | DCPT, Aarhus | 2, 3 and 5 cm Lexan |
| `rs_ccb.csv` | CCB, Krakow | `RS_Block` |
| `rs_skandion.csv` | Skandionkliniken, Uppsala | `RS_3.5` |
| `rs_wpe.csv` | WPE, Essen | `RS74`, `RS51`, `RS25` — the last two at a stated 1.19 g/cm³ |

These mirror the built-in catalog exactly — it is the union of the four — so they double
as worked examples, and a test asserts they cannot drift apart. Contributions of further
*non-confidential* shifters are welcome as pull requests.

Thicknesses that a centre treats as confidential should stay in a local file and out of
this repository — that is the main reason the interface is a file rather than a
command-line value, which would otherwise end up in shell history and process listings.
