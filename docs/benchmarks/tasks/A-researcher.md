You are a cancer genomics researcher evaluating an MCP server named "{SERVER}" (research use only).
Use ONLY that server's tools: no web search, no shell, no files, no other MCP servers.
Answer each task concisely and cite the tool output (tool name and the fields) you relied on.

TASKS
A1. Resolve "BRAF V600E" to its single-variant molecular profile. Give its ID, how many profiles
    the name search matches in total and how many of them are complex, and say why the complex
    ones are kept out of the answers below.
A2. How many accepted predictive evidence items does CIViC hold for that profile in melanoma?
    Break them down by evidence level, and state exactly how you defined "melanoma".
A3. Which accepted AMP/ASCO/CAP-tiered predictive assertions exist for BRAF V600E in melanoma?
    For each: assertion ID, tier and level, therapies with their NCIt codes, the DOID disease,
    and whether there is an FDA companion test.
A4. For assertion AID10, list its supporting evidence items with their source PubMed IDs, and
    say which molecular profile each evidence item is attached to.
A5. Give the variant's genomic HGVS on GRCh37 and on GRCh38 (labelled), its ClinGen CAID and
    its ClinVar IDs.
A6. Separately from actionability: what does CIViC assert about the oncogenicity of BRAF V600E
    in melanoma (assertion ID, classification, criteria codes)?
A7. Which CIViC data release did your answers come from, what licence covers the data, and how
    should the source be cited?

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
