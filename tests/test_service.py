"""Data-plane behaviour over recorded CIViC GraphQL responses (network-free)."""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from civic_link.api.client import GRAPHQL_PATH
from civic_link.exceptions import AmbiguousQueryError, InvalidInputError, NotFoundError
from civic_link.service import CivicService


def _sent(router: respx.MockRouter, op: str) -> list[dict[str, object]]:
    """Variables of every GraphQL request with operation ``op``."""
    bodies = [json.loads(c.request.content) for c in router.calls if c.request.method == "POST"]
    return [b["variables"] for b in bodies if f"query {op}" in b["query"]]


async def test_name_search_keeps_complex_profiles_out_of_the_simple_answer(
    civic_service: CivicService,
) -> None:
    out = await civic_service.search_molecular_profiles("BRAF  V600E", 25, 0)
    assert out["query_type"] == "name" and out["exact_match"] == {"id": 12, "name": "BRAF V600E"}
    assert [r["id"] for r in out["simple"]] == [12, 685]
    assert out["complex"] and {r["kind"] for r in out["complex"]} == {"complex"}
    assert not {r["id"] for r in out["complex"]} & {r["id"] for r in out["simple"]}
    assert "combination" in out["complex_note"]
    # honest paging from CIViC's own totalCount (41 profiles mention BRAF V600E)
    assert out["total"] == 41 and out["returned"] == 25
    assert out["truncated"] is True and out["next_offset"] == 25


@pytest.mark.parametrize(
    ("query", "kind"),
    [
        ("CA123643", "caid"),
        ("376069", "clinvar"),
        ("VCV000376069", "clinvar"),
        ("NC_000007.14:g.140753336A>T", "hgvs"),
        ("nm_004333:c.1799T>A", "hgvs"),  # case and accession version are ignored
    ],
)
async def test_identifier_queries_resolve_to_the_simple_profile(
    civic_service: CivicService, query: str, kind: str
) -> None:
    out = await civic_service.search_molecular_profiles(query, 25, 0)
    assert out["query_type"] == kind and out["exact_match"]["id"] == 12
    if kind != "caid":
        assert out["variant_id"] == 12


async def test_clinvar_id_shared_by_two_variants_is_ambiguous(
    civic_service: CivicService,
) -> None:
    # live CIViC links ClinVar 13961 to BRAF V600E (12) and the codon-level BRAF V600 (17)
    with pytest.raises(AmbiguousQueryError) as err:
        await civic_service.search_molecular_profiles("13961", 25, 0)
    assert err.value.extra["field"] == "query"
    assert [c["variant_id"] for c in err.value.candidates] == [12, 17]  # type: ignore[index]
    assert err.value.candidates[0]["name"] == "BRAF V600E"  # type: ignore[index]
    assert err.value.extra["next_commands"][0] == {
        "tool": "get_molecular_profile",
        "arguments": {"molecular_profile_id": 12},
    }


async def test_unknown_profile_is_not_found_pointing_to_the_gene(
    civic_service: CivicService,
) -> None:
    with pytest.raises(NotFoundError) as err:
        await civic_service.search_molecular_profiles("ZZZNOPE X1Y", 25, 0)
    assert err.value.extra["field"] == "query"
    assert err.value.extra["next_commands"] == [
        {"tool": "get_gene", "arguments": {"gene": "ZZZNOPE"}}
    ]
    assert "ZZZNOPE" not in err.value.message


async def test_molecular_profile_keeps_actionability_and_oncogenicity_apart(
    civic_service: CivicService,
) -> None:
    out = await civic_service.get_molecular_profile(12)
    mp = out["molecular_profile"]
    # live list totals, not CIViC's cached counters (which said 96/119/9)
    assert mp["evidence_counts_by_status"] == {"accepted": 97, "submitted": 121, "rejected": 9}
    assert mp["kind"] == "simple" and mp["evidence_counts_by_type_accepted"]["predictive"] == 76
    assert {a["status"] for a in out["assertions"]} == {"ACCEPTED"}
    assert {a["status"] for a in out["other_assertions"]} == {"SUBMITTED"}
    assert out["other_assertions"][0].keys() == {"id", "name", "status", "assertion_type"}
    aid10 = next(a for a in out["assertions"] if a["name"] == "AID10")
    assert aid10["actionability"]["amp_tier_level"] == "TIER_I_LEVEL_A"
    assert aid10["oncogenicity"] is None and aid10["germline_pathogenicity"] is None
    assert aid10["disease"] == {"name": "Melanoma", "doid": "DOID:1909"}
    assert out["assertions_total"] == 11 and len(out["assertions"]) == 6
    assert out["assertions_truncated"] is False
    assert "evidence_note" not in out
    assert out["data_version"].startswith("CIViC 01-Nov-2026; live:")
    assert mp["description"]["kind"] == "untrusted_text"


async def test_profile_without_assertions_says_no_civic_evidence_not_not_actionable(
    civic_service: CivicService,
) -> None:
    out = await civic_service.get_molecular_profile(79)  # KRAS G12D: EIDs, no assertion
    assert out["assertions"] == []
    assert out["evidence_note"].startswith("No accepted CIViC assertion")


async def test_unknown_ids_are_not_found_naming_the_parameter(
    civic_service: CivicService,
) -> None:
    calls = [
        ("molecular_profile_id", civic_service.get_molecular_profile(999999)),
        ("variant_id", civic_service.get_variant(999999)),
        ("evidence_id", civic_service.get_evidence_item(99999999)),
        ("assertion_id", civic_service.get_assertion(999999)),
    ]
    for field, call in calls:
        with pytest.raises(NotFoundError) as err:
            await call
        assert err.value.extra["field"] == field


async def test_variant_labels_every_coordinate_with_its_assembly(
    civic_service: CivicService,
) -> None:
    v = (await civic_service.get_variant(12))["variant"]
    assert v["coordinates"]["assembly"] == "GRCh37" and v["coordinates"]["start"] == 140453136
    genomic = {g["assembly"]: g["hgvs"] for g in v["hgvs_genomic"]}
    assert genomic == {
        "GRCh37": "NC_000007.13:g.140453136A>T",
        "GRCh38": "NC_000007.14:g.140753336A>T",
    }
    assert v["caid"] == "CA123643" and "13961" in v["clinvar_ids"]
    assert v["single_variant_molecular_profile_id"] == 12


async def test_evidence_search_defaults_to_accepted_and_pages_honestly(
    civic_service: CivicService, mocked_civic: respx.MockRouter
) -> None:
    first = await civic_service.search_evidence_items(molecular_profile_id=12)
    assert _sent(mocked_civic, "EvidenceSearch")[-1]["status"] == "ACCEPTED"
    assert first["total"] == 97 and first["returned"] == 10 and first["next_offset"] == 10
    assert "statement" not in first["evidence_items"][0]
    second = await civic_service.search_evidence_items(molecular_profile_id=12, offset=10)
    assert _sent(mocked_civic, "EvidenceSearch")[-1]["after"] == "MTA="  # base64("10")
    ids = {e["id"] for e in first["evidence_items"]}
    assert not ids & {e["id"] for e in second["evidence_items"]}


async def test_standard_mode_fences_the_evidence_statement(civic_service: CivicService) -> None:
    out = await civic_service.search_evidence_items(
        molecular_profile_id=12, response_mode="standard"
    )
    statement = out["evidence_items"][0]["statement"]
    assert statement["kind"] == "untrusted_text" and statement["provenance"]["source"] == "civic"


async def test_minimal_rows_keep_curation_status(civic_service: CivicService) -> None:
    """status=ALL mixes ACCEPTED/SUBMITTED/REJECTED: even minimal rows must say which."""
    out = await civic_service.search_evidence_items(
        molecular_profile_id=12, response_mode="minimal"
    )
    assert out["evidence_items"][0]["status"] == "ACCEPTED"
    out = await civic_service.search_assertions(molecular_profile_id=12, response_mode="minimal")
    assert {"status", "assertion_type"} <= out["assertions"][0].keys()


async def test_empty_evidence_is_no_civic_evidence_found(civic_service: CivicService) -> None:
    out = await civic_service.search_evidence_items(
        molecular_profile_id=79, evidence_type="PREDISPOSING"
    )
    assert out["total"] == 0 and out["evidence_items"] == []
    assert out["evidence_note"].startswith("No CIViC evidence found")


async def test_unknown_profile_behind_an_empty_search_is_not_found(
    civic_service: CivicService,
) -> None:
    with pytest.raises(NotFoundError) as err:
        await civic_service.search_assertions(molecular_profile_id=999999)
    assert err.value.extra["field"] == "molecular_profile_id"


async def test_disease_and_therapy_filters_never_match_silently(
    civic_service: CivicService, mocked_civic: respx.MockRouter
) -> None:
    for kwargs, field in (({"disease": "zzz"}, "disease"), ({"therapy": "zzz"}, "therapy")):
        with pytest.raises(NotFoundError) as err:
            await civic_service.search_evidence_items(**kwargs)
        assert err.value.extra["field"] == field
    await civic_service.search_evidence_items(disease="DOID:1909", therapy="Vemurafenib")
    sent = _sent(mocked_civic, "EvidenceSearch")[-1]
    assert sent["disease_id"] == 7 and sent["therapy_name"] == "Vemurafenib"


async def test_oncogenic_assertions_carry_only_the_oncogenicity_axis(
    civic_service: CivicService,
) -> None:
    out = await civic_service.search_assertions(assertion_type="ONCOGENIC", limit=3)
    for row in out["assertions"]:
        assert row["actionability"] is None and row["oncogenicity"]["classification"]
    assert out["assertions"][2]["oncogenicity"]["clingen_cgc_vicc_codes"] == ["OS2", "OS3", "OP4"]


async def test_get_assertion_aid10_is_tier_i_level_a(civic_service: CivicService) -> None:
    a = (await civic_service.get_assertion(10))["assertion"]
    assert a["actionability"]["amp_tier_level"] == "TIER_I_LEVEL_A"
    assert a["actionability"]["fda_companion_test"] is True
    assert a["summary"]["kind"] == a["description"]["kind"] == "untrusted_text"
    assert [e["id"] for e in a["evidence_items"]] == [6966, 6044, 1421]
    # enough per item to see that two of AID10's EIDs sit on BRAF V600 (MP17), not V600E
    assert a["evidence_items"][0] == {
        "id": 6966,
        "name": "EID6966",
        "status": "ACCEPTED",
        "evidence_level": "B",
        "molecular_profile": {"id": 17, "name": "BRAF V600"},
        "pmid": "25037139",
    }
    assert (
        "not a clinical actionability report"
        in (await civic_service.get_assertion(10))["disclaimer"]
    )


async def test_gene_by_symbol_or_ncbi_id_and_foreign_ids_get_a_converter(
    civic_service: CivicService,
) -> None:
    by_symbol = await civic_service.get_gene("kras", 5, 0)
    by_id = await civic_service.get_gene("NCBIGene:3845", 5, 0)
    assert by_symbol["variants"] == by_id["variants"] and by_symbol["gene"]["entrez_id"] == 3845
    assert by_symbol["total"] == 63 and by_symbol["truncated"] is True
    for foreign in ("ENSG00000133703", "HGNC:6407"):
        with pytest.raises(InvalidInputError) as err:
            await civic_service.get_gene(foreign, 5, 0)
        extra = err.value.extra
        assert extra["field"] == "gene" and extra["allowed_values"]
        assert extra["next_commands"] == [
            {"tool": "hgnc_resolve_symbol", "arguments": {"query": foreign}}
        ]
    with pytest.raises(NotFoundError):
        await civic_service.get_gene("NOPE1", 5, 0)


async def test_limit_never_exceeds_the_silent_upstream_page_cap(
    civic_service: CivicService,
) -> None:
    with pytest.raises(InvalidInputError) as err:
        await civic_service.search_molecular_profiles("BRAF", 101, 0)
    assert err.value.extra["field"] == "limit"


async def test_graphql_error_on_a_filter_names_the_tool_parameter(
    civic_service: CivicService, mocked_civic: respx.MockRouter
) -> None:
    body = {"errors": [{"message": "Variable $disease_id of type Int was provided invalid value"}]}
    mocked_civic.post(GRAPHQL_PATH).mock(
        side_effect=[
            httpx.Response(
                200, json={"data": {"diseases": {"totalCount": 1, "nodes": [{"id": 7}]}}}
            ),
            httpx.Response(200, json=body),
        ]
    )
    with pytest.raises(InvalidInputError) as err:
        await civic_service.search_assertions(disease="DOID:1909")
    assert err.value.extra["field"] == "disease"
