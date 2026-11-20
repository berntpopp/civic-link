"""CIViC tools: molecular profiles, variants, evidence items, assertions and genes."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Annotated, Any, Literal

from pydantic import Field, StrictInt

from civic_link.mcp.annotations import READ_ONLY_OPEN_WORLD
from civic_link.mcp.envelope import McpErrorContext, ToolReturn, run_mcp_tool
from civic_link.mcp.next_commands import cmd
from civic_link.mcp.service_adapters import get_civic_service
from civic_link.service import (
    DEFAULT_LIMIT,
    GENE_DEFAULT_LIMIT,
    MAX_LIMIT,
    MP_DEFAULT_LIMIT,
    UPSTREAM_PAGE_CAP,
)

if TYPE_CHECKING:
    from fastmcp import FastMCP

_INT_MAX = 2_147_483_647
CivicInt = Annotated[StrictInt, Field(ge=1, le=_INT_MAX)]
MpId = Annotated[CivicInt, Field(description="CIViC molecular profile ID.", examples=[12])]
Offset = Annotated[
    StrictInt, Field(ge=0, description="Rows to skip; use the previous `next_offset`.")
]
Limit = Annotated[
    StrictInt,
    Field(ge=1, le=MAX_LIMIT, description=f"Max rows (default {DEFAULT_LIMIT}, max {MAX_LIMIT})."),
]
Status = Annotated[
    Literal["ACCEPTED", "SUBMITTED", "NON_REJECTED", "ALL"],
    Field(description="Curation status; ACCEPTED (default) excludes unreviewed submissions."),
]
_Name = Annotated[str, Field(min_length=2, max_length=120)]
Disease = Annotated[
    _Name | None,
    Field(
        description="DOID (DOID:1909, exact) or disease name (Melanoma, matches CIViC "
        "names containing it); unknown is not_found."
    ),
]
Therapy = Annotated[
    _Name | None,
    Field(
        description="NCIt code (C64768, exact) or therapy name (Vemurafenib, matches CIViC "
        "names containing it); unknown is not_found."
    ),
]
ResponseMode = Annotated[
    Literal["minimal", "compact", "standard", "full"],
    Field(
        description="minimal: IDs + classification | compact (default): + disease, "
        "therapies, profile, source | standard/full: + fenced curator text."
    ),
]


AssertionId = Annotated[
    CivicInt | Annotated[str, Field(pattern=r"^(?i:AID)?[1-9]\d{0,8}$")],
    Field(description="CIViC assertion ID as a number or 'AID10'.", examples=[10]),
]
EvidenceId = Annotated[
    CivicInt | Annotated[str, Field(pattern=r"^(?i:EID)?[1-9]\d{0,8}$")],
    Field(description="CIViC evidence item ID as a number or 'EID95'.", examples=[95]),
]


def _num(value: int | str) -> int:
    return value if isinstance(value, int) else int(value[3:] if value[:1].isalpha() else value)


def _paged(payload: dict[str, Any], tool: str, args: dict[str, Any]) -> list[dict[str, Any]]:
    """Next page first when truncated."""
    if payload.get("next_offset") is not None:
        return [cmd(tool, **{**args, "offset": payload["next_offset"]})]
    return []


def _set(**values: Any) -> dict[str, Any]:
    return {k: v for k, v in values.items() if v is not None}


async def _run(
    tool: str,
    args: dict[str, Any],
    fetch: Callable[[], Awaitable[dict[str, Any]]],
    steps: Callable[[dict[str, Any]], list[dict[str, Any]]],
) -> ToolReturn:
    async def call() -> dict[str, Any]:
        payload = await fetch()
        payload["_meta"] = {"next_commands": steps(payload)}
        return payload

    return await run_mcp_tool(tool, call, context=McpErrorContext(tool, arguments=args))


def register_civic_tools(mcp: FastMCP) -> None:
    """Register the CIViC tools on a FastMCP instance."""

    @mcp.tool(
        name="search_molecular_profiles",
        annotations=READ_ONLY_OPEN_WORLD,
        output_schema=None,
        tags={"profiles"},
        description=(
            "Find CIViC molecular profiles (what evidence attaches to) for a gene + variant "
            "name (BRAF V600E), a ClinGen CAID (CA123643), a ClinVar variation ID (376069) or "
            "an HGVS string, and return exact_match (the single-variant profile) plus "
            "`simple` and `complex` lists kept apart: a complex profile (V600E AND MSI Low) "
            "only applies to that combination. Each row: id, name, kind, evidence counts. "
            "Start here. Signature: search_molecular_profiles(query, limit=, offset=)."
        ),
    )
    async def search_molecular_profiles(
        query: Annotated[
            str,
            Field(
                min_length=1,
                max_length=200,
                description="Gene + variant, CAID, ClinVar variation ID or HGVS.",
                examples=["BRAF V600E"],
            ),
        ],
        limit: Annotated[
            StrictInt,
            Field(
                ge=1,
                le=UPSTREAM_PAGE_CAP,
                description=f"Max profiles (default {MP_DEFAULT_LIMIT}, max {UPSTREAM_PAGE_CAP}).",
            ),
        ] = MP_DEFAULT_LIMIT,
        offset: Offset = 0,
    ) -> ToolReturn:
        args = {"query": query, "limit": limit, "offset": offset}

        def steps(p: dict[str, Any]) -> list[dict[str, Any]]:
            hit = p.get("exact_match")
            first = [cmd("get_molecular_profile", molecular_profile_id=hit["id"])] if hit else []
            return first + _paged(p, "search_molecular_profiles", args)

        return await _run(
            "search_molecular_profiles",
            args,
            lambda: get_civic_service().search_molecular_profiles(query, limit, offset),
            steps,
        )

    @mcp.tool(
        name="get_molecular_profile",
        annotations=READ_ONLY_OPEN_WORLD,
        output_schema=None,
        tags={"profiles"},
        description=(
            "Return one molecular profile: its variants, kind (simple/complex), evidence "
            "counts by status and type, and its assertions, each with actionability (AMP "
            "tier/level), oncogenicity or germline_pathogenicity as separate fields and a "
            "DOID disease. evidence_note flags a profile without an accepted assertion: no "
            "CIViC evidence is not 'not actionable'. "
            "Signature: get_molecular_profile(molecular_profile_id)."
        ),
    )
    async def get_molecular_profile(molecular_profile_id: MpId) -> ToolReturn:
        mp = molecular_profile_id
        return await _run(
            "get_molecular_profile",
            {"molecular_profile_id": mp},
            lambda: get_civic_service().get_molecular_profile(mp),
            lambda p: [
                cmd("search_evidence_items", molecular_profile_id=mp),
                cmd("search_assertions", molecular_profile_id=mp),
            ],
        )

    @mcp.tool(
        name="get_variant",
        annotations=READ_ONLY_OPEN_WORLD,
        output_schema=None,
        tags={"variants"},
        description=(
            "Return one CIViC variant: coordinates with their assembly (CIViC's primary "
            "build is GRCh37), genomic HGVS labelled GRCh37/GRCh38, transcript HGVS, MANE "
            "Select HGVS, ClinGen CAID, ClinVar IDs, variant types (SO) and its "
            "single-variant molecular profile. Signature: get_variant(variant_id)."
        ),
    )
    async def get_variant(
        variant_id: Annotated[CivicInt, Field(description="CIViC variant ID.", examples=[12])],
    ) -> ToolReturn:
        def steps(p: dict[str, Any]) -> list[dict[str, Any]]:
            mp = p["variant"].get("single_variant_molecular_profile_id")
            return [cmd("get_molecular_profile", molecular_profile_id=mp)] if mp else []

        return await _run(
            "get_variant",
            {"variant_id": variant_id},
            lambda: get_civic_service().get_variant(variant_id),
            steps,
        )

    @mcp.tool(
        name="search_evidence_items",
        annotations=READ_ONLY_OPEN_WORLD,
        output_schema=None,
        tags={"evidence"},
        description=(
            "List CIViC evidence items (one publication-backed clinical claim each) matching "
            "ALL given filters: molecular_profile_id, disease, therapy, evidence_type, "
            "evidence_level (A validated .. E inferential), significance, status (ACCEPTED "
            "by default). Rows: type, level, direction, significance, rating, DOID disease, "
            "therapies (NCIt), source PMID. `total` is exact; zero rows says no CIViC "
            "evidence found. Signature: search_evidence_items(molecular_profile_id=, "
            "disease=, therapy=, evidence_type=, evidence_level=, significance=, status=, "
            "response_mode=, limit=, offset=)."
        ),
    )
    async def search_evidence_items(
        molecular_profile_id: Annotated[
            CivicInt | None, Field(description="Only this molecular profile's evidence.")
        ] = None,
        disease: Disease = None,
        therapy: Therapy = None,
        evidence_type: Annotated[
            Literal[
                "PREDICTIVE",
                "DIAGNOSTIC",
                "PROGNOSTIC",
                "PREDISPOSING",
                "ONCOGENIC",
                "FUNCTIONAL",
            ]
            | None,
            Field(description="Evidence type."),
        ] = None,
        evidence_level: Annotated[
            Literal["A", "B", "C", "D", "E"] | None, Field(description="CIViC evidence level.")
        ] = None,
        significance: Annotated[
            Literal[
                "SENSITIVITYRESPONSE",
                "RESISTANCE",
                "REDUCED_SENSITIVITY",
                "ADVERSE_RESPONSE",
                "BETTER_OUTCOME",
                "POOR_OUTCOME",
                "POSITIVE",
                "NEGATIVE",
                "ONCOGENICITY",
                "LIKELY_ONCOGENIC",
                "PATHOGENIC",
                "LIKELY_PATHOGENIC",
                "UNCERTAIN_SIGNIFICANCE",
                "BENIGN",
                "LIKELY_BENIGN",
                "PREDISPOSITION",
                "PROTECTIVENESS",
                "GAIN_OF_FUNCTION",
                "LOSS_OF_FUNCTION",
                "UNALTERED_FUNCTION",
                "NEOMORPHIC",
                "DOMINANT_NEGATIVE",
                "UNKNOWN",
                "NA",
            ]
            | None,
            Field(description="Clinical significance as CIViC records it."),
        ] = None,
        status: Status = "ACCEPTED",
        response_mode: ResponseMode = "compact",
        limit: Limit = DEFAULT_LIMIT,
        offset: Offset = 0,
    ) -> ToolReturn:
        args = _set(
            molecular_profile_id=molecular_profile_id,
            disease=disease,
            therapy=therapy,
            evidence_type=evidence_type,
            evidence_level=evidence_level,
            significance=significance,
            status=None if status == "ACCEPTED" else status,
            response_mode=None if response_mode == "compact" else response_mode,
            limit=limit,
            offset=offset,
        )

        def steps(p: dict[str, Any]) -> list[dict[str, Any]]:
            first = [cmd("get_evidence_item", evidence_id=e["id"]) for e in p["evidence_items"][:1]]
            return _paged(p, "search_evidence_items", args) + first

        return await _run(
            "search_evidence_items",
            args,
            lambda: get_civic_service().search_evidence_items(
                molecular_profile_id=molecular_profile_id,
                disease=disease,
                therapy=therapy,
                evidence_type=evidence_type,
                evidence_level=evidence_level,
                significance=significance,
                status=status,
                response_mode=response_mode,
                limit=limit,
                offset=offset,
            ),
            steps,
        )

    @mcp.tool(
        name="get_evidence_item",
        annotations=READ_ONLY_OPEN_WORLD,
        output_schema=None,
        tags={"evidence"},
        description=(
            "Return one evidence item: type, level, direction, significance, rating, DOID "
            "disease, therapies, the curator's statement (fenced untrusted_text), source "
            "PMID/citation and NCT IDs, phenotypes (HPO) and the assertions it supports. "
            "Signature: get_evidence_item(evidence_id)."
        ),
    )
    async def get_evidence_item(evidence_id: EvidenceId) -> ToolReturn:
        eid = _num(evidence_id)
        return await _run(
            "get_evidence_item",
            {"evidence_id": evidence_id},
            lambda: get_civic_service().get_evidence_item(eid),
            lambda p: [
                cmd(
                    "get_molecular_profile",
                    molecular_profile_id=p["evidence_item"]["molecular_profile"]["id"],
                )
            ],
        )

    @mcp.tool(
        name="search_assertions",
        annotations=READ_ONLY_OPEN_WORLD,
        output_schema=None,
        tags={"assertions"},
        description=(
            "List CIViC assertions (curated summary calls built on evidence items) matching "
            "ALL given filters: molecular_profile_id, disease, therapy, assertion_type, "
            "amp_level, status (ACCEPTED by default). Each row keeps actionability (AMP/ASCO/"
            "CAP tier and level, FDA companion test, NCCN), oncogenicity (ClinGen/CGC/VICC) "
            "and germline_pathogenicity (ACMG) apart. Zero rows says no CIViC evidence "
            "found. Signature: search_assertions(molecular_profile_id=, disease=, therapy=, "
            "assertion_type=, amp_level=, status=, response_mode=, limit=, offset=)."
        ),
    )
    async def search_assertions(
        molecular_profile_id: Annotated[
            CivicInt | None, Field(description="Only this molecular profile's assertions.")
        ] = None,
        disease: Disease = None,
        therapy: Therapy = None,
        assertion_type: Annotated[
            Literal["PREDICTIVE", "DIAGNOSTIC", "PROGNOSTIC", "PREDISPOSING", "ONCOGENIC"] | None,
            Field(description="Assertion type."),
        ] = None,
        amp_level: Annotated[
            Literal[
                "TIER_I_LEVEL_A",
                "TIER_I_LEVEL_B",
                "TIER_II_LEVEL_C",
                "TIER_II_LEVEL_D",
                "TIER_III",
                "TIER_IV",
            ]
            | None,
            Field(description="AMP/ASCO/CAP 2017 tier and level."),
        ] = None,
        status: Status = "ACCEPTED",
        response_mode: ResponseMode = "compact",
        limit: Limit = DEFAULT_LIMIT,
        offset: Offset = 0,
    ) -> ToolReturn:
        args = _set(
            molecular_profile_id=molecular_profile_id,
            disease=disease,
            therapy=therapy,
            assertion_type=assertion_type,
            amp_level=amp_level,
            status=None if status == "ACCEPTED" else status,
            response_mode=None if response_mode == "compact" else response_mode,
            limit=limit,
            offset=offset,
        )

        def steps(p: dict[str, Any]) -> list[dict[str, Any]]:
            first = [cmd("get_assertion", assertion_id=a["id"]) for a in p["assertions"][:1]]
            return _paged(p, "search_assertions", args) + first

        return await _run(
            "search_assertions",
            args,
            lambda: get_civic_service().search_assertions(
                molecular_profile_id=molecular_profile_id,
                disease=disease,
                therapy=therapy,
                assertion_type=assertion_type,
                amp_level=amp_level,
                status=status,
                response_mode=response_mode,
                limit=limit,
                offset=offset,
            ),
            steps,
        )

    @mcp.tool(
        name="get_assertion",
        annotations=READ_ONLY_OPEN_WORLD,
        output_schema=None,
        tags={"assertions"},
        description=(
            "Return one assertion: type, direction, actionability (AMP tier/level, FDA "
            "companion test, regulatory approval, NCCN guideline) or oncogenicity / "
            "germline_pathogenicity with their codes, DOID disease, therapies, the fenced "
            "summary and description, and the evidence items behind it. "
            "Signature: get_assertion(assertion_id)."
        ),
    )
    async def get_assertion(assertion_id: AssertionId) -> ToolReturn:
        aid = _num(assertion_id)
        return await _run(
            "get_assertion",
            {"assertion_id": assertion_id},
            lambda: get_civic_service().get_assertion(aid),
            lambda p: [
                cmd("get_evidence_item", evidence_id=e["id"])
                for e in p["assertion"]["evidence_items"][:1]
            ],
        )

    @mcp.tool(
        name="get_gene",
        annotations=READ_ONLY_OPEN_WORLD,
        output_schema=None,
        tags={"genes"},
        description=(
            "Return a CIViC gene (symbol, full name, NCBI Gene ID, aliases, fenced curator "
            "summary) and the variants CIViC curates for it, each with its single-variant "
            "molecular profile ID; `total` is exact, page with offset. Ensembl or HGNC IDs "
            "are rejected with a converter step. "
            "Signature: get_gene(gene, limit=, offset=)."
        ),
    )
    async def get_gene(
        gene: Annotated[
            str,
            Field(
                min_length=1,
                max_length=40,
                description="HGNC symbol (BRAF) or NCBI Gene ID (NCBIGene:673).",
                examples=["BRAF"],
            ),
        ],
        limit: Annotated[
            StrictInt,
            Field(
                ge=1,
                le=UPSTREAM_PAGE_CAP,
                description=f"Max variants (default {GENE_DEFAULT_LIMIT}, max {UPSTREAM_PAGE_CAP}).",
            ),
        ] = GENE_DEFAULT_LIMIT,
        offset: Offset = 0,
    ) -> ToolReturn:
        args = {"gene": gene, "limit": limit, "offset": offset}
        return await _run(
            "get_gene",
            args,
            lambda: get_civic_service().get_gene(gene, limit, offset),
            lambda p: _paged(p, "get_gene", args),
        )
