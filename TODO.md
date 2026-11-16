# TODO: dicomexport 2.0.0, site configuration and material overrides

Design agreed with Niels on 2026-11-16. The issues carry comments stating it: #112, #94, #98,
#102, and on the pregdos side Eurados/pregdos#128, #126, #131. Where an issue's original text
disagrees with its later comments or with this file, this file wins.

Items are marked **DECIDED** (agreed with Niels), **PROPOSED** (suggested, not confirmed:
ask before building on it) or **OPEN** (needs a decision).

## Principles (DECIDED)

- **dicomexport is a Unix-style tool.** It translates DICOM to TOPAS input and rejects
  arguments that refer to something absent. It holds no policy and does not protect users.
- **dicomexport does not interpret TOPAS parameter files.** It reads DICOM and its own CSV
  files, and writes TOPAS. A TOPAS file it is given (the CT-number-to-material table,
  `materials.txt`) is passed on or pasted in as text, unread. Table validation is pregdos's
  job (pregdos#131).
- **pregdos does the protecting.** It offers choices from lists, decides who may do what,
  and shows dicomexport's errors as messages.
- **No new configuration language.** TOPAS syntax where TOPAS has one, simple CSV for the
  range shifters. No JSON or TOML for humans to edit.
- **Few files, few options.** One file per kind of data. No per-value overrides. No layers,
  no merging, no per-user level.

## Data layout (DECIDED)

The shipped defaults and a site's configuration directory have the same layout:

```text
beam_models/*.csv       one is chosen per export (-b)
ct_to_material/*.txt    one is chosen per export (-s / -S)
range_shifters.csv      id, thickness_mm, material[, density_g_cm3]
materials.txt           TOPAS Ma/ definitions (#94, not shipped yet)
```

- **`dicomexport/defaults/`** is shipped as package data, so dicomexport runs straight after
  `pip install`. An upgrade replaces it; nobody edits it. `dicomexport/config.py` holds
  `DEFAULTS_DIR`.
- **A site's configuration directory** is a copy of `defaults/` outside the package, edited
  there. An upgrade never touches it, so site data is safe; new shipped entries do not
  reach it by themselves.
- **One directory is in effect, never merged.** dicomexport takes the first that exists:
  1. `--config-dir DIR`
  2. `$DICOMEXPORT_CONFIG_DIR`
  3. `~/.config/dicomexport/` (`%APPDATA%\dicomexport\` on Windows)
  4. `/etc/dicomexport/` (Linux)
  5. the shipped `defaults/`

  The directory in effect is logged and named in the header of each TOPAS file.
- **Range shifters:** the plan's `RangeShifterID` selects the row; an unknown ID stops the
  export. A row is thickness, material, optional density; the position comes from the plan.
  A site changes a shifter by rewriting its whole row. `--range-shifter-catalog FILE`
  replaces the catalog of the directory in effect (replace, not extend).
- **CT-number-to-material table:** `-s TABLE` writes an `includeFile` line with the path as
  given (unchanged, #63). `-S TABLE` pastes the table into each TOPAS field file as text, so
  the run directory needs no include file. Mutually exclusive. pregdos will use `-S`.

## Remaining work, in order

#112 is done in three steps, one pull request each, so each can be reviewed and merged on
its own.

### 1. #112, step 1: ship the data (done on a branch, no pull request yet)

On branch `112-site-data-directory-built-in-defaults-for-beam-models-hu-tables-and-catalogs-extended-and-overridden-per-site`.
`dicomexport/defaults/` with beam models v2 and v5, `HUtoMaterialSchneider.txt` and
`range_shifters.csv` (replacing the `RS_CATALOG` dict); GUIs and PyInstaller builds read
it; `res/` holds only test data. CLI unchanged. All tests pass; a wheel built from it was
installed outside the repository and exported the head phantom.

Still to do: commit, push, open the pull request. **The PyInstaller builds are untested** (each now
has `--add-data` for `defaults/`, `;` on Windows, `:` on Linux): check the CI build jobs.

### 2. #112, step 2: the configuration directory

- The search order above, in `dicomexport/config.py`. Log the directory in effect and name
  it in the TOPAS file header.
- **DECIDED: `-b` may be omitted.** In the shipped `defaults/` it means
  `DCPT_beam_model__v5.csv`, named once in the code. In a site's directory only when it holds
  exactly one beam model; otherwise stop and list the names. The code default never applies
  to a site's directory.
- PROPOSED: `-b` and `-s`/`-S` also take a name, looked up in the directory in effect. The
  same "exactly one, or stop and list" rule for tables.
- **OPEN: the starting copy.** It must never overwrite existing files (DECIDED). Either a
  documented `cp -rn` plus how to find the installed package path, or a small command that
  copies only missing files, lists what it skipped, and also works on Windows. Re-running it
  after an upgrade adds new shipped files and leaves edited ones alone.
- PROPOSED: a listing command that prints, as JSON, what the directory in effect offers:
  its path, beam models, tables, range-shifter IDs, the path of `materials.txt`. Not the
  material names, which would mean reading a TOPAS file.
- PROPOSED: make no release between step 1 and step 2. Until step 2 the GUIs list only
  `defaults/`, so a GUI user has no safe place for a table of their own.
- Update the GUIs to list the directory in effect instead of `defaults/`.

### 3. #112, step 3: `-S`

- Paste the table as text, unread. No parsing, no clash detection.
- **Check in TOPAS first:** TOPAS is believed to reject a parameter defined twice in one file
  (an include is overridden silently instead). The names in `HUtoMaterialSchneider.txt` and
  those written by `topas_text.py` were compared by eye and do not overlap. Neither point has
  been run. OpenTOPAS 4.3.0 is installed locally: `/opt/Topas/OpenTOPAS-install/bin/topas`,
  source in `/opt/Topas/OpenTOPAS-4.3.0/`.
- PROPOSED: precede the block with a comment giving the original file name and its SHA-256,
  in a fixed form that pregdos can read back. Mark the end of the block too, so pregdos can
  cut it out (see the pregdos section).

### 4. #94: material overrides

- **DECIDED:** `materials.txt` in the directory in effect holds `Ma/…` definitions in TOPAS
  syntax. It is pasted into the TOPAS file as text, unread.
- **DECIDED:** the binding is per export, by structure name. PROPOSED form:
  `--material-override "ROI name=Material"`, repeatable.
- **DECIDED:** a structure that is not in the RTSTRUCT is an error. The ROI names are already
  loaded (`load_rs()`, `RTStruct.rois`); no new DICOM parsing.
- **DECIDED:** the material name is not checked. TOPAS reports an unknown material.
- dicomexport writes `MaterialByRTStructNames` and `MaterialByRTStructMaterials`, applying
  TOPAS's name rule (trim, then spaces to underscores; details in #94).
- TOPAS takes the first match when structures overlap: emit the pairs in command-line order
  and say so in the help text.
- PROPOSED: paste `materials.txt` whenever it exists, not only with an override, since a
  range-shifter row may name a site material.

### 5. #94, last part: warn about declared overrides

PROPOSED: warn when the RTSTRUCT declares an override (`RTROIObservationsSequence`,
`MaterialID`, `REL_ELEC_DENSITY`) that no option covers. A warning, not an error: Eclipse
writes such overrides routinely, for example on couch structures.

## Open questions

1. **Version number.** 2.0.0 is planned. Breaking so far: `RS_CATALOG` is gone from
   `dicomexport.model_plan` (now `default_range_shifter_catalog()`), and the beam models and
   range-shifter files moved out of `res/`.
2. **Long option names.** `-s` is `--spr-to-material`, which is wrong for an HU table. #98
   suggested `--ct-to-material` with the old name kept as an alias. `-S` needs a long name.
3. **#102** was answered with the reasons for declining and is still open. Close it, or wait
   for the requester.
4. **#98 (HLUT composition)** is not part of this work. If it comes, it is one more
   subdirectory (`hluts/`) and one option.
5. **Report to OpenTOPAS** that `DensityCorrection` is read without a bounds check
   (`TsImagingToMaterialSchneider.cc:222`). Nobody has reported it yet.

## Code pointers

| What | Where |
| --- | --- |
| Options of the study exporter | `dicomexport/parser_main.py` |
| `-b` and the range-shifter catalog are shared with | `dicomexport/parser_plan_export.py`, `main_plan_export.py` |
| Shipped data and where it is | `dicomexport/defaults/`, `dicomexport/config.py` |
| Default catalog and the CSV loader | `dicomexport/model_plan.py` (`default_range_shifter_catalog`, `load_range_shifter_catalog`) |
| Catalog lookup and the unknown-ID error | `dicomexport/import_plan_dicom.py` (`_build_range_shifter`) |
| `includeFile` line for the table | `dicomexport/topas_text.py` (`TopasText.spr_to_material`), called from `export_study_topas.py` |
| Patient block that gains the override lines | `dicomexport/topas_text.py` (`geometry_patient_dicom`, `geometry_patient`) |
| ROI names | `dicomexport/import_rtstruct.py`, `model_rtstruct.py` |
| GUIs list data files | `dicomexport/gui/utils.py` |
| PyInstaller builds | `.github/workflows/build-windows.yml`, `ci.yml` |
| Wheel contents | `pyproject.toml` `[tool.setuptools.package-data]`; `tests/test_defaults.py` fails if a file in `defaults/` is not covered |
| Table index rules, reference implementation | `tests/test_spr_tables.py` (`index_problems`) |
| Tests that pin present behaviour | `tests/test_plan.py` (`test_default_catalog_contents`), `tests/test_topas_text.py` (`test_relative_paths_pass_through_verbatim`) |

## For pregdos: migrating to dicomexport 2.0.0

Written for whoever, human or AI, adapts pregdos (Eurados/pregdos#128, #126, #131).
Items marked PROPOSED or OPEN above may have changed by the time 2.0.0 is released: check
dicomexport's `--help` and release notes before coding against an option name or format.

### What pregdos must change

- **Raise `MINIMUM_DICOMEXPORT`** in `pregdos/versions.py` to 2.0.0.
- **Configuration directory.** Add one key to pregdos's `config.toml` (`[paths]`) for the
  site's dicomexport configuration directory, document it in `config.toml.example` and the
  installation docs, and make it a mountable volume in the container.
  - **Always pass it explicitly as `--config-dir` when set.** Do not rely on dicomexport's
    search order from a service: it would look in the service account's `~/.config` and in
    `/etc/dicomexport/`, which another installation on the same host may own.
  - When the key is empty, dicomexport uses its shipped defaults (or whatever the search
    order finds). Either way, **record the directory in effect with each run** in
    `run.json` (it is in the TOPAS file header, and in the listing).
  - If pregdos's RPM/DEB packages (pregdos#86) ever install such a directory, mark its files
    as configuration (`%config(noreplace)`), so a package upgrade never replaces site data.
- **Delete pregdos's own copies:** `pregdos/data/beam_models/`, `pregdos/data/ct_to_material/`,
  and `_builtin_beam_models()` / `_builtin_material_tables()` in `webserver.py`. dicomexport
  ships the same data: the beam models are numerically identical (dicomexport's are the
  cleaned-up copies), the HU table is identical to the OpenTOPAS 4.3.0 example.
- **Build the setup page's choices from dicomexport's listing** (PROPOSED in step 2), not from
  pregdos's package data. pregdos still offers both beam models; it should keep passing
  `-b` explicitly, since a site's directory with more than one beam model requires it.
- **Range shifters need no UI.** pregdos never passed `--range-shifter-catalog`, so every run
  used the shipped catalog. With `--config-dir`, the site's `range_shifters.csv` is used
  automatically. An unknown ID makes dicomexport exit non-zero with a message naming it:
  show that message.
- **Switch from `-s` to `-S`** (step 3). The study directory then needs no copy of the table or
  the beam model, and becomes `dicom/` plus `run_*/`. Update `docs/study_layout.md`.
- **Uploads of a one-off beam model or table stay possible:** pass the uploaded file's path.

### Pitfalls

- **Three places read the table through the `includeFile` line**, which `-S` removes:
  - `executor._material_table_identity`: the checksum for `run.json`. Read the name and
    SHA-256 from the comment dicomexport writes above the pasted block (PROPOSED, step 3).
  - `structure_metrics._density_from_hu`: structure mass. Parse the pasted block from the
    field file instead of the included file.
  - **The mask pre-pass** (`structure_metrics.py`, the parameter list around line 97) copies
    `includeFile` from a field file into its own TOPAS file. With `-S` there is no such line:
    it must copy the whole pasted block, or the pre-pass runs without a material table.
- **Table validation is pregdos's job** (pregdos#131), and the rule is stricter than first
  stated: TOPAS aborts unless `len(DensityCorrection) == sections[-1] - sections[0]`, and
  reads out of bounds unless `MinImagingValue == sections[0]` (`MinImagingValue` defaults
  to -1000). `index_problems()` in dicomexport's `tests/test_spr_tables.py` is a tested
  reference implementation; it handles vectors over several lines and a trailing unit.
  Validate when a table is uploaded or chosen, not when a run is submitted.
- **Relative paths (#63) still pass through verbatim.** `DicomDirectory` stays relative when
  pregdos passes it relative. With `-S`, the only path left in a field file is the DICOM
  directory. A table chosen from the configuration directory with `-s` would be an absolute
  path into it, which is one more reason to use `-S`.
- **Material overrides (pregdos#126)**, after #94:
  - pregdos reads the material names from `materials.txt` itself (the `Ma/<name>/` prefixes);
    dicomexport does not list them.
  - Pass one `--material-override "ROI name=Material"` per choice (PROPOSED form), in the
    order of precedence: TOPAS takes the first match for overlapping structures.
  - A structure missing from the RTSTRUCT is a dicomexport error. An unknown material is
    **not** caught by dicomexport: TOPAS aborts at run time, on the compute node. Offer only
    names from `materials.txt` (or known Geant4 names) so this cannot happen.
  - The override structures do not need to be among the scored structures.
- **No SPR table ships any more.** pregdos takes HU tables only, as before.
