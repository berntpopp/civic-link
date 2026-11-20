# civic-link design (2026-11-20)

> Historical record — the v0.1.0 design as built; the live contract is `get_server_capabilities` and the README.

Tracking issue: [genefoundry-router#347](https://github.com/berntpopp/genefoundry-router/issues/347).
Source plan: genefoundry-router `docs/plans/2026-11-20-cancer-somatic-expansion.md` §2 (CIViC
row), §3 item 4, §4; evidence report A (`A-civic-metakb-cgi.md`).

## Goal

A read-only MCP backend over CIViC (CC0 data, MIT code), federated by genefoundry-router
under the namespace `civic`. It is the fleet's first somatic actionability and oncogenicity
source. Template: `pgscatalog-link` (live API, fleet scaffolding kept unchanged).

## Upstream

- `POST https://civicdb.org/api/graphql`: no auth, ~0.6 s per query.
- `GET https://civicdb.org/downloads/nightly/nightly-VariantSummaries.tsv` (~600 kB): the only
  place CIViC exposes HGVS and ClinVar IDs in a searchable form. It is loaded on demand
  and kept in memory for 24 h.
- Outbound allowlist: `civicdb.org` only, derived from the configured base URL.

## Tools (10; ≤ 10k tokens in total)

| Tool | GraphQL document |
|---|---|
| `search_molecular_profiles(query)` | `MP_SEARCH` (name / CAID / variant id) |
| `get_molecular_profile(molecular_profile_id)` | `MP_GET` |
| `get_variant(variant_id)` | `VARIANT_GET` |
| `search_evidence_items(...)` | `EVIDENCE_SEARCH` |
| `get_evidence_item(evidence_id)` | `EVIDENCE_GET` |
| `search_assertions(...)` | `ASSERTION_SEARCH` |
| `get_assertion(assertion_id)` | `ASSERTION_GET` |
| `get_gene(gene)` | `GENE_GET` |
| `get_server_capabilities`, `get_diagnostics` | none |

Each tool uses one fixed document from `civic_link/queries.py`. Caller values travel only as
GraphQL variables; callers never send GraphQL. Two helper documents (`DISEASE_LOOKUP`,
`THERAPY_LOOKUP`) check that disease and therapy filters exist, and `RELEASES` provides
`data_version`.

## Hazards and how each is handled

- **HTTP 200 + `errors[]`.** An error on `Variable $x` becomes `invalid_input` with
  `field=x`. Variables are named after the tool parameters, and the name is echoed only if
  it is one of the request's own variables. Any other GraphQL error becomes
  `upstream_unavailable` with `field=response`. Upstream text is never echoed.
- **Silent 100-node page cap.** `limit` is capped at or below 100 in the schema.
  `total` = upstream `totalCount`. Offsets map to CIViC's cursors (`base64(offset)`).
  `truncated`/`next_offset` are derived from those.
- **Complex molecular profiles.** The name search for "BRAF V600E" returns 1 simple and
  ~39 complex profiles. They are returned as separate `simple` and `complex` lists, and
  `exact_match` is only ever a simple profile.
- **GRCh37-first.** `coordinates.assembly` is set on every coordinate block. Genomic HGVS is
  labelled by the RefSeq chromosome accession version (GRCh38 = `NC_0000NN` version in a
  fixed table; GRCh37 = that version − 1), so the GRCh38 HGVS is explicit.
- **Diseases are DOID.** They are returned as `DOID:<n>`. The MONDO crosswalk belongs to the
  router skill (via mondo-link).
- **Two axes.** Each assertion carries `actionability` (AMP/ASCO/CAP tier and level, FDA
  companion test, regulatory approval, NCCN) or `oncogenicity` (ClinGen/CGC/VICC
  classification and codes, Horak 2022) or `germline_pathogenicity` (ACMG/AMP), chosen by
  the assertion type. There is never a shared "significance" verdict.
- **Untrusted prose.** Evidence statements, assertion summaries and descriptions, and gene
  and profile descriptions are fenced (`untrusted_text`).
- **Empty is not negative.** A zero-row evidence or assertion answer, or a profile without
  accepted evidence, says "No CIViC evidence found …", never "not actionable".
- **Silently-empty filters.** Disease and therapy filters are checked first. An unknown name,
  DOID or NCIt code becomes `not_found` naming the parameter. An unknown molecular profile
  behind a zero-row search is also `not_found`.
- **Foreign gene IDs.** `get_gene` accepts a symbol or an NCBI Gene ID. An Ensembl or HGNC ID
  is rejected with `invalid_input`, `allowed_values` and a converter step
  (`hgnc_resolve_symbol`).
- **`data_version`** = `CIViC <latest monthly release>; live:<UTC timestamp>`.

## Out of scope (v0.1.0)

CGI biomarker TSV fold-in, VRS normalisation, a `list_data_releases` tool, and the
agent UX eval. The last is listed as an open risk.
