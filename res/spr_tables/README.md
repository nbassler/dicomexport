Stopping-power-ratio (SPR) to material tables, prepared for TOPAS.

The imaging values in these tables encode SPR as `value = 1000 * SPR - 1000`, not Hounsfield
units. They are only valid for a CT whose voxels hold SPR in that encoding; see the header of
each file. `tests/test_spr_tables.py` checks that every table here keeps TOPAS's
`DensityCorrection` lookup in bounds (issue #99).
