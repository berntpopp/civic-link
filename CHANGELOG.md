# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.1] - 2026-11-20

Fixes from the agent UX evaluation (`docs/benchmarks/agent-ux-results.md`). No tool or
parameter changes.

### Fixed

- `get_molecular_profile` counts the live evidence list (CIViC's cached per-profile counters
  lag it), lists ACCEPTED assertions in full, and lists the others, REJECTED included, in
  `other_assertions` (CIViC's profile connection omits rejected ones).
- Errors: a malformed EID/AID names the argument and its string form; an unknown EID/AID points
  to its own browse tool; a foreign gene ID error also gives a standalone retry; cross-server
  `next_commands` say they are genefoundry router tools.
- `search_molecular_profiles` accepts `GENE p.X123Y` and the `ClinVar:<id>` CURIE.
- Capabilities advertise each paged tool's own default and maximum limit.

### Added

- `search_molecular_profiles`: `simple_total` / `complex_total`, `counts_note`,
  `query_normalized`; rows drop the redundant per-row `kind`.
- `search_evidence_items`: `counts_by_level` and `match_notes` (a name widens, a code is
  exact); minimal rows carry status and the disease name.
- `get_assertion`: each evidence item's status, level, profile and PMID.
- Agent UX evaluation protocol, frozen tasks, scripts and results (`docs/benchmarks/`).

## [0.1.0] - 2026-11-20

### Added

- First release: a read-only MCP server over the live CIViC GraphQL API
  (https://civicdb.org/api/graphql), router namespace `civic`. Tools:
  `search_molecular_profiles` (entry resolver: profile name, gene + variant, HGVS, ClinGen
  CAID or ClinVar variation ID; simple and complex profiles returned apart),
  `get_molecular_profile`, `get_variant`, `search_evidence_items` (accepted by default),
  `get_evidence_item`, `search_assertions` (accepted by default), `get_assertion`,
  `get_gene`, plus `get_server_capabilities` and `get_diagnostics`.
- One fixed GraphQL document per tool; callers never send GraphQL. Outbound requests are
  limited to `civicdb.org`.
- GraphQL errors (HTTP 200 + `errors[]`) become typed envelope errors naming the parameter;
  limits stay within CIViC's silent 100-node page cap, and `total`/`truncated` come from
  CIViC's `totalCount`.
- Coordinates carry their `assembly` (CIViC's primary coordinates are GRCh37); genomic HGVS
  is labelled per assembly, so the GRCh38 form is explicit. Diseases are returned as DOID.
- Oncogenicity (ClinGen/CGC/VICC, Horak 2022), actionability (AMP/ASCO/CAP tier and level)
  and germline pathogenicity (ACMG/AMP) are separate fields, never one "significance".
- Evidence statements and assertion summaries are fenced as untrusted text
  (Response-Envelope v1.1). An empty result says "no CIViC evidence found", never
  "not actionable".
- `data_version` = the latest monthly CIViC data release plus a `live:<timestamp>` stamp.
