# TODO

## dicomexport 2.0.0: layered site data (draft, not decided)

The design is still open and needs discussing together with pregdos. Issues involved:
#112 (framework), #94 (material overrides), #102 (range-shifter position), #98 (HLUT
composition), #100 (HU-table validation). pregdos side: Eurados/pregdos#128 and #126.

### Already settled in #112
- Ordered data layers: built-in → site → study. Each layer extends and overrides the
  previous one by name. Every layer is a directory with the same fixed layout:
  `beam_models/`, `ct_to_material/`, `range_shifters.csv`, `materials.txt`,
  `material_catalog.csv`.
- Explicit options (`-b`, `-s`, `--range-shifter-catalog`) always win.
- A machine-readable listing (`--list-site --json`). Front ends build their choices from it.
- The built-in defaults become package data, so pregdos can drop its own copies.
- Every resolved entry records its layer and file, both in the listing and as a comment in
  the TOPAS input.

### Open questions
1. **Third layer: per study, or per user?** #112 says per study, so a run gives the same
   result whoever starts it. Proposal: dicomexport takes any number of labelled layers, e.g.
   `--data-layer site=/srv/x --data-layer study=./data`. Roles such as site, user and study
   are then the front end's business, and only the labels go into provenance.
2. **Range shifters: hard error instead of a flag.** When a site layer is present and an RS
   ID resolves only from the built-ins, stop. The built-in catalog is a union of other sites'
   devices, so falling back would silently use the wrong hardware. Materials and HU tables
   keep "merge and flag".
3. **Who copies files for relocatability (#63).** Proposal: dicomexport does it.
   - Used at export time (beam model, RS catalog, MaterialID mapping): the numbers end up
     in the TOPAS file. Nothing to copy, only provenance.
   - Read by TOPAS at run time (HU table, material definitions, a generated HLUT table):
     write them into the output directory with a provenance header. The material
     definitions have to be merged into a single file anyway, because TOPAS aborts when a
     material is defined in two include chains (#94).

### Where each issue fits
| issue | layer entry | used | typical layer |
|---|---|---|---|
| #94 | `materials.txt`, `material_catalog.csv`, structure → material binding | TOPAS run time / export | definitions: site; binding: study |
| #102 | optional position column in the RS catalog | export | site (hardware) |
| #98 | `hluts/`, selectable, composed into a generated table | TOPAS run time | site |
| #100 | validates whichever HU table is resolved | export | independent of layers |

### Suggested order
1. #100. It is independent and small, and fixes #99, which feeds pregdos's structure masses.
2. #112: layers, listing, package data, copying into the output directory.
3. #94 on top of it, then pregdos#128 and #126.
4. #102. It could also come earlier, since the catalog file already exists (#76).
5. #98 last. pregdos now takes only finished CT→material tables.
