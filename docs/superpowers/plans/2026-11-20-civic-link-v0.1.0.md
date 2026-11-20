# civic-link v0.1.0 implementation plan (2026-11-20)

> Historical record — the build plan for v0.1.0; see the design spec in `../specs/` and the README for the live contract.

1. Clone the `pgscatalog-link` scaffolding and rename the package, settings prefix, resources and
   namespace. Vendor `tests/conformance/` byte-identical from genefoundry-router `main`, including
   `identifiers.py`/`identifiers.json`, and add `identifiers.local.json`.
2. Client (TDD): a GraphQL POST with a fixed document and variables, mapping `errors[]` to typed
   errors with the parameter as `field`, and a TSV GET on the same origin. Keep the host
   allowlist, byte cap, retries and cache from the template.
3. Service plus shapers (TDD, recorded fixtures from the live API on 2026-11-20): the 8 data
   tools, honest paging, separate simple and complex lists, assembly labels, DOID, the two
   classification axes, fencing, and the "no CIViC evidence found" note.
4. MCP tool registration, capabilities, README tool table, surface-budget and naming guards.
5. Live acceptance: BRAF V600E → MP 12, accepted EIDs, AID10 Tier I Level A.
6. `make ci-local`, PR, ponytail review, merge, tag `v0.1.0`, and approve the release environment.
