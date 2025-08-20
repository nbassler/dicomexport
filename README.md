# DicomExport
A tool for exporting dicom plans (RN* or RP*) to various formats.

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



## Acknowledgements
This work is part of the SONORA project, which has received funding from the European Union’s EURATOM research and innovation programme under grant agreement No 101061037 (PIANOFORTE – European Partnership for Radiation Protection Research).
