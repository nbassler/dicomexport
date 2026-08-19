# Range shifter catalogs

A range shifter is described in a DICOM RT Ion Plan by an ID, a type and a distance from
the isocenter — but never by a thickness or a material. Those are properties of the
physical device, so dicomexport must look them up.

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
# id, thickness [mm], material
RS_5CM,50.0,Lexan
```

| Column | Meaning |
| --- | --- |
| `id` | `RangeShifterID` (300A,0318) exactly as written in the plan. Case-sensitive. |
| `thickness` | Physical thickness along the beam, in mm — **not** water-equivalent thickness. |
| `material` | Material name passed through to the Monte Carlo code, e.g. `Lexan`. |

**Never infer a thickness from an ID.** The names are site-local and inconsistent:
`RS_2CM`/`RS_3CM`/`RS_5CM` are physical centimetres, but Skandion's `RS_3.5` is 30.62 mm
of Lexan because the name quotes a water-equivalent thickness instead.

Some plans also carry `RangeShifterWaterEquivalentThickness` (300A,0366) per control
point. dicomexport records it when present, but never derives the physical thickness
from it. That conversion needs a stopping-power assumption, and the tag is not reliable:
DCPT's `RS_5CM` reports a WET/thickness ratio of 1.14, consistent with Lexan, while
CCB's `RS_Block` reports 1.05 for the same material. CCB have validated their
calculations against the catalogued 39.936 mm, so it is the DICOM value that is
suspect — and a WET-derived fallback would have silently overridden a good number
with a bad one.

## Files here

| File | Site | |
| --- | --- | --- |
| `rs_dcpt.csv` | DCPT, Aarhus | 2, 3 and 5 cm Lexan |
| `rs_ccb.csv` | CCB, Krakow | `RS_Block` |
| `rs_skandion.csv` | Skandionkliniken, Uppsala | `RS_3.5` |
| `rs_wpe.csv` | WPE, Essen | `RS51` — **provisional thickness, not confirmed by the centre.** |

These mirror the built-in catalog exactly — it is the union of the four — so they double
as worked examples, and a test asserts they cannot drift apart. Contributions of further
*non-confidential* shifters are welcome as pull requests.

`RS51` is the one entry not established by its centre: 51 mm is assumed from the ID, and
the plans carrying it report no water-equivalent thickness to check against. It is in the
built-in catalog, so it resolves by default — see the note in `rs_wpe.csv` before relying
on a range computed with it.

Thicknesses that a centre treats as confidential should stay in a local file and out of
this repository — that is the main reason the interface is a file rather than a
command-line value, which would otherwise end up in shell history and process listings.
