"""Live CIViC GraphQL checks (opt-in: CIVIC_LINK_LIVE_INTEGRATION=1 make test-integration).

A handful of calls through the real rate limiter. The plan's acceptance path, plus the
upstream assumptions the recorded fixtures encode: BRAF V600E -> MP 12 (simple, with complex
profiles listed apart), accepted evidence items, AID10 Tier I Level A, GRCh37 primary
coordinates with a GRCh38 HGVS, the silent 100-node page cap, and the nightly variant index.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator

import pytest

from civic_link.api.client import CivicClient
from civic_link.config import CivicSettings
from civic_link.exceptions import AmbiguousQueryError, NotFoundError
from civic_link.service import CivicService

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.environ.get("CIVIC_LINK_LIVE_INTEGRATION") != "1",
        reason="set CIVIC_LINK_LIVE_INTEGRATION=1 to call the live CIViC API",
    ),
]


@pytest.fixture
async def service() -> AsyncIterator[CivicService]:
    client = CivicClient(CivicSettings())
    try:
        yield CivicService(client)
    finally:
        await client.aclose()


async def test_live_braf_v600e_acceptance(service: CivicService) -> None:
    found = await service.search_molecular_profiles("BRAF V600E", 100, 0)
    assert found["exact_match"]["id"] == 12 and found["complex"]
    assert not {r["id"] for r in found["complex"]} & {r["id"] for r in found["simple"]}
    evidence = await service.search_evidence_items(molecular_profile_id=12, limit=5)
    assert evidence["total"] > 50 and evidence["truncated"] is True
    assertions = await service.search_assertions(molecular_profile_id=12, limit=50)
    aid10 = next(a for a in assertions["assertions"] if a["id"] == 10)
    assert aid10["actionability"]["amp_tier_level"] == "TIER_I_LEVEL_A"
    assert assertions["data_version"].startswith("CIViC ") and "live:" in assertions["data_version"]


async def test_live_variant_assemblies_and_identifier_lookups(service: CivicService) -> None:
    variant = (await service.get_variant(12))["variant"]
    assert variant["coordinates"]["assembly"] == "GRCh37"
    assert "GRCh38" in {g["assembly"] for g in variant["hgvs_genomic"]}
    for query in ("CA123643", "NC_000007.14:g.140753336A>T"):
        assert (await service.search_molecular_profiles(query, 5, 0))["exact_match"]["id"] == 12
    # ClinVar 13961 is linked to both BRAF V600E and the codon-level BRAF V600 entry
    with pytest.raises(AmbiguousQueryError) as info:
        await service.search_molecular_profiles("13961", 5, 0)
    assert 12 in {c["variant_id"] for c in info.value.candidates}  # type: ignore[index]


async def test_live_page_cap_is_silent_upstream(service: CivicService) -> None:
    from civic_link import queries as Q

    # caps differ per connection (evidence items 100, profiles 300); limits stay <= 100
    variables = {"status": "ACCEPTED", "first": 500}
    conn = (await service.client.graphql(Q.EVIDENCE_SEARCH, variables))["evidenceItems"]
    assert conn["totalCount"] > 100 and len(conn["nodes"]) == 100


async def test_live_unknown_profile_is_not_found(service: CivicService) -> None:
    with pytest.raises(NotFoundError) as info:
        await service.get_molecular_profile(99_999_999)
    assert info.value.extra["field"] == "molecular_profile_id"
