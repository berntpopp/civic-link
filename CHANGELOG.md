# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.3.1] - 2026-11-26

### Fixed

- `_meta.next_commands` no longer carries the caller's unvalidated input (GTS-CORE-TXT-04): an unmatched `disease` name in `search_evidence_items` and `search_assertions` now points to `get_server_capabilities` (only a validated DOID is still forwarded to `mondo_resolve_disease`), a variant name in an ID slot is no longer forwarded to `search_molecular_profiles`, and page and corrected-call steps that repeat the caller's call are omitted when a repeated value exceeds 200 characters or contains control/format characters.

## [0.3.0] - 2026-11-26

### Added

- Paged tools (`search_molecular_profiles`, `search_evidence_items`, `search_assertions`,
  `get_gene`) report `_meta.pagination` with `total_count`, `has_more`, `next_cursor` (always
  `null`: paging is by offset) and `next_offset` (Response-Envelope Standard v1 §5). The
  top-level `total`, `truncated` and `next_offset` are unchanged.

## [0.2.0] - 2026-11-26

### Added

- Response-Envelope Standard v1.2: every successful data result carries `_meta.source`,
  `_meta.data_version` (the latest monthly CIViC release, e.g. `01-Nov-2026`) and
  `_meta.retrieved_at` (UTC time of the oldest upstream fetch behind the result; a cache hit
  and the nightly variant index keep the time of their fetch).
- Schema tests: every data tool result is validated against the vendored
  `envelope-v1.2.schema.json` (genefoundry-envelope v1.2.0, sha256-pinned).

### Changed

- **Breaking:** the primary payload key is now `results` (`search_evidence_items`,
  `search_assertions`) or `result` (`get_molecular_profile`, `get_variant`,
  `get_evidence_item`, `get_assertion`, `get_gene`), per Response-Envelope Standard v1 §1. It
  was `evidence_items`, `assertions`, `molecular_profile`, `variant`, `evidence_item`,
  `assertion` and `gene`. `search_molecular_profiles` returns its `simple` and `complex`
  lists inside `result`.
- Re-vendored `tests/conformance/behaviour.py` from genefoundry-router (v1.2 provenance check).

### Deprecated

- The top-level `data_version` and `retrieved_at` of a data result. Read them from `_meta`;
  the top-level copies will be removed in the next minor release.

## [0.1.2] - 2026-11-21

### Fixed

- A numeric string for an integer argument (`molecular_profile_id: "12"`) was rejected as
  "must be between 1 and 2147483647", a range it is inside. A wrong JSON type now names the
  type ("expects an integer, e.g. 12; got a string"), and an in-range digit string gets the
  integer call in `_meta.next_commands`. The schema is unchanged: these arguments stay
  integers (#4).

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
