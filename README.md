# DicomExport
A tool for exporting DICOM proton therapy studies.
- So far only TOPAS input files and MCPL-phasespace files can be generated.
- More output formats can be added.

## Developer notes
### Getting started:

- Clone the repository.
- Use VSCode, and open the repository folder
- open the dicomexport/main.py file and setup a venv in the terminal
- run `pip install -e .` Say yes to install all options, when prompted.

You are then ready to convert dicom files to topas input scripts.
Example:

The test directory `res/test_studies/DCPT_headphantom/`has a set of CT files, a RS structure file, a RN plan file with 3 fields in it.
You need also so specify a beam model, optionally also at what distance it is defined in mm.
Finally you need to point to a Stopping power ratio to material table.

```bash
PYTHONPATH=. python3 dicomexport/main.py -v -b=res/beam_models/DCPT_beam_model__v2.csv -p 500.0 -s=res/spr_tables/SPRtoMaterial__Brain.txt res/test_studies/DCPT_headphantom/
```
which will produce three topas files, ready to run:

```
$ PYTHONPATH=. python3 dicomexport/main.py -v -b=res/beam_models/DCPT_beam_model__v2.csv -p 500.0 -s
res/spr_tables/SPRtoMaterial__Brain.txt res/test_studies/DCPT_headphantom/
INFO:dicomexport.import_rtstruct:Using RTSTRUCT file: RS.1.2.246.352.205.5439556202947041733.367077883804944283.dcm
INFO:dicomexport.import_rtstruct:Imported RTSTRUCT: DCPT_headphantom with 11 ROIs
WARNING:__main__:Multiple DICOM RTDOSE files found, using the first one.
INFO:dicomexport.export_study_topas:Wrote Topas geometry file for field 1: /home/bassler/Projects/dicomexport/topas_field1.txt
INFO:dicomexport.export_study_topas:Wrote Topas geometry file for field 2: /home/bassler/Projects/dicomexport/topas_field2.txt
INFO:dicomexport.export_study_topas:Wrote Topas geometry file for field 3: /home/bassler/Projects/dicomexport/topas_field3.txt
```

Command line options and usage:
```
$ PYTHONPATH=. python3 dicomexport/main.py --help
usage: main.py [-h] [-b BM] [-s SPR_TO_MATERIAL_PATH] [-p BEAM_MODEL_POSITION] [-f FIELD_NR] [-N NSTAT] [-v] [-V]
               study_dir [output_base_path]

Convert DICOM CT and RTSTRUCT files to geometry needed for TOPAS.

positional arguments:
  study_dir             (required) Path to folder containing the study.The folder should contain a) DICOM CT series(CT*.dcm) and b) one
                        DICOM RTSTRUCT file (RS*.dcm) and c) one DICOM RTPLAN file (RN*.dcm) and d) at least one DICOM RTDOSE file
                        (RD*.dcm) where the resulting dose distribution will be stored.
  output_base_path      Output TOPAS geometry file (default: topas.txt). Field number will be appended automatically to the name before
                        the extension.

options:
  -h, --help            show this help message and exit
  -b BM, --beam-model BM
                        (required) Beam model CSV path
  -s SPR_TO_MATERIAL_PATH, --spr-to-material SPR_TO_MATERIAL_PATH
                        (required) SPR to material mapping CSV path
  -p BEAM_MODEL_POSITION, --beam-model-position BEAM_MODEL_POSITION
                        Beam model position in mm, relative to isocenter, positive upstream.
  -f FIELD_NR, --field FIELD_NR
                        Field number to export. If not specified, all fields will be exported.
  -N NSTAT, --nstat NSTAT
                        Target protons for simulation
  -v, --verbosity       Increase verbosity (can use -v, -vv, etc.).
  -V, --version         Show version and exit.
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
This work is part of the SONORA project, which has received funding from the European Union’s EURATOM research and innovation programme under grant agreement No 101061037 (PIANOFORTE – European Partnership for Radiation Protection Research).
