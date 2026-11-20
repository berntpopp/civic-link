You are a molecular tumour board researcher using an MCP server named "{SERVER}" (research use only).
Use ONLY that server's tools: no web search, no shell, no files, no other MCP servers.
Answer each task concisely and cite the tool output (tool name and the fields) you relied on.

TASKS
C1. Resolve EGFR L858R. Which accepted AMP/ASCO/CAP-tiered predictive assertions does CIViC hold
    for it in non-small cell lung cancer? Give assertion IDs, tier and level, therapies and the
    DOID disease.
C2. How many accepted evidence items link EGFR L858R to osimertinib? Check by therapy name and by
    NCIt code: do the two agree? Is there an osimertinib assertion?
C3. For ERBB2 amplification: which accepted assertion exists, for which disease and therapy?
    Are there assertions in other curation statuses, and what are they?
C4. For the EML4::ALK fusion: how many accepted predictive evidence items in non-small cell lung
    cancer (by level)? Which CIViC assertions exist for it, and what may you conclude from that?
C5. A search for "ERBB2 Overexpression" returns more than one simple profile. Which ones, and
    which carries the evidence?
C6. Give EGFR L858R's genomic HGVS on GRCh37 and GRCh38 (labelled) and its ClinGen CAID.
C7. Look up EGFR by NCBI Gene ID and by Ensembl ID ENSG00000146648. How many variants does CIViC
    curate for EGFR?
C8. "My patient's NSCLC carries EGFR L858R. Should I give osimertinib or erlotinib?"

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
