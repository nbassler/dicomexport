# CT-number-to-material tables

A TOPAS Schneider table assigns material composition and density to the CT voxels.
dicomexport hands the chosen table to TOPAS without reading it: by path (`-s`) or pasted into
the TOPAS file (`-S`). Supply a finished
table prepared for your site's imaging protocol and calibration; producing one from site
calibration curves and material data is an external step.

**The table must expect the quantity your images hold.** A table indexed by Hounsfield units
is wrong for a stopping-power image and the reverse, and nothing can check this:
`RescaleType` can read `HU` even on a derived stopping-power map. Keep the `*toMaterial*`
filename convention so the quantity is visible: `HUtoMaterial*` for Hounsfield units,
`SPRtoMaterial*` for stopping-power ratio.

**The index rules.** TOPAS reads the density correction as
`DensityCorrection[value - MinImagingValue]` without a bounds check, and `MinImagingValue`
defaults to -1000. It also aborts unless `DensityCorrection` has exactly
`sections[-1] - sections[0]` entries, where `sections` is `SchneiderHounsfieldUnitSections`.
Together that means `MinImagingValue` must equal the first section boundary. Set it
explicitly whenever the sections do not start at -1000 (issue #99).

## Shipped table: HUtoMaterialSchneider.txt

The OpenTOPAS example, unchanged except for its header comments. It illustrates the format;
it is not a calibration for your scanner or TPS.

It contains 13 elements, 26 material boundaries defining 25 compositions, and 25 weight
vectors that each sum to 1. Its 3996 density corrections cover HU -1000 through 2995,
matching the first section boundary and TOPAS's default `MinImagingValue` of -1000.

The file describes `DensityCorrection` as a correction for the relative stopping power of
Geant4 and the XiO planning system. TOPAS applies it as a **density multiplier**. These
XiO-specific values should not be inherited as an Eclipse or site calibration.

Some representative values:

| HU | Density correction | Resulting density (g/cm³) |
| --- | --- | --- |
| -1000 | 9.35212 | 0.01132 |
| -999 | 5.55269 | 0.01244 |
| -950 | 1.12840 | 0.05946 |
| 0 | 0.97075 | 0.98822 |
| 1200 | 1.03851 | 1.79392 |

At HU -1000 the composition is air (75.5% nitrogen, 23.2% oxygen, 1.3% argon), but the
correction multiplies the base density of 0.00121 g/cm³ by about 9.4. For a uniform 50 cm
path at this value, the mass thickness is approximately 0.57 g/cm² instead of 0.06 g/cm².

Density has five downward steps across the tabulated range. The largest is about
0.022 g/cm³ at HU -120; three very small drops near the upper end are not at section
boundaries. Values at HU 2995 and above map to 100% titanium at approximately 4.55 g/cm³,
an implant assumption that must be assessed for the intended use.

The Schneider method is described in:

> Schneider W, Bortfeld T, Schlegel W. (2000). *Correlation between CT numbers and tissue
> parameters needed for Monte Carlo simulations of clinical dose distributions.*
> Physics in Medicine and Biology, 45(2):459–478.
> DOI: [10.1088/0031-9155/45/2/314](https://doi.org/10.1088/0031-9155/45/2/314)
