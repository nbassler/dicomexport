# TODO: dicomexport 2.0.0

What is left before 2.0.0, and what pregdos must change for it. Design agreed with Niels on
2026-11-16; the issues (#94, #98, #102; pregdos#126, #128, #131) carry comments stating it.
Where an issue disagrees with this file, this file wins. **PROPOSED** means suggested but
not confirmed: ask before building on it. **OPEN** means not decided yet.

## Principles

- **dicomexport is a Unix-style tool.** It translates DICOM to TOPAS input and rejects
  arguments that refer to something absent. It holds no policy and does not protect users.
- **dicomexport does not interpret TOPAS files.** Files given with `-s`/`-S` are passed on or
  pasted in unread. Checking them is pregdos's job.
- **No new configuration language.** TOPAS syntax for TOPAS things, CSV for range shifters.
- **Few files, few options.** One configuration directory in effect, never merged. No
  layers, no per-user level, no per-value overrides.

The configuration directory (#112) is done; `dicomexport/defaults/README.md` and the main
README describe it.

## Remaining work

### 1. #94: material overrides (branch `94-rtstruct-…`, not committed)

Built: `--material-override "ROI=MATERIAL"` (repeatable, order kept, split at the last `=`),
checked against the RTSTRUCT by TOPAS's name rule (trim, spaces to underscores); a missing,
repeated or ambiguous structure exits with code 2. The material is not checked. Writes
`DicomRTStructFile`, `MaterialByRTStructNames`/`Materials` and `# MATERIAL_OVERRIDE:` header
lines. `materials.txt` has no special handling: it is pasted with `-S materials.txt` (bare
names are now also looked up at the top of the configuration directory). The shipped
`materials.txt` defines `ImplantSteel` (DCPT's steel at 7.8 g/cm3, pregdos#126). The RTSTRUCT's
own overrides (`MaterialID`, `ROIPhysicalPropertiesSequence`) are read and warned about when
not covered. An overridden structure is refused when TOPAS would build it differently
(TOPAS fills every contour of 3+ points and never clears a voxel): a hole (nested or XOR),
an open contour, no closed contour, a name not stored as UTF-8 (TOPAS compares raw bytes),
a contour off the CT slices (TOPAS matches z exactly and skips the rest), a character a
TOPAS file cannot carry (`= ' ` ? # "`, typographic quotes and dashes, also in the RTSTRUCT
path), or an RTSTRUCT whose ROI sequences OpenTOPAS 4.3.0 cannot read (see Open questions).
The test study's `CTV` has a real hole at z = 9.5 mm. Code: `material_override.py` (`check_contours`), `import_rtstruct._declared_overrides`,
`TopasText.material_overrides`.

Still to do: review, commit, PR (closes #94). Then answer pregdos#126.

### 2. Before releasing 2.0.0

- **#129** (branch `129-…`, not committed): an unknown `RangeShifterID`, or an invalid plan,
  is now a one-line error with exit code 2 in both commands, no longer a traceback (and a
  silent failure in the Qt GUI). `dicomexport` reads the plan before the CT, so it fails fast.

- **Run the standalone builds from the pre-release.** They have never been run. The Windows
  zip holds `dicomexport.exe`, `dicomexport-cli.exe` and `defaults/`; the GUI lists beam
  models and tables; an exported `includeFile` still exists after the GUI is closed. The
  Linux archive holds the binary and `defaults/`.
- **Release notes, what breaks:** `--spr-to-material` is gone (`-s` is now `--include`,
  repeatable, with `-S`); the beam models and range-shifter data moved from `res/` to
  `dicomexport/defaults/`; `RS_CATALOG` is gone from `dicomexport.model_plan` (use
  `default_range_shifter_catalog()`); `dicomexport-cli.exe` is no longer a separate release
  asset; `plan-export` no longer requires `-b`.

### 3. Open questions

- **#102**: declined with reasons, still open. Close it, or wait for the requester.
- **#98 (HLUT composition)**: not part of 2.0.0. If it comes: one subdirectory, one option.
- **Report to OpenTOPAS** two bugs: `DensityCorrection` is read without a bounds check
  (`TsImagingToMaterialSchneider.cc:222`); and `TsDicomPatient.cc:652` assigns through a
  reference to the first `StructureSetROISequence` item while searching, so an RTSTRUCT
  whose `ROIContourSequence` lists another ROI first loses that ROI and TOPAS stops.
  dicomexport refuses such an RTSTRUCT for overrides; drop that check once fixed upstream.

### 4. After 2.0.0, not blocking

- **#130: check every path written into a TOPAS file at export.** `DicomDirectory`,
  `CloneRTDoseGridFrom` and `includeFile` are written unchecked; a path containing
  `= ' ` ? # "` makes TOPAS stop at startup (checked with 4.3.0: a clear message for `=`,
  a confusing "extra tokens" one for `#`). Only the RTSTRUCT path of an override is checked
  now (`material_override._unsafe`); reuse it for all of them, exit code 2 at export.

## Code pointers

| What | Where |
| --- | --- |
| Configuration directory, file selection, `--init-config` | `dicomexport/config.py` |
| `-b`, `-s`/`-S`, `--config-dir`, range-shifter flags (shared by both exporters) | `dicomexport/parser_config.py` |
| `--init-config`, `--list-config` | `dicomexport/parser_main.py`, `main.py` |
| Range-shifter catalog; unknown-ID error | `model_plan.py` (`RangeShifterCatalog`); `import_plan_dicom.py` (`_build_range_shifter`) |
| Included and pasted files; header lines | `topas_text.py` (`includes`, `include_sources`, `header2`), called from `export_study_topas.py` |
| Material overrides: checks, declared-override warning, TOPAS lines | `material_override.py`, `import_rtstruct.py` (`_declared_overrides`), `topas_text.py` (`material_overrides`) |
| ROI names | `import_rtstruct.py`, `model_rtstruct.py` |
| GUIs | `gui/qt_app.py`, `gui/app.py`, `gui/utils.py` |
| Standalone builds; wheel contents | `.github/workflows/build-windows.yml`, `ci.yml`; `pyproject.toml`, checked by `tests/test_defaults.py` |
| Table index rules, reference implementation | `tests/test_spr_tables.py` (`index_problems`) |

## For pregdos: migrating to dicomexport 2.0.0

For whoever, human or AI, adapts pregdos (pregdos#128, #126, #131). Everything below is on
dicomexport `main` but unreleased; material overrides (#94) are on a branch. Check
`--help` and the release notes before coding against an option name.

### What pregdos must change

1. **Raise `MINIMUM_DICOMEXPORT`** in `pregdos/versions.py` to 2.0.0.
2. **Configuration directory.** Add a `[paths]` key to `config.toml` for the site's
   dicomexport configuration directory; document it in `config.toml.example` and the
   installation docs; make it a mountable volume in the container.
   - **Always pass it as `--config-dir` when set.** A service must not rely on the search
     order: it would look in the service account's `~/.config` and in `/etc/dicomexport`,
     which another installation on the host may own.
   - A site creates the directory with `dicomexport --init-config DIR` (never overwrites).
     It then holds both DCPT beam models, so `-b` is required until the site removes one.
   - If pregdos's packages (pregdos#86) ever install such a directory, mark the files
     `%config(noreplace)`.
3. **Delete pregdos's own data:** `pregdos/data/beam_models/`, `pregdos/data/ct_to_material/`,
   `_builtin_beam_models()` and `_builtin_material_tables()` in `webserver.py`. dicomexport
   ships the same beam models (numerically identical) and HU table.
4. **Build the setup page from `dicomexport --list-config json --config-dir DIR`.** Keys:
   `dicomexport_version`, `config_dir`, `found_by`, `is_shipped_defaults`, `beam_models` and
   `ct_to_material` (lists of `{name, path, default}`), `range_shifters`
   (`{path, exists, ids}`), `materials` (`{path, exists}`). Preselect `default: true`, but
   always pass `-b` explicitly.
5. **Name the table with `-S`** instead of `-s ../table.txt`: `-S` pastes it into each field
   file, so the study directory needs no copy (update `docs/study_layout.md`). Files the
   table itself references must still exist at runtime. **Once any `-s`/`-S` is given,
   dicomexport adds no table by itself:** always name it, also when adding other files.
6. **Find the pasted table again.** Three places read the table through the `includeFile`
   line, which `-S` removes:
   - `executor._material_table_identity` (checksum for `run.json`): take path and SHA-256
     from the `# INCLUDE_INLINE: <path> sha256=<hex>` header line.
   - `structure_metrics._density_from_hu` (structure mass): parse the block between
     `# BEGIN INCLUDE_INLINE: <path> sha256=<hex>` and `# END INCLUDE_INLINE: <path>`.
   - **The mask pre-pass** (`structure_metrics.py`, around line 97) copies `includeFile` into
     its own TOPAS file. It must copy the whole pasted block instead, **exactly once**, and
     not redefine any of its parameters: TOPAS stops on a parameter defined twice in a file.

   `<path>` is the path pregdos passed, or the absolute path a bare name resolved to. The
   block holds the file's bytes plus one LF before the end marker; the SHA-256 covers the
   file's bytes, i.e. the block without that LF.
7. **Record what a run used** in `run.json`, from each field file's header: `# CONFIG_DIR:`,
   `# BEAM_MODEL:`, one `# INCLUDE:` or `# INCLUDE_INLINE:` per file, and
   `# RANGE_SHIFTER_CATALOG:`. Files picked from the configuration directory have absolute
   paths; paths pregdos typed appear as typed.
8. **Show dicomexport's errors.** Configuration errors (missing `--config-dir`, ambiguous or
   unknown `-b`/`-s`/`-S`, malformed `range_shifters.csv`, a plan with an unknown
   range-shifter ID) exit with code 2 and a one-line message on stderr. The range-shifter
   message names the ID and the catalog file.
9. **Spot mode: add a setting.** dicomexport now defaults to `--spot-mode sources`: one
   TOPAS source per spot, the field run as `--batches` identical Geant4 runs (default 10),
   each with 1/10 of every spot's protons. pregdos's present behaviour, one run per spot, is
   `--spot-mode timefeature`. Offer the choice, and always pass `--spot-mode` and `--batches`
   explicitly.
10. **Read the run layout from the header, not from `Tf/spotWeight`.** In sources mode there
    is no `uv:Tf/spotWeight/Values` line. The header has, in both modes, `# SPOT_MODE:`,
    `# SPOTS:`, `# RUNS:` (batches, or spots in timefeature mode) and
    `# SIMULATED_HISTORIES:` (protons actually simulated); in sources mode also
    `# EVENTS_PER_RUN:`. Two readers break:
    - `results.parse_plan_scaling` sums `spotWeight` for the simulated histories, and would
      get 0. Take `# SIMULATED_HISTORIES:` instead.
    - `executor._spot_weights` / `field_progress` / `run_progress` (the progress bars) count
      one run per spot, weighted by `spotWeight`.
11. **Progress bars in sources mode.** The runs are identical, so progress is runs started
    (`Begin processing for Run: N`, as now) out of `RUNS`, each worth 1/`RUNS` of the field:
    10 steps of 10 % with the default. For finer steps within a run, TOPAS logs
    `History: N` per event (`Ts/ShowHistoryCountAtInterval = 1`), `EVENTS_PER_RUN` per run;
    but an event holds one proton from every spot still active, so early events carry more
    work than late ones. Say "batch" in the UI in this mode, not "spot". Timefeature mode
    keeps today's spot-weighted bar.
12. **OPEN, check before trusting uncertainties in sources mode.** pregdos computes the
    relative uncertainty as sqrt(N)·SD/Sum with N = simulated protons, which assumes one
    proton per TOPAS history. In sources mode a TOPAS history is an event with one proton
    from every active spot, so TOPAS's SD is per event and N would be the number of events
    (`RUNS` × `EVENTS_PER_RUN`), and the events within a run are not identical. Decide with
    Niels how uncertainties are formed in this mode (the identical batches exist for this).

### Good to know

- **Range shifters need no UI.** With `--config-dir`, the site's `range_shifters.csv` is used.
- **Uploads of a one-off beam model or table** stay possible: pass the uploaded file's path.
- **Free TOPAS code (pregdos#126)** is possible with `-S`. Included code cannot change a
  parameter dicomexport writes: pasted, TOPAS stops and names it; with `-s`, TOPAS silently
  keeps dicomexport's value. Use `-S`.
- **Table validation is pregdos's job** (pregdos#131), when a table is uploaded or chosen.
  TOPAS aborts unless `len(DensityCorrection) == sections[-1] - sections[0]`, and reads out
  of bounds unless `MinImagingValue == sections[0]` (default -1000). `index_problems()` in
  dicomexport's `tests/test_spr_tables.py` is a tested reference implementation.
- **Relative paths pass through verbatim.** With `-S`, the only path left in a field file
  is the DICOM directory, relative if pregdos passes it relative.
- **No SPR table ships.** pregdos takes HU tables only, as before.
- **Material overrides (#94):** pass `-S materials.txt` (with the table) and one
  `--material-override "ROI=MATERIAL"` per choice, in order of precedence: TOPAS takes the
  first match for overlapping structures, so implants before the body. Offer ROI names from
  the RTSTRUCT, and materials from `materials.txt` (the `Ma/<name>/` prefixes; dicomexport
  does not list them) plus any Geant4/TOPAS names pregdos allows: an unknown material is
  caught only by TOPAS. Record the `# MATERIAL_OVERRIDE: ROI=MATERIAL` header lines in
  `run.json`. Override structures need not be scored. dicomexport refuses a structure TOPAS
  would build wrongly (a hole, an open contour, no closed contour, a name TOPAS cannot
  match), with exit code 2 and a message naming it: show it. dicomexport warns (stderr) when the
  RTSTRUCT declares an override that no option covers; worth showing.
