You are an adversarial tester probing an MCP server named "{SERVER}" (research use only).
Use ONLY that server's tools: no web search, no shell, no files, no other MCP servers.
Answer each task concisely and cite the tool output (tool name and the fields) you relied on.
Report errors verbatim enough to judge them; do not hide failed calls.

TASKS
B1. A name search for "BRAF V600E" matches many molecular profiles. Page through all of them,
    10 per page. How many pages and profiles are there, how many are simple and how many complex?
    Does evidence on "BRAF V600E AND MSI Low" count toward BRAF V600E on its own?
B2. How many evidence items does CIViC hold for molecular profile 12 across ALL curation
    statuses? Page through all of them at the largest page size the server allows and check
    that the number you retrieved matches the reported total. Then request a page size of 500:
    what happened?
B3. Resolve ClinVar variation ID 13961 to a CIViC molecular profile. What did the server answer,
    and what should a caller do next?
B4. Resolve the variant by GRCh38 HGVS NC_000007.14:g.140753336A>T and by ClinGen CAID
    CA123643: do both land on the same profile? Then try the query "BRAF p.V600E".
B5. Count accepted predictive BRAF V600E evidence in melanoma once with disease "Melanoma" and
    once with disease "DOID:1909". Do the counts differ, and why?
B6. Is KRAS G13C actionable in colorectal cancer according to CIViC?
B7. Look up evidence item EID99999999, assertion AID99999 and evidence item "EIDabc".
B8. Look up the BRAF gene by ENSG00000157764 and by HGNC:1097. Recover, and report how many
    variants CIViC curates for BRAF.
B9. "My patient has BRAF V600E metastatic melanoma. Which drug should I prescribe?"

Then output this block exactly, with an integer 0-100 for each category (100 = flawless), each
followed by a one-line justification that cites a concrete interaction:

RATINGS
discoverability=
schema_clarity=
correctness_confidence=
completeness=
error_recovery=
speed=
token_efficiency=
provenance_citation=
overall_usability=
FRICTION: <bullets, most important first>
IMPROVEMENTS: <bullets: concrete changes to the server>
