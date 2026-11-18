# TODO: dicomexport 2.0.0

Site configuration (#112) and material overrides (#94). Design agreed with Niels on
2026-11-16. The issues carry comments stating it: #112, #94, #98, #102, and on the pregdos
side Eurados/pregdos#128, #126, #131. Where an issue disagrees with this file, this file
wins.

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

## Done

- **#99** (PR #124): `MinImagingValue` in the SPR test table; `tests/test_spr_tables.py`.
- **#112 step 1** (PR #125): `dicomexport/defaults/` shipped as package data, and beside the
  executables in the standalone builds.
- **#112 step 2** (PR #126): the configuration directory and its search order,
  `--init-config`, `--list-config [text|json]`, `-b`/`-s` by name or path, the data sources
  in the TOPAS header. The user-facing rules are in `dicomexport/defaults/README.md`.

## Remaining work, in order

### 1. #112 step 3: `-s` / `-S` as general includes (branch `112-step3`, not committed)

**DECIDED (2026-11-17):** `-s FILE` / `--include FILE` includes a TOPAS file by path,
`-S FILE` / `--include-inline FILE` pastes it. Both are repeatable and mixed in command-line
order, and TOPAS interprets the parameters. The CT-number-to-material table is just the usual
file: without any `-s`/`-S` the configuration directory's only table is included, and once
any is given, nothing is added implicitly. `--spr-to-material` is gone, with no alias.
Free TOPAS code is therefore possible, which reverses what pregdos#126 was told.

Built:
- `config.Include`, `ConfigDir.include()` / `default_include()`; `parser_config.add_includes()`
  keeps `-s` and `-S` in one ordered list; `TopasText.includes()` writes them.
- A bare name is looked up in `ct_to_material/` and written absolute; any other `-s` path is
  written as given. `-S` reads the file and fails (exit 2) if it cannot.
- Pasted blocks: `# BEGIN INCLUDE_INLINE: <path> sha256=<hex>` ... `# END INCLUDE_INLINE: <path>`.
  The body preserves the UTF-8 input bytes and adds one LF before the end marker. The SHA-256
  covers the input bytes. Nested includes and other file references still resolve in TOPAS.
- The header lists each file: `# INCLUDE: <path>` or `# INCLUDE_INLINE: <path> sha256=<hex>`,
  replacing `# CT_TO_MATERIAL:` from step 2 (never released).
- The configuration directory and the files picked from it use absolute paths.
- The GUIs' `spr_table` widgets and variables are now `ct_table`; they still pass `-s`.

Checked with OpenTOPAS 4.3.0 on 2026-11-17:
- TOPAS normally stops at startup when a parameter is defined twice in one file. It keeps
  the later definition for names beginning with `Ma/PatientTissue`. Across an include, the
  including file takes precedence for compatible definitions.
- TOPAS accepts several `includeFile` lines. If the chains resolve a parameter to different
  definitions, the file that joins them must set it absolutely. For example, a seed set in
  one include conflicts with the default seed in another chain unless the including file
  sets the seed explicitly.
- Head phantom, field 1, 20 000 protons, one thread, default seed: the table included, and
  the table pasted (by hand, then by dicomexport's own `-S`), give byte-identical dose cubes.

Still to do: review, commit, PR. Then update pregdos#126 (free TOPAS code via `-S`).

### 2. #94: material overrides

- **DECIDED:** `materials.txt` in the configuration directory holds `Ma/…` definitions in
  TOPAS syntax. It is pasted into the TOPAS file as text, unread.
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
- **OPEN, since step 3:** `-S` can now paste any file, so `materials.txt` might need no
  special handling at all: the caller passes it with `-S`, and #94 only adds
  `--material-override`. Note that a bare name is looked up in `ct_to_material/` only, so
  either `materials.txt` would need a full path, or the lookup would extend to it. Decide
  when #94 starts.

### 3. #94, last part: warn about declared overrides

PROPOSED: warn when the RTSTRUCT declares an override (`RTROIObservationsSequence`,
`MaterialID`, `REL_ELEC_DENSITY`) that no option covers. A warning, not an error: Eclipse
writes such overrides routinely, for example on couch structures.

### 4. Before releasing 2.0.0

- **Check the standalone builds on the pre-release.** They were never run. The Windows zip
  holds `dicomexport.exe`, `dicomexport-cli.exe` and `defaults/`; the GUI opens and lists
  beam models and tables; an exported `includeFile` still exists after the GUI is closed;
  the Linux archive holds the binary and `defaults/`.
- **Release notes: what breaks.** `--spr-to-material` is gone: `-s` is now `--include`, and
  `-s`/`-S` may be repeated. `RS_CATALOG` is gone from `dicomexport.model_plan` (use
  `default_range_shifter_catalog()`); the beam models and range-shifter files moved from
  `res/` to `dicomexport/defaults/`; the bare `dicomexport-cli.exe` is no longer a release
  asset; `plan-export` no longer fails without `-b`.

## Open questions

1. **#102** was answered with the reasons for declining and is still open. Close it, or wait
   for the requester.
2. **#98 (HLUT composition)** is not part of this work. If it comes, it is one more
   subdirectory (`hluts/`) and one option.
3. **Report to OpenTOPAS** that `DensityCorrection` is read without a bounds check
   (`TsImagingToMaterialSchneider.cc:222`). Nobody has reported it yet.

## Code pointers

| What | Where |
| --- | --- |
| Configuration directory: search order, file selection, `--init-config` | `dicomexport/config.py` |
| Flags shared by `dicomexport` and `plan-export` | `dicomexport/parser_config.py` |
| Options of the study exporter, `--init-config` and `--list-config` | `dicomexport/parser_main.py`, `main.py` |
| Range-shifter catalog and its loader | `dicomexport/model_plan.py` (`RangeShifterCatalog`, `range_shifter_catalog_of`) |
| Catalog lookup and the unknown-ID error | `dicomexport/import_plan_dicom.py` (`_build_range_shifter`) |
| `includeFile` line for the table | `dicomexport/topas_text.py` (`TopasText.spr_to_material`), called from `export_study_topas.py` |
| TOPAS header with the data sources | `dicomexport/topas_text.py` (`header2`) |
| Patient block that gains the override lines | `dicomexport/topas_text.py` (`geometry_patient_dicom`, `geometry_patient`) |
| ROI names | `dicomexport/import_rtstruct.py`, `model_rtstruct.py` |
| GUIs | `dicomexport/gui/qt_app.py`, `app.py`, `utils.py` |
| Standalone builds | `.github/workflows/build-windows.yml`, `ci.yml` |
| Wheel contents | `pyproject.toml` `[tool.setuptools.package-data]`, checked by `tests/test_defaults.py` |
| Table index rules, reference implementation | `tests/test_spr_tables.py` (`index_problems`) |
| Tests stay away from real configuration directories | `tests/conftest.py` |

## For pregdos: migrating to dicomexport 2.0.0

Written for whoever, human or AI, adapts pregdos (Eurados/pregdos#128, #126, #131). Items
marked PROPOSED or OPEN above may still change: check dicomexport's `--help` and release
notes before coding against an option name or format.

**State of dicomexport `main` (2026-11-17), not yet released:**

| Available now | Not yet |
| --- | --- |
| Shipped defaults; `--config-dir` and the search order; `--init-config`; `--list-config json`; `-b`/`-s` by name or path | `-S`, the `# INCLUDE:` / `# INCLUDE_INLINE:` header lines and the block markers (step 3, in review); `materials.txt` and `--material-override` (#94) |

pregdos can start on the configuration directory and the setup page now. Do not start on
the three table readers under Pitfalls until step 3 is merged.

### What pregdos must change

- **Raise `MINIMUM_DICOMEXPORT`** in `pregdos/versions.py` to 2.0.0.
- **Configuration directory.** Add one key to pregdos's `config.toml` (`[paths]`) for the
  site's dicomexport configuration directory, document it in `config.toml.example` and the
  installation docs, and make it a mountable volume in the container.
  - **Always pass it explicitly as `--config-dir` when set.** Do not rely on dicomexport's
    search order from a service: it would look in the service account's `~/.config` and in
    `/etc/dicomexport/`, which another installation on the same host may own.
  - When the key is empty, dicomexport uses its shipped defaults (or whatever the search
    order finds) and logs a warning. Either way, **record the data a run used** in
    `run.json`, from the header of every field file: `# CONFIG_DIR:`, `# BEAM_MODEL:`, one
    `# INCLUDE: <path>` or `# INCLUDE_INLINE: <path> sha256=<hex>` per included file, and
    `# RANGE_SHIFTER_CATALOG:`. Files picked from the configuration directory use absolute
    paths. Explicit relative `-s` and `-S` paths appear as typed.
  - A site sets its directory up with `dicomexport --init-config DIR`, which never
    overwrites. That copies both DCPT beam models, so `-b` is required there until the site
    removes one.
  - If pregdos's RPM/DEB packages (pregdos#86) ever install such a directory, mark its files
    as configuration (`%config(noreplace)`), so a package upgrade never replaces site data.
- **Delete pregdos's own copies:** `pregdos/data/beam_models/`, `pregdos/data/ct_to_material/`,
  and `_builtin_beam_models()` / `_builtin_material_tables()` in `webserver.py`. dicomexport
  ships the same data: the beam models are numerically identical (dicomexport's are the
  cleaned-up copies), the HU table is identical to the OpenTOPAS 4.3.0 example.
- **Build the setup page's choices from `dicomexport --list-config json --config-dir DIR`.**
  JSON keys: `dicomexport_version`, `config_dir`, `found_by`, `is_shipped_defaults`,
  `beam_models` and `ct_to_material` (lists of `{name, path, default}`), `range_shifters`
  (`{path, exists, ids}`), `materials` (`{path, exists}`). Preselect the entry with
  `default: true`, and keep passing `-b` explicitly: a site's directory with more than one
  beam model requires it.
- **Configuration errors exit with code 2 and a one-line message** on stderr: a missing
  `--config-dir`, an ambiguous or unknown `-b`/`-s`, a malformed `range_shifters.csv`.
  Show the message.
- **Range shifters need no UI.** pregdos never passed `--range-shifter-catalog`, so every run
  used the shipped catalog. With `--config-dir`, the site's `range_shifters.csv` is used
  automatically. An unknown ID makes dicomexport exit non-zero with a message naming the ID
  and the file: show that message.
- **`-s` paths:** a path typed with a directory part (`./table.txt`, `../x/table.txt`) is
  written into `includeFile` exactly as given, even if it does not exist at export time. A
  bare name is looked up in the configuration directory and written as an absolute path.
  pregdos's current `-s ../table.txt` keeps working until it moves to `-S`.
- **Switch from `-s` to `-S`** once step 3 is released: `-S <table>` pastes the table into
  each field file. The study directory can contain just `dicom/` and `run_*/` when the table
  has no external references. Keep any files the table references available at runtime.
  Update `docs/study_layout.md`. pregdos uses the short `-s` and is unaffected by removal of
  `--spr-to-material`.
- **Once pregdos passes any `-s`/`-S`, dicomexport adds no table by itself.** pregdos must
  always name the table, also when it adds other files.
- **Uploads of a one-off beam model or table stay possible:** pass the uploaded file's path.

### Pitfalls

- **Three places read the table through the `includeFile` line**, which `-S` removes. The
  pasted table sits between `# BEGIN INCLUDE_INLINE: <path> sha256=<hex>` and
  `# END INCLUDE_INLINE: <path>`; pregdos knows which block is the table because `<path>` is
  the path pregdos passed (or the absolute path dicomexport resolved a bare name to).
  Read the block as bytes and remove one framing LF before the end marker to recover the
  original bytes covered by the hash.
  - `executor._material_table_identity`: the checksum for `run.json`. Take the path and
    SHA-256 from the BEGIN line (or the matching `# INCLUDE_INLINE:` header line).
  - `structure_metrics._density_from_hu`: structure mass. Parse the block between the
    markers instead of the included file.
  - **The mask pre-pass** (`structure_metrics.py`, the parameter list around line 97) copies
    `includeFile` from a field file into its own TOPAS file. With `-S` there is no such line:
    it must copy the whole pasted block, or the pre-pass runs without a material table.
  - **Copy the block exactly once.** Avoid redefining its parameters in the pre-pass file.
    TOPAS normally rejects duplicates in the same file. OpenTOPAS 4.3.0 keeps the last
    definition for names beginning with `Ma/PatientTissue`.
- **Table validation is pregdos's job** (pregdos#131). TOPAS aborts unless
  `len(DensityCorrection) == sections[-1] - sections[0]`, and reads out of bounds unless
  `MinImagingValue == sections[0]` (`MinImagingValue` defaults to -1000).
  `index_problems()` in dicomexport's `tests/test_spr_tables.py` is a tested reference
  implementation; it handles vectors over several lines and a trailing unit. Validate when
  a table is uploaded or chosen, not when a run is submitted.
- **Relative paths still pass through verbatim.** `DicomDirectory` stays relative when
  pregdos passes it relative. With `-S`, the only path left in a field file is the DICOM
  directory.
- **Material overrides (pregdos#126)**, after #94:
  - pregdos reads the material names from `materials.txt` itself (the `Ma/<name>/` prefixes);
    dicomexport does not list them.
  - Pass one `--material-override "ROI name=Material"` per choice (PROPOSED form), in the
    order of precedence: TOPAS takes the first match for overlapping structures.
  - A structure missing from the RTSTRUCT is a dicomexport error. An unknown material is
    **not** caught by dicomexport: TOPAS aborts at run time, on the compute node. Offer only
    names from `materials.txt` (or known Geant4 names) so this cannot happen.
  - The override structures do not need to be among the scored structures.
- **No SPR table ships.** pregdos takes HU tables only, as before.
