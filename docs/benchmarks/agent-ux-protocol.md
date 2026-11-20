# Agent UX evaluation protocol

How we test civic-link the way it is used: real agent CLIs, each with only this MCP server
mounted, doing realistic and adversarial CIViC work, then rating the experience. It is
adapted from pgscatalog-link's `docs/benchmarks/agent-ux-protocol.md`.

## Agents

Each prompt runs once per agent per round against one local server
(`python server.py --transport unified --port 18501`). The three agents run in parallel, each
working through the prompts in sequence, so at most 3 sessions run at a time. Each session also
holds one slot of a fleet-wide session semaphore (`SLOT=...`), and its wall clock starts only
after the slot is acquired, so queueing is not timed.

| Agent | Invocation (see `scripts/agent_ux_session.sh`) | Isolation |
|-------|------------------------------------------------|-----------|
| Claude Code | `claude -p --model opus --strict-mcp-config --tools ""` | only this MCP; no built-in tools, user settings, hooks or plugins |
| Codex CLI | `codex exec --json -s read-only -c mcp_servers.eval_civic.url=...` | read-only sandbox, empty working directory |
| Antigravity (`agy`) | `agy -p` with the server added through `agy mcp add eval-civic-link` | empty working directory; other user MCP servers stay mounted, the prompt forbids them |

Record the model each client actually resolved (Claude's `init` event, Codex's config). Never
substitute a model silently. Keep every session, including failed or timed-out ones.

## Tasks

Prompts live in `tasks/` and are frozen before a round. `{SERVER}` is replaced by the mounted
name.

- `A-researcher.md`: "Is BRAF V600E actionable in melanoma?" end to end. Resolve the simple
  (not complex) molecular profile, count accepted predictive evidence by level, the AMP-tiered
  assertions with therapies (NCIt) and DOID disease, an assertion's supporting evidence and
  PubMed IDs, GRCh37 versus GRCh38 HGVS, and an oncogenicity assertion kept apart from
  actionability; then data release, licence and citation.
- `B-adversarial.md`: CIViC's real traps. Complex profiles that match "BRAF V600E" by name,
  paging past CIViC's silent 100-row page cap to an honest total, a ClinVar ID linked to two
  variants (V600 and V600E), HGVS / CAID / free-text resolver paths, disease name (substring)
  versus DOID (exact), a variant with no accepted evidence (must read as "no CIViC evidence",
  never "not actionable"), unknown and malformed evidence/assertion IDs, foreign gene IDs
  (Ensembl, HGNC), an over-cap page size, and a request for patient treatment advice.
- `C-fresh.md`: written and frozen before round 1, never shown before the final round. Other
  genes and tumours (EGFR L858R in NSCLC, ERBB2 amplification, EML4::ALK fusion, an expression
  profile) check that fixes generalise instead of fitting the A/B wording.

Agents get no answer key and no score target. A private answer key, verified against the live
CIViC API (through the server and by direct GraphQL) before round 1, is kept with the run
artefacts, outside the repo.

## Ratings

Each session rates 9 categories as an integer 0-100 and justifies each with a concrete
interaction. It also lists its friction points and suggested improvements:

`discoverability`, `schema_clarity`, `correctness_confidence`, `completeness`,
`error_recovery`, `speed`, `token_efficiency`, `provenance_citation`, `overall_usability`.

`scripts/agent_ux_scores.py <round-dir>` parses the ratings and adds measured MCP calls, error
results, client tokens (Claude, Codex) and wall time. A missing rating counts as a failure, not
as 100.

Unexercised categories: a session whose trace has no error result cannot measure error
recovery. Its `error_recovery` rating is shown in brackets and left out of the minimum. agy
writes no trace, so its ratings always count.

Speed is partly upstream-bound: the server spaces CIViC calls 0.3 s apart process-wide and the
sessions of a round share one server.

## Gate

A round passes when **every category's minimum over all sessions is >= 80**. Averages are never
used, so one bad session cannot be hidden. It must also pass all of:

1. Every answer is audited against the answer key. A wrong fact the server caused (misleading
   field, dishonest count, an empty result read as "not actionable") blocks the round whatever
   the self-ratings say.
2. The final round includes `C-fresh.md`.
3. `make ci-local` and the live conformance probes stay green.

At most 5 rounds; if the gate is still not met, the blocking categories are reported with
evidence.

## Improvement loop

1. Run the round: `scripts/agent_ux_eval.sh <out>/round-N` (pass the C glob in the final round).
2. Triage the friction lists into server defects, missing affordances and evaluator noise.
   Fix defects; add an affordance only when several sessions or one blocking task need it.
   Do not tune wording to one prompt.
3. Review each change in ponytail style (the smallest complete change; a test per behaviour
   change) and run `make ci-local`.
4. Restart the server and rerun every prompt. Never drop a low-scoring session or reword a task
   to raise its score.

The rounds and their scores are written up in `agent-ux-results.md`.
