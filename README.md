# DicomExport

[![CI](https://github.com/nbassler/dicomexport/actions/workflows/ci.yml/badge.svg)](https://github.com/nbassler/dicomexport/actions/workflows/ci.yml)
[![Lint](https://github.com/nbassler/dicomexport/actions/workflows/lint.yml/badge.svg)](https://github.com/nbassler/dicomexport/actions/workflows/lint.yml)
[![CodeQL](https://github.com/nbassler/dicomexport/actions/workflows/codeql.yml/badge.svg)](https://github.com/nbassler/dicomexport/actions/workflows/codeql.yml)
[![Build Binaries](https://github.com/nbassler/dicomexport/actions/workflows/build-windows.yml/badge.svg)](https://github.com/nbassler/dicomexport/actions/workflows/build-windows.yml)
[![Dependabot](https://img.shields.io/badge/dependabot-enabled-025e8c?logo=dependabot)](https://github.com/nbassler/dicomexport/network/updates)

DicomExport turns DICOM proton therapy data into input for Monte Carlo codes:

- **TOPAS input files** for a whole study: the CT as the patient, the RT Ion Plan as the
  beam, dose scored on the RTDOSE grid. One file per field.
- **MCPL phase-space files** from a plan.
- **Spot lists** from a plan, for FLUKA (`SOURCE` card) or SHIELD-HIT12A (`USECBEAM` card).

## Installation

```bash
pip install dicomexport            # command-line tools
pip install "dicomexport[gui]"     # plus the desktop GUI (Qt)
pip install "dicomexport[web]"     # plus the web UI (Streamlit)
```

Each [release](https://github.com/nbassler/dicomexport/releases) also has standalone
builds: a Windows zip with the GUI and the command-line tool, and a Linux archive with the
command-line tool. Keep the `defaults/` folder next to the executables.

## Commands

| Command | Input | Output |
| --- | --- | --- |
| `dicomexport` | study directory: CT, RTSTRUCT, RT Ion Plan, RTDOSE | one TOPAS input file per field |
| `plan-export` | RT Ion Plan, or IBA `.pld` | TOPAS beam definition, MCPL, or spot list |
| `geo-export` | CT directory and RTSTRUCT | TOPAS patient geometry only |
| `dicomexport-gui` | | desktop GUI for `dicomexport` |
| `streamlit run dicomexport/gui/app.py` | | web UI for `dicomexport` |

Every command has `--help`.

## Quick start

From a clone of this repository, which includes a test study:

```bash
dicomexport res/test_studies/DCPT_headphantom/
```

This writes `topas_field01.txt` to `topas_field03.txt`, one per field of the plan, and
warns that it used the example data shipped with dicomexport (see Configuration). Run
TOPAS on them from the same directory: the files refer to the study with the paths
given on the command line.

## Configuration: beam models, tables and range shifters

Besides the DICOM study, an export needs:

- a **beam model** (`-b`): the beam's energy spectrum, spot size and divergence per
  energy, at a plane upstream of the isocenter;
- a **CT-number-to-material table** for TOPAS (`-s` or `-S`, see Including TOPAS files),
  which must expect what the CT holds, usually Hounsfield units;
- for plans with a range shifter, the shifter's **thickness and material**, which DICOM
  does not contain.

dicomexport ships examples of all three, so it runs straight after installation: DCPT's
beam models, the OpenTOPAS example table, and range shifters from four centres. **They are
not your site's data**, and dicomexport warns whenever it uses them.

A site keeps its own data in a configuration directory:

```bash
dicomexport --init-config /etc/dicomexport   # start from a copy of the examples; never overwrites
dicomexport --list-config                    # which directory is in effect, and what it offers
```

dicomexport uses the first of these that exists, and only that one:

1. `--config-dir DIR`
2. `$DICOMEXPORT_CONFIG_DIR`
3. `~/.config/dicomexport` (`%APPDATA%\dicomexport` on Windows)
4. `/etc/dicomexport` (not on Windows)
5. the examples shipped with dicomexport

`-b`, `-s` and `-S` take a file, or the name of one in the configuration directory, such as
`-b DCPT_beam_model__v5`. The beam model and the table may be omitted when the directory
leaves no choice. Every TOPAS file records in its header which directory, beam model,
included files and range-shifter catalog it was made with. Upgrades never touch a site's
directory.

The `README.md` in [`dicomexport/defaults/`](dicomexport/defaults/) (also copied into every
site's directory) describes the layout, the file formats and the rules. The beam model
format is described in [`dicomexport/defaults/beam_models/`](dicomexport/defaults/beam_models/),
the tables in [`dicomexport/defaults/ct_to_material/`](dicomexport/defaults/ct_to_material/).

## TOPAS export

The input files are written for OpenTOPAS 4.3 and need OpenTOPAS 4.2 or later. For an
older version, pass `--topas-version X.Y`.

- **Beam geometry.** The beam model position is read from the `BMODPOS` key in the beam
  model's header, or given with `-p` (mm upstream of the isocenter). `--nozzle-side neg-z`,
  the default, follows IEC 61217: at gantry 0 the beam enters a head-first-supine patient
  from the anterior side. `pos-z` mirrors every field through the isocenter and is meant
  only for research setups without a patient; dicomexport warns when it is used.
- **Spots.** By default each spot is its own source and a field is a single Geant4 run
  (`--spot-mode sources`), split into identical batches (`--batches`, default 10) for
  statistical uncertainties. `--spot-mode timefeature` steps one source through the spots
  instead. `-N` sets the total number of protons per field.
- **Dose.** Dose to water is scored on the grid of the study's RTDOSE file and written as a
  DICOM dose cube, at 32 bits per pixel (`--dose-cube-16bit` halves the size but zeroes the
  lowest doses).
- **Threads.** `--threads` sets TOPAS's thread count, resolved on the machine that runs the
  file, so exporting on one machine and running on another is safe.
- **Fields.** `-f N` exports only the field with DICOM BeamNumber N.

### Including TOPAS files

`-s FILE` includes a TOPAS parameter file by path, as an `includeFile` line. `-S FILE`
pastes the UTF-8 file into each TOPAS field file. TOPAS interprets the parameters. Both
options may be repeated and mixed, and the files keep their command-line order.

The usual file is the CT-number-to-material table, and without any `-s` or `-S` the
configuration directory's only table is included. Any other TOPAS code can be added the same
way, such as extra scorers or material definitions; once you give `-s` or `-S`, name the
table too.

- **Paths.** A bare name is looked up in `ct_to_material/` of the configuration directory
  and written as an absolute path. Any other path given to `-s` is written exactly as given,
  so it may name a file that exists only where TOPAS runs. With `-S`, the named file must
  exist at export time. Any nested `includeFile` directives and other file references
  still resolve when TOPAS runs.
- **Pasted files** are marked, so other tools can find them:

  ```text
  # BEGIN INCLUDE_INLINE: <path> sha256=<checksum of the file>
  ...the original UTF-8 bytes followed by one LF...
  # END INCLUDE_INLINE: <path>
  ```

  To recover or verify the original bytes, read the block as bytes and remove exactly one
  LF immediately before the end marker. The SHA-256 covers the original file bytes.
- **How TOPAS handles conflicts.** For compatible parameter definitions, the including
  file's value takes precedence. When two include chains resolve a parameter to different
  definitions, TOPAS requires an absolute definition in the file that joins them.
  An explicit value in one chain can conflict with a built-in default inherited by
  another. TOPAS normally rejects duplicate definitions in the same file. OpenTOPAS
  4.3.0 keeps the last definition for names beginning with `Ma/PatientTissue`.

## Plan-only export

`plan-export` reads a plan without CT. The same `-b`, `--config-dir` and range-shifter rules
apply.

A 7-column spot list:

```bash
plan-export --export-fmt spotlist -nc 7 res/test_plans/temp_sobp_10x10.dcm sobp.txt
```

An [MCPL](https://mctools.github.io/mcpl/) phase space with a million protons, one file per
field (`temp_sobp_10x10_field01.mcpl`, ...):

```bash
plan-export --export-fmt mcpl -N 1000000 res/test_plans/temp_sobp_10x10.dcm temp_sobp_10x10.mcpl
```

### MCPL coordinate frame

The phase space is **frame-relative (pre-gantry)**: no gantry or couch rotation is applied.
The receiving Monte Carlo code places it at the nozzle and applies the gantry transform, so
`--nozzle-side` does not apply to MCPL export.

By default (`--mcpl-frame iec`) the frame is the IEC 61217 gantry frame:

- axes: `X = Xg`, `Y = Yg`, `Z = Zg`;
- the source plane is at `+D`, the beam model position upstream of the isocenter;
- the beam travels toward **−Z**;
- the isocenter is at the origin.

`--mcpl-frame rotx180` rotates the whole phase space by 180° about X, so the beam travels
toward **+Z** with the source at `−D`. A rotation cannot reverse Z alone, so this **flips
the sign of Y**; the beam optics are preserved. Use it for codes that expect a beam moving
toward +Z.

## Development

```bash
git clone https://github.com/nbassler/dicomexport.git
cd dicomexport
pip install -e ".[dev,gui,web]"
pytest
ruff check .
```

`res/` holds test data: studies, plans, a test beam model and an SPR-encoded table. See
[CONTRIBUTING.md](CONTRIBUTING.md).

## Acknowledgements

This work is part of the [SONORA project](https://pianoforte-partnership.eu/sonora/), which has received funding from the European Union's EURATOM research and innovation programme under grant agreement No 101061037 ([PIANOFORTE](https://pianoforte-partnership.eu/) - European Partnership for Radiation Protection Research).
