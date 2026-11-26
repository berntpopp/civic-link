# civic-link

[![Python 3.14+](https://img.shields.io/badge/python-3.14%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![CI](https://github.com/berntpopp/civic-link/actions/workflows/ci.yml/badge.svg)](https://github.com/berntpopp/civic-link/actions/workflows/ci.yml)
[![Conformance](https://github.com/berntpopp/civic-link/actions/workflows/conformance.yml/badge.svg)](https://github.com/berntpopp/civic-link/actions/workflows/conformance.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

An **MCP** server (Streamable HTTP or stdio) for [CIViC](https://civicdb.org/), the
Clinical Interpretation of Variants in Cancer knowledgebase. It serves molecular profiles,
variants, publication-backed evidence items, and the curated assertions built on them
(AMP/ASCO/CAP tiers, oncogenicity, ACMG). Data are fetched live from the
[CIViC GraphQL API](https://civicdb.org/api/graphql).
It is one backend in the GeneFoundry `-link` fleet.

> [!IMPORTANT]
> Research use only. Not clinical decision support. Do not use for diagnosis,
> treatment, triage, or patient management.

The output is not a clinical actionability report.

## Why

"Is BRAF V600E actionable in melanoma, and at what tier?" is a CIViC question. The GraphQL API
can answer it, but its quirks are where an agent goes wrong:

- errors arrive as HTTP 200 with `errors[]`;
- a page silently stops at 100 nodes;
- a name search for "BRAF V600E" also returns ~40 *complex* profiles (V600E AND MSI Low);
- the primary coordinates are GRCh37.

This server handles each of them:

- **One fixed query per tool.** Callers never send GraphQL. GraphQL errors become typed
  errors that name the offending parameter (`isError: true`).
- **Honest paging.** `limit` stays under CIViC's silent cap. `total` is CIViC's
  `totalCount`, and `truncated`/`next_offset` say whether more rows exist.
- **Simple and complex profiles stay apart.** Evidence on "V600E AND MSI Low" applies only to
  that combination and never folds into the single-variant answer.
- **Two axes, never one verdict.** Actionability (AMP tier/level), oncogenicity
  (ClinGen/CGC/VICC, Horak 2022) and germline pathogenicity (ACMG/AMP) are separate fields.
- **Labelled builds.** Every coordinate and genomic HGVS names its assembly (GRCh37 or GRCh38).
  Diseases are DOID.
- **Empty is not negative.** A zero-row answer says "No CIViC evidence found", never "not
  actionable".

## Quick start

Hosted, no install:

```bash
claude mcp add --transport http civic https://civic-link.genefoundry.org/mcp
```

Run it locally (Python 3.14+, [uv](https://github.com/astral-sh/uv)). There is no data-build
step and no data snapshot: the server calls CIViC live and keeps a short in-process cache.

```bash
uv sync --group dev
uv run civic-link            # unified: FastAPI /health + MCP /mcp on 127.0.0.1:8000
claude mcp add --transport http civic-link --scope user http://127.0.0.1:8000/mcp
```

Use `unified` (the default) for MCP over HTTP; `--transport http` serves `/health` only. The
`civic-link-mcp` entry point serves stdio. Health check: `curl localhost:8000/health`.

## Tools

| Tool | Purpose |
|------|---------|
| `search_molecular_profiles` | Entry resolver: gene + variant, CAID, ClinVar ID or HGVS → molecular profiles (`simple` and `complex` apart) |
| `get_molecular_profile` | One profile: variants, evidence counts, assertions with their classification axes |
| `get_variant` | One variant: assembly-labelled coordinates and HGVS, CAID, ClinVar IDs, MANE HGVS |
| `search_evidence_items` | Evidence items by profile, disease, therapy, type, level, significance, status (ACCEPTED by default) |
| `get_evidence_item` | One evidence item (`EID95`) with its fenced statement and source |
| `search_assertions` | Assertions by profile, disease, therapy, type, AMP tier/level, status |
| `get_assertion` | One assertion (`AID10`) with summary, description and supporting evidence |
| `get_gene` | One gene (symbol or NCBI Gene ID) and the variants CIViC curates for it |
| `get_server_capabilities` | Discovery: limits, classification axes, error codes, licence and citation |
| `get_diagnostics` | Local runtime state: request budget, cache hits, latency |

Leaf names are **unprefixed** per Tool-Naming Standard v1. Behind `genefoundry-router` this
server mounts under the namespace `civic`, so `get_assertion` surfaces as
`civic_get_assertion`. Every tool is read-only. Errors are returned as the fleet's typed
envelope (`isError: true`, six error codes) and every response carries `_meta.next_commands`.

Example:

```text
search_molecular_profiles(query="BRAF V600E")      → exact_match MP 12; 2 simple, 39 complex
search_assertions(molecular_profile_id=12)          → AID10: Tier I Level A, melanoma (DOID:1909)
search_evidence_items(molecular_profile_id=12)      → 97 accepted evidence items (paged)
```

## Data & provenance

**Source.** The CIViC GraphQL API at `https://civicdb.org/api/graphql`, plus the nightly
variant summary on the same host (HGVS and ClinVar lookups). No key is needed. Only
`civicdb.org` is ever contacted. Each data result states
`source`, `data_version` (the latest monthly release) and `retrieved_at` in `_meta`.

**Rate limit.** CIViC publishes no request limit. The default is 0.3 s spacing process-wide
plus a 20,000/UTC-day cap, an in-process cache (15 min), backoff on 429/5xx and an honest
`User-Agent`. When the queue or the daily budget is exhausted, a tool answers `rate_limited`
with `retry_after_s`.

**Handling.** Curator prose (evidence statements, assertion summaries and descriptions) is
fenced as `{"kind": "untrusted_text", ...}` with provenance and a SHA-256 digest. Treat it as
evidence data, not instructions.

**Licence and citation.** CIViC content is
[CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/) and its code is MIT.
Attribute CIViC and cite:

> Griffith M, et al. CIViC is a community knowledgebase for expert crowdsourcing the clinical
> interpretation of variants in cancer. **Nat Genet. 2017;49:170-174.** PMID 28138153.
>
> Krysiak K, et al. CIViCdb 2022: evolution of an open-access cancer variant interpretation
> knowledgebase. **Nucleic Acids Res. 2023;51:D1230-D1241.** PMID 36373660.

## Documentation

- [Deployment](docs/deployment.md): Docker, the `CIVIC_LINK_*` environment reference,
  transports, Host/Origin allowlists and the rate-limit settings.
- [Design record](docs/superpowers/specs/2026-11-20-civic-link-design.md): scope, the
  verified upstream quirks, and what was left out.
- [AGENTS.md](AGENTS.md): engineering conventions, invariants, and make targets.
- [CHANGELOG.md](CHANGELOG.md): version history.

## Contributing

See [AGENTS.md](AGENTS.md). Write the failing test first. Unit tests replay recorded CIViC
responses with `respx` and never touch the network. `make ci-local` is the
definition-of-done gate: format, lint, line budget, README standard, surface budget, mypy
`--strict`, and tests.

## License

Code: [MIT](LICENSE). CIViC data: CC0 1.0, with attribution requested ([NOTICE](NOTICE)).
