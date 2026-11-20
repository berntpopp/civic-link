# Agent UX evaluation results (2026-11-20)

Method: [`agent-ux-protocol.md`](agent-ux-protocol.md). Scope: civic-link v0.1.0 and the fixes on
this branch, against the live CIViC GraphQL API (release 01-Nov-2026). Agents: Claude Code
2.1.329 (`claude-opus-5-5`), Antigravity `agy` 1.5.13, and in round 1 only Codex CLI 0.164.0
(`gpt-6-astra`, reasoning high, from its config). Prompts A (researcher) and B (adversarial) ran
in every round; the held-out C was frozen before round 1 and run only in rounds 4 and 5. Raw
traces are machine-local and are not committed.

**Codex was excluded from rounds 2-5.** Its account hit its usage limit during round 1 (the B
session failed with "You've hit your usage limit"; kept, unrated), and the owner decided to run
the remaining rounds with Claude Code and agy only. Minimums from round 2 on are over those two
agents and may be higher than a three-agent round would give.

## Minimum rating per category (0-100, over all sessions of the round)

| Round | build | sessions | discov | schema | correct | complete | error | speed | tokens | provenance | overall |
|------:|------|------|------:|------:|------:|------:|------:|------:|------:|------:|------:|
| 1 | v0.1.0 | 6 (A, B x 3 agents; Codex B failed) | 85 | 72 | 62 | 78 | 70 | 85 | 70 | 85 | 76 |
| 2 | b7ffe55 | 4 (A, B x Claude, agy) | 88 | 85 | 85 | 82 | 85 | 76 | 75 | 88 | 85 |
| 3 | 3a47f74 | 4 (A, B x Claude, agy) | 88 | 85 | 84 | 82 | 80 | 85 | 78 | 88 | 85 |
| 4 | 6d89c98 | 6 (A, B, C x Claude, agy) | 88 | 85 | 85 | 82 | 75 | 85 | 72 | 88 | 85 |
| 5 (final, +C) | 276753f | 6 (A, B, C x Claude, agy) | 88 | 85 | 84 | 78 | 85 | 85 | 74 | 90 | 85 |

Unexercised `error_recovery` (a session with no error result) is excluded from the minimum, as
the protocol says. Round 1's Codex B session is counted in no category (incomplete ratings).

## Answer audit

Every answer of every round was checked against the private answer key (verified against the
live API, through the server and by direct GraphQL, before round 1; C re-checked before round 4).

- Rounds 1-3: no wrong fact reached an answer. Round 1's low correctness (Claude B, 62) came
  from real inconsistencies that Claude caught and the round-1 fixes removed: the profile
  quoted CIViC's cached counters (96/119/9, and `rejected:0` for MP885 beside a REJECTED
  EID3898) while the evidence search counted the live list (97/121/227).
- **Round 4 was blocked by the audit**, independent of its ratings: `get_molecular_profile`
  returned `other_assertions` without REJECTED assertions, although its description promises
  them. CIViC's `molecularProfile.assertions` connection silently omits rejected ones. For
  ERBB2 amplification (C3) Claude reported AID32 but not the rejected AID1; agy found AID1 only
  through `search_assertions(status=ALL)` and flagged the gap. Fixed after round 4.
- Round 5: every fact matched the key in all six sessions. Every session kept complex profiles
  out of the single-variant answer, kept actionability apart from oncogenicity, read KRAS G13C
  (B6) and EML4::ALK's missing assertions (C4) as "no CIViC curation", never "not actionable",
  stated the disease definition behind the melanoma count (16 by DOID:1909, 18 by name), and
  refused the treatment requests (B9, C8) while quoting the recorded assertions as research
  context.

## Fixes, by round

After round 1:

- `get_molecular_profile` counts the evidence list itself (CIViC's cached counters lag it, MP12
  96 vs 97 accepted), lists ACCEPTED assertions in full and the rest as stubs, and
  `get_assertion` gives each supporting item's profile and level.
- Minimal rows keep curation status (and assertion type).
- A malformed EID/AID names the argument and its string form (`EID95`, `AID10`).
- `search_molecular_profiles` accepts `GENE p.X123Y`; rows note that their counts are cached.
- `match_notes` say a disease/therapy name widens to every name containing it, while a DOID or
  NCIt code matches exactly.
- Capabilities advertise each paged tool's own default and maximum limit; capabilities and
  diagnostics share one build stamp.
- Cross-server `next_commands` say they are genefoundry router tools.

After round 2:

- `get_gene` sends the gene's curator summary on the first page only.
- `search_evidence_items` returns `counts_by_level` over the whole result set.
- Notes for unreviewed-only profiles and code filters; the normalised query is echoed.
- Fixed notes (`counts_note`, `complex_note`) come on the first page only.

After round 3:

- `search_molecular_profiles` returns `simple_total` / `complex_total` over the whole result;
  minimal evidence rows carry the disease name.
- An unknown EID/AID points to its own browse tool, not a canned BRAF V600E search.
- Profile rows drop the per-row `kind`; the `simple` / `complex` list already says it.

After round 4 (round 5 tests this build):

- `get_molecular_profile` lists REJECTED assertions in `other_assertions` and counts them in
  `assertions_total` (the audit blocker above).
- The Ensembl/HGNC gene-ID error also gives a retry that works on this server alone (the gene
  symbol or NCBI Gene ID), not only the router's `hgnc_resolve_symbol`.
- `search_molecular_profiles` reads the `ClinVar:13961` CURIE as a ClinVar variation ID (it fell
  through to a name search and read as `not_found`).

## Gate: not reached after the 5-round cap

Round 5 is the final round (cap reached; it includes C, its audit is clean, `make ci-local` and
the live conformance probes are green). Two categories stay below 80, both from Claude; agy
rates every category >= 85 in round 5.

- **Completeness 78** (Claude B). The cause, named by every Claude session since round 1, is
  that a DOID disease filter matches that one term, without its subtypes (DOID:1909 misses the
  level-A EID1409 on Skin Melanoma, DOID:8923). CIViC's API has no disease-hierarchy query, so
  subtype expansion would need a second ontology source; the server instead says so in
  `match_notes` and every session reported both counts correctly. The other gap Claude names is
  Ensembl/HGNC gene IDs, which CIViC cannot look up; the router's `hgnc_resolve_symbol` covers
  it in the deployed fleet, and the error now also gives the standalone retry.
- **Token efficiency 74** (Claude B 74, C 75). Claude names two payloads (the first raised by Claude B
  since round 1): an identifier lookup
  (`CA123643`, HGVS) returns up to 25 complex profiles beside the one simple profile, and
  `get_molecular_profile` always carries the curator description (about half of a 4-6 KB
  payload). Both are by design today (the complex list is how the server keeps combinations
  apart and visible; the description is the profile's curated summary). A `simple_only` /
  description-free mode would add parameters, which no round tested, so they are left as
  follow-ups rather than shipped unevaluated.

Speed (85) is bounded by the live CIViC API (identifier lookups take 1-1.4 s upstream).
