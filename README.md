# DigiLab catalogue demo — DCAT-AP + ODRL (+ CDIF)

A minimal cross-institutional catalogue showing the data space idea: **find data and software across partners, and
see what you may do with it before contacting anyone.** Metadata and access terms travel; the data stays with the
partner. All partner data is mock; the two software assets are real Naturalis/BGE repositories.

```
partner sites (nginx)                     DigiLab catalogue (FastAPI)
  /knmi/        index.html + catalog.jsonld ──harvest──► SHACL check ──► Parquet index (DuckDB) ──► search + ODRL evaluation
  /deltares/    "            "                                                                   ├─ DCAT-AP (as published)
  /fair2grow/   "            "              ◄──────── live federated query (no index) ──────────  ├─ CDIF (generated)
  /naturalis/   "  (+ 2 software assets)                                                  ├─ CodeMeta (generated, software)
                                                                                                 └─ vocabulary links
  /maris/       not registered yet  ──── register via UI / POST /api/sources ────►
```

## Run

```bash
docker compose up --build
```

| What | Where |
|---|---|
| DigiLab catalogue | http://localhost:8000 |
| Standards & mappings (DCAT → CDIF, ODRL profile, SHACL, vocabularies) | http://localhost:8000/standards |
| API (OpenAPI) | http://localhost:8000/docs |
| Partner sites | http://localhost:8080 — each at `/<partner>/`, catalogue at `/<partner>/catalog.jsonld` |

Re-harvest after editing a partner file: `docker compose run --rm harvester` (or `POST /api/harvest`).
To start clean, delete the files in `data/`.

Without Docker: `pip install -r app/requirements.txt`; `python -m http.server 8080 -d partners`;
then in `app/`: `python -m catalog.harvest` and `uvicorn catalog.api:app --port 8000`.

## Layout

```
partners/<org>/catalog.jsonld    DCAT-AP catalogue: datasets (dcat:dataset) and software (dcat:resource), each with an odrl:Offer
partners/<org>/index.html        partner landing page rendered from that file; links to the DigiLab catalogue
partners/_shared/config.js       URL of the DigiLab catalogue used by partner pages
config/sources.json              catalogues harvested from the start (MARIS is deliberately not listed)
config/shapes/dcat-odrl-min.ttl  the agreed metadata minimum (SHACL) — the governance artefact
config/vocab.json                keyword/theme/purpose → AGROVOC, DPV, EU themes, Darwin Core (Vocabulary Hub stand-in)
config/nginx-partners.conf       serves .jsonld as application/ld+json
app/catalog/common.py            fetch, SHACL-check, flatten DCAT/ODRL; vocabulary lookup
app/catalog/cdif.py              DCAT dataset record → CDIF Data Description 1.1 crosswalk
app/catalog/codemeta.py          DCAT software record → CodeMeta 3.0 crosswalk
app/catalog/policy.py            tiny ODRL evaluator (purpose, spatial; eq/neq/isAnyOf/isNoneOf)
app/catalog/harvest.py           harvester → data/index.parquet
app/catalog/api.py               search, dataset representations, catalogue registration
```

## API

| Endpoint | |
|---|---|
| `GET /api/search?q&type=dataset\|software&purpose&spatial&action&mode=index\|live&source&dataset&only_conformant` | search + policy verdict per hit |
| `GET /api/dataset/dcat?id=<iri>` | the dataset as the partner published it (DCAT-AP + ODRL JSON-LD) |
| `GET /api/dataset/cdif?id=<iri>` | a dataset as CDIF (schema.org JSON-LD) |
| `GET /api/dataset/codemeta?id=<iri>` | a software asset as CodeMeta (schema.org SoftwareSourceCode) |
| `GET /api/dataset?id=<iri>` | flattened index record |
| `GET/POST /api/sources`, `DELETE /api/sources/{id}` | list, register, remove catalogues |
| `POST /api/harvest` · `GET /api/vocab` | re-harvest · vocabulary mappings |

## Demo script (about 10 minutes)

0. **Frame it.** The *How this works* panel on the catalogue page explains the four layers (DCAT-AP = what exists,
   ODRL = what you may do, CDIF/CodeMeta = what's inside, SHACL + vocabularies = what we agree on) and the federation
   point: metadata and terms travel, data stays. Collapse it once explained.

1. **A partner publishes one file.** Open http://localhost:8080/deltares/ — organisation → datasets → ODRL offer,
   rendered from `catalog.jsonld`. Click *view DCAT source*. The badge shows it is listed in the DigiLab catalogue.
2. **Search across partners.** Click *View in DigiLab catalogue*, then search `horticulture`, purpose *research*,
   NL → Deltares FTO (allowed, must inform) and the FAIR2GROW tomato trial (allowed, must attribute), grouped by organisation.
   Each hit shows its ODRL offer as a tree; *ODRL (JSON)* opens the offer exactly as published.
3. **Purpose changes the answer.** Switch to *commercial* and search `greenhouse` → Deltares flips to *Not allowed*;
   KNMI stays allowed with attribution. Set *Where used* to *outside EU* → the tomato trial falls outside its offer.
4. **Open metadata, closed payload.** Search `sensitive` → Naturalis precise coordinates: *Request access*;
   the generalised version: *Allowed*. Under *Advanced options*, switch action to *distribute* → the precise set is prohibited.
5. **Shared meaning.** Click a keyword tag to find all datasets with that keyword across partners; the ↗ next to it
   opens the concept found via an ontology lookup service (AGROVOC, AgroPortal/CGO, EDAM). `≈` marks a close match only
   (sensitive species → EDAM "Data protection"), `link` a related resource rather than a term (BOLD, iBOL Europe list).
   Purposes in the ODRL tree link to DPV. Dashed `?` links are unmapped terms — the Vocabulary Hub's job. Stress that
   these links are examples, not curated mappings. See *Standards & mappings → Vocabularies*.
6. **Built on standards, many representations.** On a dataset: *DCAT-AP (as published)* vs *CDIF*. The tomato trial
   describes its variables, so its CDIF includes `variableMeasured` with QUDT units; Deltares is dataset-level only.
   The *Standards & mappings* page has the field-by-field DCAT → CDIF table.
6b. **Software is an asset too.** Set *Asset type* to *software* → sdmdl and the iBOL Europe / BGE gap-list app,
   published by Naturalis as `dcat:Resource` + `schema:SoftwareSourceCode`, each with an MIT-based ODRL offer
   (use, duty to attribute), related publications/data, and a generated *CodeMeta* view instead of CDIF.
7. **Governance.** Under *Advanced options*, tick *only conformant metadata* → the KNMI radiation record disappears; it lacks a description
   required by the agreed minimum (`dcat-odrl-min.ttl`).
8. **Adding a partner.** Open http://localhost:8080/maris/ — badge: *not yet in DigiLab catalogue*. In the catalogue,
   *Partners & registration*: paste `http://localhost:8080/maris/catalog.jsonld`, name `MARIS`, *Register & harvest*.
   It is SHACL-checked and searchable at once (try `water`, purpose *commercial* → allowed, attribute + pay).
   The MARIS page badge now reads *listed*. *remove* resets it.
9. **Harvest vs live.** Under *Advanced options*, set *Access method* to *live federated query*, then take a partner offline
   (`mv partners/deltares partners/_off`). Live loses its dataset; the harvested index still serves it, possibly stale.

## Honest limits

- ODRL has no standard evaluation algorithm; `policy.py` implements a deliberately small profile.
  Purpose values are a demo vocabulary; only `research` and `commercial` are mapped (to DPV).
- The catalogue **states** terms; it does not enforce them. Enforcement belongs to connectors
  (Dataspace Protocol / Eclipse EDC), which consume this same DCAT + ODRL offer shape.
- The CDIF output follows the structure of the CDIF Data Description v1.1.1 example; it is not validated against
  the CDIF shapes. Variable roles (Measure/Descriptor) are a heuristic.
- Vocabulary links are examples of ontology lookup (AGROVOC, AgroPortal/CGO, BioPortal/EDAM, NERC Vocabulary Server), not
  curated mappings; check them before showing externally. Lookup services are listed in `config/vocab.json`.
- Production would add incremental harvest (`dct:modified`), signed catalogues, verifiable credentials for parties,
  and the Vocabulary Hub in place of `config/vocab.json`.
- The FAIR2GROW record is a placeholder: swap in the real 4TU dwarf tomato record and DOI.
- Software descriptions were written from the public GitHub READMEs; check them with the maintainers before showing externally.
- Background: Beyvers et al. (2026), *Towards FAIR and federated data ecosystems for interdisciplinary research*,
  PLoS Comput Biol 22(2): e1013806 — see *Standards & mappings → Federation*.
