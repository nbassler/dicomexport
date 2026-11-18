# dicomexport configuration directory

The data dicomexport needs besides the DICOM study:

```text
beam_models/*.csv       beam models, one is chosen per export (-b)
ct_to_material/*.txt    CT-number-to-material tables for TOPAS, included with -s or -S
range_shifters.csv      range shifter catalog, looked up by the plan's RangeShifterID
```

This README is in two places: in the `defaults/` directory shipped inside the installed
dicomexport package, and in every site's copy of it.

**In the shipped `defaults/`, do not edit anything.** It belongs to the installed package and
is replaced on every upgrade. Its files are examples, not your site's calibration: the beam
models are DCPT's, the table is the OpenTOPAS example, and the range shifters are those
dicomexport has met at four centres.

**In a site's copy, edit freely.** Add your beam models and tables, list your range
shifters, remove what does not apply. An upgrade never touches it.

## Setting up a site's configuration directory

```bash
dicomexport --init-config /etc/dicomexport      # or ~/.config/dicomexport, or any directory
```

This copies the shipped defaults into the directory. It never overwrites a file that is
already there, so re-running it after an upgrade only adds files the site does not have yet.

dicomexport uses exactly one configuration directory, never a mix. It takes the first of:

1. `--config-dir DIR`
2. `$DICOMEXPORT_CONFIG_DIR`
3. `~/.config/dicomexport/` (`%APPDATA%\dicomexport\` on Windows)
4. `/etc/dicomexport/` (not on Windows)
5. the shipped `defaults/`

`dicomexport --list-config` shows which one is in effect and what it offers. Every TOPAS file
names the directory and the files it used in its header.

**Choosing files.** `-b`, `-s` and `-S` take a file path, or the name of a file in the
directory in effect, with or without its suffix: `-b DCPT_beam_model__v5`. The beam model
and the table may be omitted when the choice is unambiguous: a directory with exactly one
beam model or one table. `-s` includes the table by path, `-S` pastes it into the TOPAS
file; see dicomexport's README for including other TOPAS files. Only in the
shipped defaults is `DCPT_beam_model__v5.csv` the beam model used without `-b`; a site's
directory with both DCPT models needs `-b`, so dicomexport never picks a calibration on a
site's behalf.

Keeping a site's directory under version control (git) gives every revision of a beam model
or a calibration a history, and a backup.

## Range shifter catalog: `range_shifters.csv`

A range shifter is described in a DICOM RT Ion Plan by an ID, a type and a distance from
the isocenter — but never by a thickness, a material or a density. Those are properties
of the physical device, so dicomexport must look them up in `range_shifters.csv`.

When a plan names a shifter that is not in it, the export stops with a message naming the
ID and the file. Add the shifter to `range_shifters.csv` in the site's configuration
directory, or, for a single run, pass a catalog that lists it:

```bash
dicomexport ... --range-shifter-catalog my_shifters.csv
```

### One catalog per run, never merged

The catalog of the configuration directory in effect is the *complete* set of known
shifters, and a file passed with `--range-shifter-catalog` replaces it. Neither extends
another. This is deliberate:

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

### Format

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

### Density

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

### The shipped catalog

| Site | Shifters |
| --- | --- |
| DCPT, Aarhus | `RS_2CM`, `RS_3CM`, `RS_5CM`: 2, 3 and 5 cm Lexan |
| CCB, Krakow | `RS_Block` |
| Skandionkliniken, Uppsala | `RS_3.5` |
| WPE, Essen | `RS74`, `RS51`, `RS25`, the last two at a stated 1.19 g/cm³ |

Each site's rows carry its provenance as comments in `range_shifters.csv`. Contributions of
further *non-confidential* shifters are welcome as pull requests.

Thicknesses that a centre treats as confidential should stay in a local file and out of
this repository — that is the main reason the interface is a file rather than a
command-line value, which would otherwise end up in shell history and process listings.
