"""Pure shapers: turn CIViC GraphQL nodes into compact, honest payload rows.

Identifiers and controlled vocabularies pass through verbatim. Curator prose (evidence
statements, assertion summaries and descriptions, gene and profile descriptions) is
fenced as ``untrusted_text``. Diseases are DOID (``DOID:<n>``). Every coordinate carries
its ``assembly``. Oncogenicity, actionability and germline pathogenicity are separate
fields and are never folded into one "significance".
"""

from __future__ import annotations

import base64
import csv
import io
import re
from typing import Any

from civic_link.mcp.untrusted_content import fence_untrusted_text

SITE = "https://civicdb.org"

#: Absence of CIViC evidence is not a negative finding (plan §5 risk 4).
NO_EVIDENCE = (
    "No CIViC evidence found for this query. CIViC is a community-curated knowledgebase: "
    "absence of CIViC evidence does not mean the variant is not actionable or not oncogenic."
)
NO_ASSERTION = (
    "No accepted CIViC assertion for this profile; see its evidence items. Absence of a CIViC "
    "assertion does not mean the variant is not actionable or not oncogenic."
)
NOT_A_REPORT = "Research use only; this is not a clinical actionability report."
COMPLEX_NOTE = (
    "Complex profiles combine several variants (AND/OR/NOT); their evidence applies only to "
    "that combination, never to a single variant on its own."
)

#: RefSeq chromosome accession version on GRCh38; on GRCh37 every one is exactly one lower.
_GRCH38_NC_VERSION = {
    1: 11, 2: 12, 3: 12, 4: 12, 5: 10, 6: 12, 7: 14, 8: 11, 9: 12, 10: 11, 11: 10, 12: 12,
    13: 11, 14: 9, 15: 10, 16: 10, 17: 11, 18: 10, 19: 10, 20: 11, 21: 9, 22: 11, 23: 11,
    24: 10,
}  # fmt: skip
_NC = re.compile(r"^NC_0000(\d\d)\.(\d+):g\.")
_ASSEMBLY = {"GRCH37": "GRCh37", "GRCH38": "GRCh38", "NCBI36": "NCBI36"}


#: Query / argument forms.
CAID = re.compile(r"^CA\d{1,12}$", re.IGNORECASE)
CLINVAR = re.compile(r"^(?:VCV)?0*(\d{1,9})(?:\.\d+)?$", re.IGNORECASE)
HGVS = re.compile(r"^[A-Z]{2}_\d+(?:\.\d+)?:[cgnmpr]\.\S+$", re.IGNORECASE)
DOID_RE = re.compile(r"^DOID:(\d{1,9})$", re.IGNORECASE)
NCIT_RE = re.compile(r"^(?:NCIT:)?(C\d{1,9})$", re.IGNORECASE)
NCBI_GENE = re.compile(r"^(?:NCBIGene:)?(\d{1,9})$", re.IGNORECASE)
FOREIGN_GENE = re.compile(r"^(ENSG\d+(\.\d+)?|HGNC:\d+)$", re.IGNORECASE)
SYMBOL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.\-]{0,29}$")
WS = re.compile(r"\s+")


def hgvs_key(value: str) -> str:
    """HGVS match key: case-insensitive, accession version ignored."""
    acc, _, change = value.strip().partition(":")
    return f"{acc.split('.')[0]}:{change}".upper()


VariantIndex = dict[str, dict[str, list[dict[str, Any]]]]


def variant_index(text: str) -> VariantIndex:
    """ClinVar ID and HGVS -> CIViC variants, from the nightly VariantSummaries TSV."""
    index: VariantIndex = {"clinvar": {}, "hgvs": {}}
    for row in csv.DictReader(io.StringIO(text), delimiter="\t"):
        if not (row.get("variant_id") or "").isdigit():
            continue
        mp = row.get("single_variant_molecular_profile_id") or ""
        hit = {
            "variant_id": int(row["variant_id"]),
            "name": f"{row.get('feature_name') or ''} {row.get('variant') or ''}".strip(),
            "single_variant_molecular_profile_id": int(mp) if mp.isdigit() else None,
        }
        keys = [("clinvar", c.strip()) for c in (row.get("clinvar_ids") or "").split(",")]
        keys += [("hgvs", hgvs_key(h)) for h in (row.get("hgvs_descriptions") or "").split(",")]
        for kind, key in keys:
            if key and (kind == "hgvs" or key.isdigit()):
                index[kind].setdefault(key, []).append(hit)
    return index


def fence(raw: Any, record_id: str) -> dict[str, Any] | None:
    """Fence one upstream prose value (``None``/empty stays ``None``)."""
    if not isinstance(raw, str) or not raw.strip():
        return None
    return fence_untrusted_text(raw, source="civic", record_id=record_id).model_dump(mode="json")


def cursor(offset: int) -> str | None:
    """CIViC's connection cursor for "after the first ``offset`` nodes"."""
    return base64.b64encode(str(offset).encode()).decode() if offset else None


def page_block(*, total: int, returned: int, limit: int, offset: int) -> dict[str, Any]:
    """Uniform pagination block; ``total`` is CIViC's own ``totalCount``."""
    truncated = offset + returned < total
    return {
        "total": total,
        "returned": returned,
        "limit": limit,
        "offset": offset,
        "truncated": truncated,
        "next_offset": offset + returned if truncated else None,
    }


def doid(disease: dict[str, Any] | None) -> dict[str, Any] | None:
    """A CIViC disease as ``{name, doid: "DOID:<n>"}`` (DOID is CIViC's disease ontology)."""
    if not disease:
        return None
    raw = disease.get("doid")
    return {"name": disease.get("name"), "doid": f"DOID:{raw}" if raw else None}


def therapies(raw: Any) -> list[dict[str, Any]]:
    """Therapies with their NCIt codes."""
    return [{"name": t.get("name"), "ncit": t.get("ncitId")} for t in raw or []]


def classification(raw: dict[str, Any]) -> dict[str, Any]:
    """The assertion's verdict on exactly one axis, chosen by its type.

    ONCOGENIC -> ``oncogenicity`` (ClinGen/CGC/VICC, Horak 2022); PREDISPOSING ->
    ``germline_pathogenicity`` (ACMG/AMP); otherwise -> ``actionability`` (AMP/ASCO/CAP 2017
    tier and level). The other axes are null, never inferred.
    """
    kind = raw.get("assertionType")
    out: dict[str, Any] = {
        "actionability": None,
        "oncogenicity": None,
        "germline_pathogenicity": None,
    }
    if kind == "ONCOGENIC":
        out["oncogenicity"] = {
            "classification": raw.get("significance"),
            "clingen_cgc_vicc_codes": [c.get("code") for c in raw.get("clingenCodes") or []],
        }
    elif kind == "PREDISPOSING":
        out["germline_pathogenicity"] = {
            "classification": raw.get("significance"),
            "acmg_codes": [c.get("code") for c in raw.get("acmgCodes") or []],
        }
    else:
        out["actionability"] = {
            "amp_tier_level": raw.get("ampLevel"),
            "significance": raw.get("significance"),
            "fda_companion_test": raw.get("fdaCompanionTest"),
            "regulatory_approval": raw.get("regulatoryApproval"),
            "nccn_guideline": (raw.get("nccnGuideline") or {}).get("name"),
            "nccn_guideline_version": raw.get("nccnGuidelineVersion"),
        }
    return out


def mp_row(raw: dict[str, Any]) -> dict[str, Any]:
    """A molecular-profile row for search results."""
    counts = raw.get("evidenceCountsByStatus") or {}
    row = {
        "id": raw.get("id"),
        "name": raw.get("name"),
        "kind": "complex" if raw.get("isComplex") else "simple",
        "accepted_evidence_count": counts.get("acceptedCount"),
        "submitted_evidence_count": counts.get("submittedCount"),
    }
    if raw.get("deprecated"):
        row["deprecated"] = True
    return row


def mp_detail(raw: dict[str, Any]) -> dict[str, Any]:
    """One molecular profile: variants, evidence counts, fenced description."""
    status = raw.get("evidenceCountsByStatus") or {}
    return {
        **mp_row(raw),
        "aliases": raw.get("molecularProfileAliases") or [],
        "score": raw.get("molecularProfileScore"),
        "variants": [
            {
                "id": v.get("id"),
                "name": v.get("name"),
                "variant_kind": v.get("__typename"),
                "feature": v.get("feature"),
            }
            for v in raw.get("variants") or []
        ],
        "evidence_counts_by_status": {
            "accepted": status.get("acceptedCount"),
            "submitted": status.get("submittedCount"),
            "rejected": status.get("rejectedCount"),
        },
        "evidence_counts_by_type_all_statuses": {
            k.removesuffix("Count") + "_count": v
            for k, v in (raw.get("evidenceCountsByType") or {}).items()
        },
        "description": fence(raw.get("description"), f"MP{raw.get('id')}"),
        "url": SITE + str(raw.get("link") or ""),
    }


def assertion_row(raw: dict[str, Any], mode: str = "compact") -> dict[str, Any]:
    """An assertion at one response_mode; the classification axes stay separate."""
    if mode == "minimal":
        return {
            "id": raw.get("id"),
            "name": raw.get("name"),
            "status": raw.get("status"),
            "assertion_type": raw.get("assertionType"),
            **classification(raw),
        }
    out = {
        "id": raw.get("id"),
        "name": raw.get("name"),
        "status": raw.get("status"),
        "molecular_profile": raw.get("molecularProfile"),
        "assertion_type": raw.get("assertionType"),
        "assertion_direction": raw.get("assertionDirection"),
        **classification(raw),
        "disease": doid(raw.get("disease")),
        "therapies": therapies(raw.get("therapies")),
        "therapy_interaction_type": raw.get("therapyInteractionType"),
        "variant_origin": raw.get("variantOrigin"),
    }
    if mode in ("standard", "full"):
        out["summary"] = fence(raw.get("summary"), str(raw.get("name")))
    return out


def evidence_row(raw: dict[str, Any], mode: str = "compact") -> dict[str, Any]:
    """An evidence item at one response_mode (standard/full add the fenced statement)."""
    disease = doid(raw.get("disease"))
    if mode == "minimal":
        return {
            "id": raw.get("id"),
            "name": raw.get("name"),
            "status": raw.get("status"),
            "evidence_type": raw.get("evidenceType"),
            "evidence_level": raw.get("evidenceLevel"),
            "significance": raw.get("significance"),
            "disease_doid": disease["doid"] if disease else None,
        }
    source = raw.get("source") or {}
    out = {
        "id": raw.get("id"),
        "name": raw.get("name"),
        "status": raw.get("status"),
        "molecular_profile": raw.get("molecularProfile"),
        "evidence_type": raw.get("evidenceType"),
        "evidence_level": raw.get("evidenceLevel"),
        "evidence_direction": raw.get("evidenceDirection"),
        "significance": raw.get("significance"),
        "evidence_rating": raw.get("evidenceRating"),
        "variant_origin": raw.get("variantOrigin"),
        "disease": disease,
        "therapies": therapies(raw.get("therapies")),
        "therapy_interaction_type": raw.get("therapyInteractionType"),
        "source": {
            "type": source.get("sourceType"),
            "citation_id": source.get("citationId"),
            "citation": source.get("citation"),
        },
    }
    if mode in ("standard", "full"):
        out["statement"] = fence(raw.get("description"), str(raw.get("name")))
    return out


def coordinates(raw: dict[str, Any] | None) -> dict[str, Any] | None:
    """A CIViC coordinate block with its genome assembly named."""
    if not raw or raw.get("start") is None:
        return None
    return {
        "assembly": _ASSEMBLY.get(str(raw.get("referenceBuild")), raw.get("referenceBuild")),
        "chromosome": raw.get("chromosome"),
        "start": raw.get("start"),
        "stop": raw.get("stop"),
        "reference_bases": raw.get("referenceBases"),
        "variant_bases": raw.get("variantBases"),
        "representative_transcript": raw.get("representativeTranscript"),
        "ensembl_version": raw.get("ensemblVersion"),
    }


def genomic_assembly(hgvs: str) -> str | None:
    """GRCh37/GRCh38 for a chromosome-level ``NC_0000NN.v:g.`` HGVS, else None."""
    match = _NC.match(hgvs)
    if not match:
        return None
    grch38 = _GRCH38_NC_VERSION.get(int(match.group(1)))
    version = int(match.group(2))
    if grch38 == version:
        return "GRCh38"
    return "GRCh37" if grch38 is not None and version == grch38 - 1 else None


def variant_detail(raw: dict[str, Any]) -> dict[str, Any]:
    """One CIViC variant: identity, assembly-labelled coordinates and HGVS, cross-refs."""
    hgvs = [h for h in raw.get("hgvsDescriptions") or [] if isinstance(h, str)]
    genomic = [{"assembly": genomic_assembly(h), "hgvs": h} for h in hgvs if _NC.match(h)]
    out: dict[str, Any] = {
        "id": raw.get("id"),
        "name": raw.get("name"),
        "variant_kind": raw.get("__typename"),
        "feature": raw.get("feature"),
        "aliases": raw.get("variantAliases") or [],
        "variant_types": [
            {"name": t.get("name"), "soid": t.get("soid")} for t in raw.get("variantTypes") or []
        ],
        "coordinates": coordinates(raw.get("coordinates")),
        "hgvs_genomic": genomic,
        "hgvs_other": [h for h in hgvs if not _NC.match(h)],
        "mane_select_hgvs": raw.get("maneSelectTranscript"),
        "caid": raw.get("alleleRegistryId"),
        "clinvar_ids": raw.get("clinvarIds") or [],
        "single_variant_molecular_profile_id": raw.get("singleVariantMolecularProfileId"),
        "molecular_profile_count": (raw.get("molecularProfiles") or {}).get("totalCount"),
        "url": raw.get("link") and SITE + str(raw["link"]),
    }
    if raw.get("__typename") == "FusionVariant":
        out["vicc_compliant_name"] = raw.get("viccCompliantName")
        out["five_prime_coordinates"] = coordinates(raw.get("fivePrimeCoordinates"))
        out["three_prime_coordinates"] = coordinates(raw.get("threePrimeCoordinates"))
    if raw.get("__typename") == "FactorVariant":
        out["ncit"] = raw.get("ncitId")
    return out
