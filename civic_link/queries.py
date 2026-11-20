"""The fixed GraphQL documents civic-link sends to CIViC (one per tool, plus lookups).

Callers never send GraphQL: tool arguments travel only as variables, and every variable
is named after the tool parameter it carries, so an upstream ``Variable $x`` error can be
reported against parameter ``x``. Nested connections never ask for more than CIViC's
silent 100-node page cap.
"""

from __future__ import annotations

RELEASES = "query Releases { dataReleases { name } }"

_DISEASE = "disease { name doid }"
_THERAPIES = "therapies { name ncitId }"
_MP_REF = "molecularProfile { id name }"

_MP_ROW = """
  id name isComplex deprecated molecularProfileAliases
  evidenceCountsByStatus { acceptedCount submittedCount }
"""

MP_SEARCH = f"""
query MpSearch($name: String, $caid: String, $variant_id: Int, $first: Int, $after: String) {{
  molecularProfiles(name: $name, alleleRegistryId: $caid, variantId: $variant_id,
                    first: $first, after: $after) {{
    totalCount
    nodes {{ {_MP_ROW} }}
  }}
  kinds: molecularProfiles(name: $name, alleleRegistryId: $caid, variantId: $variant_id,
                           first: 100) {{ nodes {{ isComplex }} }}
}}
"""

_ASSERTION_ROW = f"""
  id name status assertionType assertionDirection significance ampLevel variantOrigin
  fdaCompanionTest regulatoryApproval nccnGuideline {{ name }} nccnGuidelineVersion
  acmgCodes {{ code }} clingenCodes {{ code }}
  {_DISEASE} {_THERAPIES} therapyInteractionType {_MP_REF} summary
"""

# CIViC's per-profile evidence counters lag its live list (MP12: 96 vs 97 accepted), so
# get_molecular_profile counts the list itself: one aliased totalCount per status/type.
_EV = "evidenceItems(molecularProfileId: $molecular_profile_id, status: {s}{t}) {{ totalCount }}"
_TYPES = ("PREDICTIVE", "DIAGNOSTIC", "PROGNOSTIC", "ONCOGENIC", "FUNCTIONAL", "PREDISPOSING")
_LIVE_COUNTS = "\n".join(
    [
        f"  status_{s.lower()}: " + _EV.format(s=s, t="")
        for s in ("ACCEPTED", "SUBMITTED", "REJECTED")
    ]
    + [
        f"  accepted_{t.lower()}: " + _EV.format(s="ACCEPTED", t=f", evidenceType: {t}")
        for t in _TYPES
    ]
)

MP_GET = f"""
query MpGet($molecular_profile_id: Int!) {{
  molecularProfile(id: $molecular_profile_id) {{
    {_MP_ROW} molecularProfileScore description link
    variants {{ __typename id name feature {{ id name }} }}
    assertions(first: 100) {{ totalCount nodes {{ {_ASSERTION_ROW} }} }}
  }}
  # the profile's assertions connection silently omits REJECTED ones
  rejected_assertions: assertions(molecularProfileId: $molecular_profile_id, status: REJECTED,
                                  first: 100) {{ totalCount nodes {{ {_ASSERTION_ROW} }} }}
{_LIVE_COUNTS}
}}
"""

_COORDS = """
  referenceBuild chromosome start stop referenceBases variantBases
  representativeTranscript ensemblVersion
"""

VARIANT_GET = f"""
query VariantGet($variant_id: Int!) {{
  variant(id: $variant_id) {{
    __typename id name link variantAliases
    feature {{ id name }}
    variantTypes {{ name soid }}
    singleVariantMolecularProfileId
    molecularProfiles(first: 1) {{ totalCount }}
    ... on GeneVariant {{
      alleleRegistryId clinvarIds hgvsDescriptions maneSelectTranscript
      coordinates {{ {_COORDS} }}
    }}
    ... on FactorVariant {{ ncitId }}
    ... on FusionVariant {{
      viccCompliantName
      fivePrimeCoordinates {{ {_COORDS} }}
      threePrimeCoordinates {{ {_COORDS} }}
    }}
  }}
}}
"""

_EVIDENCE_ROW = f"""
  id name status evidenceType evidenceLevel evidenceDirection significance evidenceRating
  variantOrigin {_DISEASE} {_THERAPIES} therapyInteractionType {_MP_REF}
  source {{ sourceType citationId citation }}
"""

# Per-level totals for the same filters (any level), so a breakdown needs no paging.
_EV_FILTERS = """molecularProfileId: $molecular_profile_id, diseaseName: $disease_name,
    diseaseId: $disease_id, therapyName: $therapy_name, therapyId: $therapy_id,
    evidenceType: $evidence_type, significance: $significance, status: $status"""
_LEVEL_COUNTS = "\n".join(
    f"  level_{lv}: evidenceItems({_EV_FILTERS}, evidenceLevel: {lv}) {{ totalCount }}"
    for lv in "ABCDE"
)

EVIDENCE_SEARCH = f"""
query EvidenceSearch($molecular_profile_id: Int, $disease_name: String, $disease_id: Int,
  $therapy_name: String, $therapy_id: Int, $evidence_type: EvidenceType,
  $evidence_level: EvidenceLevel, $significance: EvidenceSignificance,
  $status: EvidenceStatusFilter, $first: Int, $after: String) {{
  evidenceItems(molecularProfileId: $molecular_profile_id, diseaseName: $disease_name,
    diseaseId: $disease_id, therapyName: $therapy_name, therapyId: $therapy_id,
    evidenceType: $evidence_type, evidenceLevel: $evidence_level,
    significance: $significance, status: $status, first: $first, after: $after) {{
    totalCount
    nodes {{ {_EVIDENCE_ROW} description }}
  }}
{_LEVEL_COUNTS}
}}
"""

EVIDENCE_GET = f"""
query EvidenceGet($evidence_id: Int!) {{
  evidenceItem(id: $evidence_id) {{
    {_EVIDENCE_ROW} description link
    phenotypes {{ hpoId name }}
    source {{ sourceType citationId citation title clinicalTrials {{ nctId }} }}
    assertions {{ id name }}
  }}
}}
"""

ASSERTION_SEARCH = f"""
query AssertionSearch($molecular_profile_id: Int, $disease_name: String, $disease_id: Int,
  $therapy_name: String, $therapy_id: Int, $assertion_type: EvidenceType,
  $amp_level: AmpLevel, $status: EvidenceStatusFilter, $first: Int, $after: String) {{
  assertions(molecularProfileId: $molecular_profile_id, diseaseName: $disease_name,
    diseaseId: $disease_id, therapyName: $therapy_name, therapyId: $therapy_id,
    assertionType: $assertion_type, ampLevel: $amp_level, status: $status,
    first: $first, after: $after) {{
    totalCount
    nodes {{ {_ASSERTION_ROW} }}
  }}
}}
"""

ASSERTION_GET = f"""
query AssertionGet($assertion_id: Int!) {{
  assertion(id: $assertion_id) {{
    {_ASSERTION_ROW} description link
    phenotypes {{ hpoId name }}
    evidenceItemsCount
    evidenceItems {{ id name status evidenceLevel {_MP_REF} source {{ sourceType citationId }} }}
  }}
}}
"""

GENE_GET = """
query GeneGet($symbol: [String!], $entrez_id: [Int!], $first: Int, $after: String) {
  genes(entrezSymbols: $symbol, entrezIds: $entrez_id, first: 1) {
    nodes {
      id name fullName entrezId featureAliases description link
      variants(first: $first, after: $after) {
        totalCount
        nodes { id name singleVariantMolecularProfileId }
      }
    }
  }
}
"""

DISEASE_LOOKUP = """
query DiseaseLookup($disease: String, $doid: String) {
  diseases(name: $disease, doid: $doid, first: 1) { totalCount nodes { id name doid } }
}
"""

THERAPY_LOOKUP = """
query TherapyLookup($therapy: String, $ncit: String) {
  therapies(name: $therapy, ncitId: $ncit, first: 1) { totalCount nodes { id name ncitId } }
}
"""
