# Description of the beam model format

Beam model CSV files describe the energy-dependent transverse phase-space
parameters at a beam model plane. They do not define the beam direction or any
global simulation coordinate axis. The parameters are used locally at a given
beam model plane, central beam position, and central beam direction.

## CSV column layout

Each data row contains either 6 columns (no divergence/correlation data) or 10
columns (full transverse phase-space data):

1) `Energy`: nominal, requested energy [MeV]
2) `E_real`: actual energy derived from range measurements [MeV]
3) `E_real_sigma`: Gaussian 1-sigma energy spread [MeV]
4) `protons/MU`: number of primary protons per monitor unit
5) `sigma_x`: RMS beam width in the local transverse x direction [mm]
6) `sigma_y`: RMS beam width in the local transverse y direction [mm]
7) `sigma_x'`: RMS angular divergence in the local transverse x direction [rad] *(10-column format only)*
8) `sigma_y'`: RMS angular divergence in the local transverse y direction [rad] *(10-column format only)*
9) `rho_xx'`: correlation coefficient between x and x' [-] *(10-column format only)*
10) `rho_yy'`: correlation coefficient between y and y' [-] *(10-column format only)*

Columns 9 and 10 are dimensionless correlation coefficients, not covariances,
and must lie in `[-1, 1]`. Files outside that range are rejected.

A 6-column file carries no beam optics: divergence and correlation are taken as
zero, giving a perfectly parallel beam. Use the 10-column format in production.

## Header keys

Comment lines (prefixed with `#`) may contain the following optional key:

- `BMODPOS <value> mm` — distance of the beam model plane upstream of the
  isocenter in mm. This is part of the beam model definition: all tabulated
  spot sizes, divergences, and correlations are valid at this plane only. It
  must not be changed. `BMODPOS` is
  always a positive upstream distance along the beam, independent of the
  direction in which the beam is transported in the simulation universe. The
  beam model file must not encode a signed coordinate or assume a particular
  global axis.

The unit suffix `mm` is required; other units (cm, m, µm) are rejected. For
legacy files without `BMODPOS`, `--beam-model-position` can provide the missing
value; otherwise the code defaults to 500.0 mm.

Example header line: `#"BMODPOS 600.0 mm"`

`BMODPOS` is the only key the loader parses; all other comment lines are
informational.

## Twiss/correlation interpretation

For each transverse plane, the 10-column format defines a 2D Gaussian in
position and angle at the beam model plane. The correlation coefficient is
converted to a covariance before sampling:

```math
\mathrm{cov}(x,x') = \rho_{xx'} \sigma_x \sigma_{x'}
```

Here the covariance is the central second moment of the sampled distribution:

```math
\mathrm{cov}(x,x') =
\left\langle (x - \langle x \rangle)(x' - \langle x' \rangle) \right\rangle
```

It is not the product of mean values. The y plane is treated analogously.

```math
\Sigma_x =
\begin{pmatrix}
\sigma_x^2 & \rho_{xx'} \sigma_x \sigma_{x'} \\
\rho_{xx'} \sigma_x \sigma_{x'} & \sigma_{x'}^2
\end{pmatrix}
```

The geometric emittance and Twiss parameters follow from the covariance matrix:

```math
\epsilon_x = \sqrt{\det \Sigma_x}, \quad
\beta_x = \frac{\sigma_x^2}{\epsilon_x}, \quad
\alpha_x = -\frac{\mathrm{cov}(x,x')}{\epsilon_x}, \quad
\gamma_x = \frac{\sigma_{x'}^2}{\epsilon_x}
```

Sampling uses these matrices to draw local transverse positions and angles
before the resulting particles are oriented according to the selected beam
geometry.

## Available files

| File | Description | Position |
|------|-------------|----------|
| `DCPT_beam_model__v2.csv` | DCPT beam model reverse-engineered from experimental data and TOPAS simulations | 500.0 mm upstream |
| `DCPT_beam_model__v5.csv` | Updated DCPT beam model (emittance source type) | 600.0 mm upstream |
| `bm_test_6col.csv` | **Test fixture, not a beam model.** Synthetic 6-column data used by the test suite; carries no beam optics | no BMODPOS (falls back to default) |

## Acknowledgements

DCPT is the Danish Centre for Particle Therapy, Aarhus, Denmark.

`DCPT_beam_model__v2.csv` was kindly provided by Anne Vestergaard and Peter Lægdsmand from DCPT.
`DCPT_beam_model__v5.csv` was kindly provided by Simon Norrig from DCPT.
