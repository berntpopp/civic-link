"""End-to-end MCP tool tests through an in-memory FastMCP client."""

from __future__ import annotations

from typing import Any

from fastmcp import Client

from civic_link.mcp.capabilities import TOOLS


async def _raw(mcp: Any, name: str, args: dict[str, Any]) -> Any:
    async with Client(mcp) as client:
        return await client.call_tool(name, args, raise_on_error=False)


async def test_registered_tools_match_capabilities_and_are_documented(facade: Any) -> None:
    async with Client(facade) as client:
        tools = await client.list_tools()
    assert [t.name for t in tools] == TOOLS
    for tool in tools:
        props = tool.input_schema.get("properties", {})
        for name, prop in props.items():
            assert prop.get("description"), f"{tool.name}.{name} lacks a description"
        for name in tool.input_schema.get("required", []):
            assert props[name].get("examples"), f"{tool.name}.{name} lacks examples"
        assert tool.description and "Signature:" in tool.description
        assert tool.annotations is not None and tool.annotations.read_only_hint is True
        assert tool.output_schema is None


async def test_braf_v600e_acceptance_path(facade: Any, call_tool: Any) -> None:
    """BRAF V600E -> MP 12 -> accepted EIDs -> assertions incl. AID10 (Tier I Level A)."""
    found = await call_tool(facade, "search_molecular_profiles", {"query": "BRAF V600E"})
    assert found["success"] is True and found["exact_match"]["id"] == 12
    meta = found["_meta"]
    assert meta["source"] == "civic" and meta["unsafe_for_clinical_use"] is True
    assert meta["next_commands"][0] == {
        "tool": "get_molecular_profile",
        "arguments": {"molecular_profile_id": 12},
    }
    evidence = await call_tool(facade, "search_evidence_items", {"molecular_profile_id": 12})
    assert evidence["total"] == 97 and {e["status"] for e in evidence["evidence_items"]} == {
        "ACCEPTED"
    }
    assertions = await call_tool(facade, "search_assertions", {"molecular_profile_id": 12})
    aid10 = next(a for a in assertions["assertions"] if a["id"] == 10)
    assert aid10["actionability"]["amp_tier_level"] == "TIER_I_LEVEL_A"


async def test_unknown_profile_is_is_error_not_found(facade: Any) -> None:
    res = await _raw(facade, "get_molecular_profile", {"molecular_profile_id": 999999})
    assert res.is_error is True
    body = res.structured_content
    assert body["error_code"] == "not_found" and body["field"] == "molecular_profile_id"


async def test_assertion_and_evidence_ids_accept_civic_prefixes(
    facade: Any, call_tool: Any
) -> None:
    for ref in (10, "10", "AID10", "aid10"):
        out = await call_tool(facade, "get_assertion", {"assertion_id": ref})
        assert out["assertion"]["id"] == 10
    out = await call_tool(facade, "get_evidence_item", {"evidence_id": "EID95"})
    assert out["evidence_item"]["source"]["citation_id"] == "24583796"


async def test_evidence_paging_suggests_next_page(facade: Any, call_tool: Any) -> None:
    out = await call_tool(facade, "search_evidence_items", {"molecular_profile_id": 12})
    assert out["_meta"]["next_commands"][0] == {
        "tool": "search_evidence_items",
        "arguments": {"molecular_profile_id": 12, "limit": 10, "offset": 10},
    }


async def test_off_enum_filter_is_invalid_input_with_allowed_values(facade: Any) -> None:
    res = await _raw(facade, "search_assertions", {"amp_level": "TIER_V"})
    body = res.structured_content
    assert res.is_error is True and body["error_code"] == "invalid_input"
    assert "TIER_I_LEVEL_A" in body["allowed_values"]


async def test_over_cap_limit_suggests_the_clamped_call(facade: Any) -> None:
    args = {"molecular_profile_id": 12, "limit": 500}
    res = await _raw(facade, "search_evidence_items", args)
    assert res.is_error is True
    assert res.structured_content["_meta"]["next_commands"] == [
        {"tool": "search_evidence_items", "arguments": {**args, "limit": 50}}
    ]


async def test_variant_name_in_an_id_slot_suggests_the_profile_search(facade: Any) -> None:
    res = await _raw(facade, "get_molecular_profile", {"molecular_profile_id": "BRAF V600E"})
    assert res.is_error is True
    assert res.structured_content["_meta"]["next_commands"] == [
        {"tool": "search_molecular_profiles", "arguments": {"query": "BRAF V600E"}}
    ]


async def test_foreign_gene_id_is_rejected_with_a_converter(facade: Any) -> None:
    res = await _raw(facade, "get_gene", {"gene": "ENSG00000133703"})
    body = res.structured_content
    assert res.is_error is True and body["field"] == "gene" and body["allowed_values"]
    assert body["_meta"]["next_commands"] == [
        {"tool": "hgnc_resolve_symbol", "arguments": {"query": "ENSG00000133703"}}
    ]


async def test_capabilities_and_diagnostics(facade: Any, call_tool: Any) -> None:
    caps = await call_tool(facade, "get_server_capabilities", {})
    assert caps["tools"] == TOOLS and caps["research_use_only"] is True
    assert "CC0" in caps["license"] and "28138153" in caps["recommended_citation"]
    diag = await call_tool(facade, "get_diagnostics", {})
    assert diag["upstream"]["base_url"] == "https://civicdb.org"


async def test_descriptions_name_only_returned_fields(facade: Any, call_tool: Any) -> None:
    """Contract truth: the fields a description promises are in the response."""
    found = await call_tool(facade, "search_molecular_profiles", {"query": "BRAF V600E"})
    assert {"exact_match", "simple", "complex"} <= set(found)
    assert {"id", "name", "kind"} <= set(found["simple"][0])
    mp = await call_tool(facade, "get_molecular_profile", {"molecular_profile_id": 79})
    assert {"evidence_note", "assertions"} <= set(mp)
    variant = (await call_tool(facade, "get_variant", {"variant_id": 12}))["variant"]
    assert {"coordinates", "hgvs_genomic", "mane_select_hgvs", "caid", "clinvar_ids"} <= set(
        variant
    )
    gene = await call_tool(facade, "get_gene", {"gene": "BRAF"})
    assert {"variants", "total"} <= set(gene)
    row = gene["variants"][0]
    assert "single_variant_molecular_profile_id" in row


async def test_significance_enum_covers_civic_vocabulary(facade: Any) -> None:
    """Every CIViC EvidenceSignificance value (introspected 2026-11-20) is accepted."""
    civic = [
        "SENSITIVITYRESPONSE",
        "RESISTANCE",
        "BETTER_OUTCOME",
        "POOR_OUTCOME",
        "POSITIVE",
        "NEGATIVE",
        "NA",
        "ADVERSE_RESPONSE",
        "PATHOGENIC",
        "LIKELY_PATHOGENIC",
        "BENIGN",
        "LIKELY_BENIGN",
        "UNCERTAIN_SIGNIFICANCE",
        "REDUCED_SENSITIVITY",
        "GAIN_OF_FUNCTION",
        "LOSS_OF_FUNCTION",
        "UNALTERED_FUNCTION",
        "NEOMORPHIC",
        "UNKNOWN",
        "DOMINANT_NEGATIVE",
        "PREDISPOSITION",
        "PROTECTIVENESS",
        "ONCOGENICITY",
        "LIKELY_ONCOGENIC",
    ]
    async with Client(facade) as client:
        tool = next(t for t in await client.list_tools() if t.name == "search_evidence_items")
    prop = tool.input_schema["properties"]["significance"]
    enum = next(b["enum"] for b in prop.get("anyOf", [prop]) if "enum" in b)
    assert set(enum) == set(civic)
