# Third-party notices

The project keeps its own raw, semantic, ontology, provenance and quality
rules. The following external projects were inspected and their ideas or
narrow implementation patterns were adapted behind local interfaces:

- `asagynbaev/pdf-extractor` — MIT License. The atomic-write pattern in
  `bmstu_parser.runtime.atomic` is a narrowed adaptation.
- `spbu-se/spbu-curriculum-tool` — Apache License 2.0. Its typed curriculum
  validation approach informed `study_plans.rules`; no C#/F# source files are
  vendored.
- `UTDNebula/api-tools` — MIT License. Its scrape/parse/validate separation
  informed the local pipeline seams; no Go source files are vendored.
- `jengroff/mcgill` — MIT License. Its non-destructive resolution approach
  informed `study_plans.resolution`; no application code is vendored.
- `docling-project/docling` — MIT License. Docling is an optional external
  reader backend and is not bundled into this repository.

