# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
