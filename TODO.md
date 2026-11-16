# TODO

## Site configuration and material overrides

Design agreed in discussion on 2026-11-16. It replaces the "ordered data layers" design in
#112 and the earlier draft of this file. Comments stating the new design were posted on the
issues the same day (see the end of this file).

Issues: #99 (table fix, **next**), #112 (site data), #94 (material overrides),
#98 (HLUT composition), #102 (range-shifter position).
pregdos side: Eurados/pregdos#128, #126 and #131 (table validation, moved from #100).

Each item below is marked **DECIDED** (agreed with Niels) or **PROPOSED** (suggested in the
discussion, not yet confirmed). Ask before building on a PROPOSED item.

### Principles (DECIDED)

- **dicomexport is a Unix-style tool.** It translates DICOM to TOPAS input and rejects
  arguments that refer to something absent. It holds no policy and does not protect users.
- **dicomexport does not interpret TOPAS parameter files.** It reads DICOM and its own CSV
  files, and it writes TOPAS. A TOPAS file it is given (the CT-number-to-material table,
  `materials.txt`) is passed on or pasted in as text, unread.
- **pregdos does the protecting.** It offers choices from lists, decides who may do what,
  and shows dicomexport's errors as messages.
- **No new configuration language.** Site managers write TOPAS syntax where TOPAS has one,
  and simple CSV for the range-shifter list. No JSON or TOML for humans to edit.
- **Few files, few options.** One file per kind of data. No per-value overrides.

### What was dropped, and why

| Dropped | Reason |
| --- | --- |
| User level | Few users per installation. They share what is added to the site configuration. |
| Ordered layers, labels, merging by name | A pregdos installation serves one site. Its site data is one set of files, edited for that site. |
| `material_catalog.csv` (MaterialID → material) | One more file and a second naming scheme. The override is given by structure name. |
| Per-study binding file | The binding is passed as options. |
| Position column in the range-shifter catalog (#102) | Position comes from the RTPLAN (snout position) and is already handled. |
| Copying files into the output directory | Replaced by `-S`, which writes the table into the TOPAS file. |
| Validating the table in dicomexport (#100) | Would need a TOPAS parser here. pregdos already parses the table. Moved to pregdos#131; #100 is closed. |
| Checking the contents of `materials.txt` | Same reason. No `Ma/`-only restriction and no unknown-material warning. |

### The configuration directory

One directory holds a site's data (DECIDED):

```text
<config-dir>/
    beam_models/*.csv       one is chosen per export
    ct_to_material/*.txt    one is chosen per export
    range_shifters.csv      id, thickness_mm, material[, density_g_cm3]
    materials.txt           TOPAS Ma/ definitions
```

- **DECIDED: one set, never merged.** dicomexport ships a working example set. A site takes
  a copy and edits it. Exactly one directory is in effect for an export.
- **DECIDED: an upgrade never changes a site's copy.** New shipped entries do not appear in
  it by themselves.
- **PROPOSED: location in the repository.** `dicomexport/config/`, inside the package so it
  is in the wheel. `res/` then holds only test data.
- **PROPOSED: option name.** `--config-dir DIR`. Without it, the shipped set is used.
- **PROPOSED: selecting a file.** `-b` and `-s`/`-S` take a file path, or a name looked up in
  the configuration directory. If the option is omitted and the directory holds exactly one
  candidate, that one is used. Otherwise stop and list the choices.
- **PROPOSED: getting a starting copy.** A small command that writes the shipped set into a
  directory, or a documented `cp`. Not decided which.
- **PROPOSED: listing for front ends.** A command that prints what the directory offers
  (beam models, tables, range-shifter IDs, and the path of `materials.txt`) as JSON, so
  pregdos builds its choices without knowing the layout. JSON is output only; nobody edits
  it. Material names are not listed, because that would mean reading a TOPAS file. pregdos
  reads them from `materials.txt` itself.

### Range shifters (DECIDED)

- The plan's `RangeShifterID` selects the entry. An unknown ID is an error.
- An entry carries thickness, material and optional density. Position is not in it.
- A site changes a shifter by rewriting its whole row under the same ID.
- PROPOSED: the built-in `RS_CATALOG` dict in `model_plan.py` becomes the shipped
  `range_shifters.csv`. The four per-site files in `res/range_shifters/` are then redundant
  and go, and their README moves next to the shipped file.
- PROPOSED: `--range-shifter-catalog FILE` stays and means "use this file in place of the
  one in the configuration directory". That is the present behaviour (replace, not extend).

### CT-number-to-material table: `-s` and `-S` (DECIDED)

- `-s TABLE` writes an `includeFile` line with the path as given. Unchanged from today, so
  the pass-through test from #63 (`test_relative_paths_pass_through_verbatim`) stays valid.
- `-S TABLE` writes the table's contents into each TOPAS field file. No include file is
  needed, and the run directory is self-contained. The two options are mutually exclusive.
- Size is not a concern: TOPAS reads input files of 700 kB and more.
- pregdos will use `-S`.

- DECIDED: the table is pasted as text. dicomexport does not parse it or look for clashes.

To check when implementing `-S`:

- TOPAS is believed to reject a parameter defined twice in one file, where an include is
  silently overridden by the including file. If so, TOPAS reports a clash itself when it
  reads the file, before any geometry is built. The names in `HUtoMaterialSchneider.txt`
  and those written by `topas_text.py` were compared by eye and do not overlap.
  **Neither point has been run in TOPAS.** Confirm with a local run or the integration
  workflow (`.github/workflows/topas-integration.yml`).
- PROPOSED: precede the block with a comment giving the original file name and its SHA-256,
  in a fixed form that pregdos can read back for `run.json`. A checksum needs no parsing.

### Material overrides (#94)

- **DECIDED: definitions are site configuration.** `materials.txt` holds `Ma/…` definitions
  in TOPAS syntax, the same lines site physicists paste into run files today
  (see pregdos#126).
- **DECIDED: the binding is per export.** A structure gets a material through an option.
  PROPOSED form: `--material-override "ROI name=Material"`, repeatable.
- **DECIDED: a structure that is not in the RTSTRUCT is an error.** dicomexport already has
  the ROI names: `main.py` calls `load_rs()`, and `RTStruct.rois` carries `roi_name`.
  No new DICOM parsing is needed for this check.
- dicomexport writes `MaterialByRTStructNames` and `MaterialByRTStructMaterials` itself and
  applies TOPAS's rule to the names (trim, then spaces to underscores; see the notes in #94).
- TOPAS takes the first match when structures overlap. Emit the pairs in the order given on
  the command line, and say so in the help text.
- **DECIDED: the material name is not checked.** dicomexport does not read `materials.txt`
  and cannot know what TOPAS predefines. TOPAS reports an unknown material. pregdos offers
  the names as a list, so its users cannot mistype one.
- **DECIDED: `materials.txt` is pasted into the TOPAS file as text, unread.** Keeping it to
  material definitions is the site manager's responsibility.
- PROPOSED: it is pasted whenever it exists, not only when an override is given. A
  range-shifter entry may also name a site material.
- PROPOSED, later and separate: warn when the RTSTRUCT declares an override
  (`RTROIObservationsSequence`, `MaterialID`, `REL_ELEC_DENSITY`) that no option covers.
  This is the only new RTSTRUCT reading. It must be a warning, not an error: Eclipse writes
  such overrides routinely, for example on couch structures.

### Next: #99, on branch `99-sprtomaterial-brain-set-minimagingvalue`

A data fix in `res/spr_tables/SPRtoMaterial__Brain.txt`. No code changes in the package.

1. Add `i:Ge/Patient/MinImagingValue = -1024`, with a comment saying why: the sections
   start at -1024, TOPAS defaults `MinImagingValue` to -1000, and it reads
   `DensityCorrection[value - MinImagingValue]`.
2. Correct four comments that were inherited from `HUtoMaterialSchneider.txt` and are wrong
   for this file (details in the comment on #99):

   | Line | Present comment | Problem |
   | --- | --- | --- |
   | 8 | "conversion of Hounsfield Units to materials using the Schneider paper" | The axis is SPR, `SPR = (value + 1000) / 1000`. "Schneider" names the TOPAS converter, not the data. |
   | 12 | "Correction Factor for the relative stopping power of Geant4 and the XiO planning system" | All 4096 entries are 1.0. There is no correction. |
   | 15 | "Formula: … HU[-1000,2995] …" | Wrong axis and wrong range. Values run from -1024 to 3071. |
   | 23 | "Define Materials used for HU" | Not HU. |

3. Do **not** change -1024 to -1000 or "fix" the negative density at the bottom of the
   table. Both are deliberate; #99 explains why.
4. The table stays where it is. Whether it ships, and where, belongs to #112 (open point 1).

Facts already checked:

- With `MinImagingValue = -1024` the table satisfies both index rules exactly:
  `sections[0] = -1024`, and `3072 - (-1024) = 4096`, the length of `DensityCorrection`.
- The rules were read from the OpenTOPAS 4.3.0 source
  (`geometry/TsImagingToMaterialSchneider.cc`, lines 90-93, 169-188 and 222). They are
  written out in pregdos#131.
- TOPAS also aborts unless `len(DensityCorrection) == sections[-1] - sections[0]` exactly
  (lines 52-56). With the two index rules this leaves `MinImagingValue == sections[0]` as the
  only valid setting. pregdos#131 says a longer vector is fine; that is wrong and needs a
  correcting comment there.
- `tests/test_main.py`, `tests/test_field_selection.py` and `tests/test_spot_mode.py` pass
  this table as `-s`. They only need the file to exist, so they are unaffected.

Verification:

- OpenTOPAS 4.3.0 is installed on Niels's machine: binary
  `/opt/Topas/OpenTOPAS-install/bin/topas`, source in `/opt/Topas/OpenTOPAS-4.3.0/`.
  Export `res/test_studies/DCPT_headphantom/` with the fixed table and run it with a few
  histories. TOPAS must load the patient without aborting.
- DECIDED and done: `tests/test_spr_tables.py` checks every table in `res/spr_tables/`
  against the TOPAS conditions above, and checks that the table as it was before the fix is
  caught. It parses the tables inside the test suite only; the package still does not.

### Open points

1. **Is the SPR table part of the shipped set?** `res/spr_tables/SPRtoMaterial__Brain.txt`
   expects SPR-encoded images. pregdos removed it for that reason (pregdos#106, #112) and
   takes only HU-indexed tables. Suggestion: ship `HUtoMaterialSchneider.txt` (today only in
   `pregdos/data/ct_to_material/`) and keep the SPR table out of `ct_to_material/`.
2. **#98 (HLUT composition).** Not part of this work. If it comes, it is one more
   subdirectory (`hluts/`) and one option. pregdos takes only finished tables.
3. **#102.** Declining follows from the range-shifter decision, but the requester (NatMoj)
   reports a wrong value in the TPS plan. They need a reply, and perhaps a question about
   what exactly is wrong in their plan.
4. **Version number.** "2.0.0" was chosen for the layered design. `-s` keeps its behaviour,
   so check what is still breaking: `res/` moves, `RS_CATALOG` leaves `model_plan.py`.
5. **`-s` long name.** #98 suggested `--ct-to-material`, with `--spr-to-material` kept as an
   alias. Not discussed again; `-S` needs a long name too.
6. **Report to OpenTOPAS.** The missing bounds check on `DensityCorrection` is a defect in
   TOPAS. Nobody has reported it upstream yet.

### Order of work

1. **#99.** The data fix described above. pregdos#131 (validation) is independent and can
   be done at any time.
2. **Configuration directory (#112).** Move the data into the package, add `--config-dir`,
   name lookup and the listing. Move `RS_CATALOG` to CSV.
3. **`-S`**, with the TOPAS run that confirms how a duplicate parameter behaves.
4. **Material overrides (#94).** `materials.txt` and `--material-override`.
5. **pregdos#128 and #126** (list below).
6. **Warning for declared overrides** (#94, last part).

### Code pointers

| What | Where |
| --- | --- |
| Options of the study exporter | `dicomexport/parser_main.py` |
| `-b` and the range-shifter catalog are shared with | `dicomexport/parser_plan_export.py`, `main_plan_export.py` |
| Built-in catalog and its CSV loader | `dicomexport/model_plan.py` (`RS_CATALOG`, `load_range_shifter_catalog`) |
| Catalog lookup and the unknown-ID error | `dicomexport/import_plan_dicom.py` (`_build_range_shifter`) |
| `includeFile` line for the table | `dicomexport/topas_text.py` (`TopasText.spr_to_material`), called from `export_study_topas.py` |
| Patient geometry block that gains the override lines | `dicomexport/topas_text.py` (`geometry_patient_dicom`, `geometry_patient`) |
| ROI names | `dicomexport/import_rtstruct.py`, `model_rtstruct.py` |
| GUIs list files from `res/` | `dicomexport/gui/utils.py` (`BEAM_MODELS_DIR`, `SPR_TABLES_DIR`) |
| Windows build packs the exe with `res/` | `.github/workflows/build-windows.yml`, `ci.yml` |
| Tests that pin present behaviour | `tests/test_plan.py` (`test_supplied_catalog_replaces_the_builtin`, `test_shipped_catalogs_agree_with_the_builtin`), `tests/test_topas_text.py` (`test_relative_paths_pass_through_verbatim`) |

### pregdos side (pregdos#128, #126, #131)

- Validate the CT-number-to-material table (pregdos#131): read `MinImagingValue`, reject a
  table that indexes `DensityCorrection` out of bounds, and drop the guessed origin in
  `structure_metrics._density_from_hu`.

- One key in `config.toml` for the configuration directory, placed beside
  `/etc/pregdos/config.toml`. Empty means dicomexport's shipped set. Pass it on every
  conversion. The container needs it as a mountable volume.
- Delete `pregdos/data/beam_models/` and `pregdos/data/ct_to_material/` and the code that
  lists them (`_builtin_beam_models`, `_builtin_material_tables` in `webserver.py`). Build
  the setup page from dicomexport's listing.
- Call dicomexport with `-S`. The study directory then needs no copy of the table or the
  beam model: it becomes `dicom/` plus `run_*/`. Update `docs/study_layout.md`.
- Three places read the table through `includeFile` and must read the block from the field
  file instead: `executor._material_table_identity` (checksum for `run.json`),
  `structure_metrics._density_from_hu` (structure mass), and the mask pre-pass input.
- Uploading a one-off beam model or table stays possible: pregdos passes the uploaded file
  as a path.
- Material overrides (pregdos#126): on the setup page the user picks, per structure, a
  material from the names in `materials.txt`. pregdos reads those names from the file
  itself and passes each choice as an option.
- Raise `MINIMUM_DICOMEXPORT`.

### Issue comments

Posted on 2026-11-16: #112, #94, #98, #102, pregdos#128, pregdos#126. #100 was closed with a
pointer to the new pregdos#131.

Still to do:

- **#94 needs a short follow-up.** The posted comment lists two PROPOSED items that were
  dropped afterwards: the `Ma/`-only restriction on `materials.txt`, and the warning for a
  material not defined there. Draft it and have Niels review it before posting.
- **#102** was answered with the reasons only. The issue is still open.
- **pregdos#128** keeps its old title. The comment suggests a new one.
