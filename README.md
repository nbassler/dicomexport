# DicomExport

[![CI](https://github.com/nbassler/dicomexport/actions/workflows/ci.yml/badge.svg)](https://github.com/nbassler/dicomexport/actions/workflows/ci.yml)
[![Lint](https://github.com/nbassler/dicomexport/actions/workflows/lint.yml/badge.svg)](https://github.com/nbassler/dicomexport/actions/workflows/lint.yml)
[![CodeQL](https://github.com/nbassler/dicomexport/actions/workflows/codeql.yml/badge.svg)](https://github.com/nbassler/dicomexport/actions/workflows/codeql.yml)
[![Build Binaries](https://github.com/nbassler/dicomexport/actions/workflows/build-windows.yml/badge.svg)](https://github.com/nbassler/dicomexport/actions/workflows/build-windows.yml)
[![TOPAS integration](https://github.com/nbassler/dicomexport/actions/workflows/topas-integration.yml/badge.svg)](https://github.com/nbassler/dicomexport/actions/workflows/topas-integration.yml)
[![Dependabot](https://img.shields.io/badge/dependabot-enabled-025e8c?logo=dependabot)](https://github.com/nbassler/dicomexport/network/updates)

A tool for exporting DICOM proton therapy studies.
- Supported output formats: TOPAS input files, MCPL phase-space files, and generic spot lists (FLUKA/SHIELD-HIT12A).
- More output formats can be added.

## Running the GUI

### Desktop GUI (Qt)
```bash
pip install "dicomexport[gui]"
dicomexport
```
Or directly:
```bash
python dicomexport/gui/qt_app.py
```

### Web UI (Streamlit)
```bash
pip install "dicomexport[gui]"
streamlit run dicomexport/gui/app.py
```

## Developer notes
### Getting started:

- Clone the repository.
- Use VSCode, and open the repository folder
- open the dicomexport/main.py file and setup a venv in the terminal
- run `pip install -e .` Say yes to install all options, when prompted.

You are then ready to convert dicom files to topas input scripts.
Example:

The test directory `res/test_studies/DCPT_headphantom/`has a set of CT files, a RS structure file, a RN plan file with 3 fields in it.
You need also so specify a beam model. The beam model position is read automatically from the
`BMODPOS` key in the CSV header; you can override it with `-p` if needed.
Finally you need to point to a Stopping power ratio to material table.

```bash
PYTHONPATH=. python3 dicomexport/main.py -v -b=res/beam_models/DCPT_beam_model__v2.csv --nozzle-side pos-z -s=res/spr_tables/SPRtoMaterial__Brain.txt res/test_studies/DCPT_headphantom/
```
which will produce three topas files, ready to run:

```
$ PYTHONPATH=. python3 dicomexport/main.py -v -b=res/beam_models/DCPT_beam_model__v2.csv --nozzle-side pos-z -s
res/spr_tables/SPRtoMaterial__Brain.txt res/test_studies/DCPT_headphantom/
INFO:dicomexport.import_rtstruct:Using RTSTRUCT file: RS.1.2.246.352.205.5439556202947041733.367077883804944283.dcm
INFO:dicomexport.import_rtstruct:Imported RTSTRUCT: DCPT_headphantom with 11 ROIs
WARNING:__main__:Multiple DICOM RTDOSE files found, using the first one.
INFO:dicomexport.export_study_topas:Wrote Topas geometry file for field 1: /home/bassler/Projects/dicomexport/topas_field1.txt
INFO:dicomexport.export_study_topas:Wrote Topas geometry file for field 2: /home/bassler/Projects/dicomexport/topas_field2.txt
INFO:dicomexport.export_study_topas:Wrote Topas geometry file for field 3: /home/bassler/Projects/dicomexport/topas_field3.txt
```

### TOPAS beam geometry options

Both the full study exporter (`dicomexport/main.py`, installed as `dicomexport`) and the plan-only exporter
(`dicomexport/main_plan_export.py`, installed as `plan-export`) support:

- `-p, --beam-model-position`: beam model distance in mm upstream of the isocenter (always positive, independent of beam transport direction). If omitted, the value is read from the `BMODPOS` key in the CSV header; if that key is also absent, it defaults to `500.0` mm.
- `--nozzle-side {pos-z,neg-z}`: side of the gantry where the nozzle/source is placed. The default is `pos-z`, meaning source at `+Z` and beam travelling toward `-Z` in the IEC convention. `neg-z` places the source at `-Z` and the beam travels toward `+Z`.

For TOPAS export, the range shifter position follows the selected nozzle side.

### Full study export options

```
$ PYTHONPATH=. python3 dicomexport/main.py --help
usage: main.py [-h] [-b BM] [-s SPR_TO_MATERIAL_PATH] [-p BEAM_MODEL_POSITION]
               [-f FIELD_NR] [-N NSTAT]
               [--export-fmt {topas,phasespace,racehorse}]
               [--nozzle-side {pos-z,neg-z}] [-v] [-V]
               study_dir [output_base_path]

Convert DICOM CT and RTSTRUCT files to geometry needed for TOPAS.

positional arguments:
  study_dir             (required) Path to folder containing the study.The folder should contain a) DICOM CT series(CT*.dcm) and b) one
                        DICOM RTSTRUCT file (RS*.dcm) and c) one DICOM RTPLAN file (RN*.dcm) and d) at least one DICOM RTDOSE file
                        (RD*.dcm) where the resulting dose distribution will be stored.
  output_base_path      Export file (default: topas.txt). Field number will be appended automatically to the name before the extension.

options:
  -h, --help            show this help message and exit
  -b, --beam-model BM
                        (required) Beam model CSV path
  -s, --spr-to-material SPR_TO_MATERIAL_PATH
                        (required) SPR to material mapping CSV path
  -p, --beam-model-position BEAM_MODEL_POSITION
                        Beam model position in mm, relative to isocenter, positive upstream. If not given, the value is read from the BMODPOS key in the beam model file header, or defaults to 500.0 mm if absent.
  -f, --field FIELD_NR
                        Field number to export. If not specified, all fields will be exported.
  -N, --nstat NSTAT
                        Target protons for simulation
  --export-fmt {topas,phasespace,racehorse}
                        Export format (default: topas). Formats: topas (*.txt), phasespace (*.mcpl), racehorse (*.csv).
  --nozzle-side {pos-z,neg-z}
                        Which side of the gantry the nozzle sits on (default: pos-z). pos-z: nozzle at +Z, beam travels toward -Z
                        (IEC convention). neg-z: nozzle at -Z, beam travels toward +Z.
  -v, --verbosity       Increase verbosity (can use -v, -vv, etc.).
  -V, --version         Show version and exit.
  ```

### Plan-only export options

```
$ PYTHONPATH=. python3 dicomexport/main_plan_export.py --help
usage: main_plan_export.py [-h] [-b FBM] [-p BEAM_MODEL_POSITION]
                           [-f FIELD_NR] [-d] [-s SCALE] [-N NSTAT]
                           [-nc {5,6,7,9,11}]
                           [--export-fmt {topas,mcpl,racehorse,spotlist}]
                           [--spot-pos-iso] [--test-mode]
                           [--nozzle-side {pos-z,neg-z}] [-v] [-V]
                           fin [fout]

Convert DICOM-RT Ion plans to MC-compatible spot lists using a beam model.

positional arguments:
  fin                   Input DICOM-RN or IBA .pld file
  fout                  Output file, default: plan.txt. Field number will be appended automatically to the name before the extension.

options:
  -h, --help            show this help message and exit
  -b, --beam-model FBM  Beam model CSV path
  -p, --beam-model-position BEAM_MODEL_POSITION
                        Beam model position in mm, relative to isocenter, positive upstream. If not given, the value is read from the BMODPOS key in the beam model file header, or defaults to 500.0 mm if absent.
  -f, --field FIELD_NR  Field number to export. If not specified, all fields will be exported.
  -d, --diag            Print plan diagnostics and exit
  -s, --scale SCALE     additional scaling multiplier for MC plan
  -N, --nstat NSTAT     Target protons for simulation
  -nc, --spotlist-column-count {5,6,7,9,11}
                        Number of columns in the spotlist export. Valid values: 5, 6, 7, 9, or 11 (default: 11).
  --export-fmt {topas,mcpl,racehorse,spotlist}
                        Export format (default: topas). Formats: topas (*.txt), mcpl (*.mcpl), racehorse (*.csv), spotlist (*.txt).
  --spot-pos-iso        Export spot X/Y positions at isocenter (z=0) instead of the beam model plane.
  --test-mode           Generate a self-contained Topas file (no DICOM patient) with a water box and isocenter dose scorer.
  --nozzle-side {pos-z,neg-z}
                        Which side of the gantry the nozzle sits on (default: pos-z). pos-z: nozzle at +Z, beam travels toward -Z
                        (IEC convention). neg-z: nozzle at -Z, beam travels toward +Z.
  -v, --verbosity       Increase verbosity
  -V, --version         show program's version number and exit
```

### Example for SpotList export
Can export files which are useful for passing them to FLUKA via the `SOURCE` card, or loading into SHIELD-HIT12A via the `USECBEAM` card.
Here a 7-column spotlist is exported:

```bash
$ PYTHONPATH=. python3 dicomexport/main_plan_export.py --export-fmt=spotlist -nc=7 res/test_plans/temp_sobp_10x10.dcm -v -b res/beam_models/DCPT_beam_model__v2.csv
```

### Example for [MCPL](https://mctools.github.io/mcpl/) phasespace export
The MCPL format is a standardized and efficient way to handle phase space files, commonly used in Monte Carlo simulations.

To export a DICOM plan to the MCPL format, you can use the following command:

```bash
PYTHONPATH=. python3 dicomexport/main_plan_export.py res/test_plans/temp_sobp_10x10.dcm -b=res/beam_models/DCPT_beam_model__v2.csv --export-fmt=mcpl -v -N=1000000 temp_sobp_10x10.mcpl
```
```
INFO:dicomexport.export_mcpl:Processing field:
INFO:dicomexport.export_mcpl:Beam model position D = +500.0 mm
INFO:dicomexport.export_mcpl:Writing MCPL file: temp_sobp_10x10_field01.mcpl
Written 1000000/1000000 particles (100.0%)
```

This will process the specified DICOM plan and generate MCPL files for each field.



For more details about the MCPL format, visit the [MCPL documentation](https://mctools.github.io/mcpl/).

## Acknowledgements
This work is part of the [SONORA project](https://pianoforte-partnership.eu/sonora/), which has received funding from the European Union's EURATOM research and innovation programme under grant agreement No 101061037 ([PIANOFORTE](https://pianoforte-partnership.eu/) - European Partnership for Radiation Protection Research).
