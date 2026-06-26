# Description of the beam model format

## CSV column layout

1) Energy: Nominal (i.e. requested energy) [MeV]
2) E_real: actual energy derived from range measurements [MeV]
3) E_real_sigma: energy spread 1-sigma Gaussian [MeV]
4) protons/MU: number of protons per given monitor Unit (this is proportional to air mass stopping power)
5) beamwidth sigma x [mm]
6) beamwidth sigma y [mm]
7) divergence sigma x' [rad]  *(10-column format only)*
8) divergence sigma y' [rad]  *(10-column format only)*
9) Covariance cov(x x')       *(10-column format only)*
10) Covariance cov(y y')      *(10-column format only)*

## Header keys

Comment lines (prefixed with `#`) may contain the following optional key:

- `BMODPOS <value> mm` — distance of the beam model plane upstream of the isocenter in mm.
  Must be positive. The unit suffix `mm` is required; other units (cm, m, µm) are rejected.
  If absent, the code uses `--beam-model-position` if provided; otherwise it defaults to 500.0 mm.

Example header line: `#"BMODPOS 600.0 mm"`

## Available files

| File | Description | Position |
|------|-------------|----------|
| `DCPT_beam_model__v2.csv` | DCPT beam model reverse-engineered from experimental data and TOPAS simulations | 500.0 mm upstream |
| `DCPT_beam_model__v5.csv` | Updated DCPT beam model (emittance source type) | 600.0 mm upstream |
| `bm_test_6col.csv` | Reduced test model — do not use for production | no BMODPOS (falls back to default) |

## Acknowledgements
`DCPT_beam_model__v2.csv` was kindly provided by Anne Vestergaard and Peter Lægdsmand from DCPT.
`DCPT_beam_model__v5.csv` was kindly provided by Simon Norrig from DCPT.
