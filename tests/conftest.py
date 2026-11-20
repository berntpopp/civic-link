"""Shared fixtures: a real CivicService over a respx-mocked CIViC GraphQL API.

Unit tests are network-free. ``mocked_civic`` answers each fixed GraphQL document with a
recorded response from ``tests/fixtures/civic/`` (captured from https://civicdb.org/api/graphql
on 2026-11-20 with the exact documents in ``civic_link/queries.py``); ``facade`` wires the
service into a real FastMCP instance and ``call_tool`` drives it through an in-memory
``fastmcp.Client``.
"""

from __future__ import annotations

import json
import pathlib
import re
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from typing import Any

import httpx
import pytest
import respx

from civic_link.api.client import GRAPHQL_PATH, CivicClient
from civic_link.config import CivicSettings
from civic_link.mcp import metrics
from civic_link.mcp.facade import create_civic_mcp
from civic_link.mcp.service_adapters import set_civic_service
from civic_link.service import VARIANT_INDEX_PATH, CivicService

FX = pathlib.Path(__file__).parent / "fixtures" / "civic"
BASE = "https://civicdb.org"


def load(name: str) -> Any:
    """Load a recorded CIViC JSON fixture by file stem."""
    return json.loads((FX / f"{name}.json").read_text())


def fast_settings() -> CivicSettings:
    """Upstream settings with politeness spacing disabled so tests run instantly."""
    return CivicSettings(min_interval_s=0.0, backoff_base_s=0.0)


def _fixture_for(op: str, v: dict[str, Any]) -> str:
    """The recorded response for one (operation, variables) pair."""
    if op == "MpSearch":
        if v.get("name") == "BRAF V600E":
            return "mp_search_braf_v600e"
        if v.get("caid") == "CA123643":
            return "mp_search_caid"
        return "mp_search_variant12" if v.get("variant_id") == 12 else "mp_search_none"
    if op == "MpGet":
        return {12: "mp_get_12", 79: "mp_get_79", 885: "mp_get_885"}.get(
            v["molecular_profile_id"], "mp_get_missing"
        )
    if op == "VariantGet":
        return "variant_get_12" if v["variant_id"] == 12 else "variant_get_missing"
    if op == "EvidenceSearch":
        if v.get("molecular_profile_id") == 12 and not v.get("evidence_type"):
            return "evidence_search_mp12_page2" if v.get("after") else "evidence_search_mp12"
        return "evidence_search_empty"
    if op == "EvidenceGet":
        return "evidence_get_95" if v["evidence_id"] == 95 else "evidence_get_missing"
    if op == "AssertionSearch":
        if v.get("molecular_profile_id") == 12:
            return "assertion_search_mp12"
        if v.get("assertion_type") == "ONCOGENIC":
            return "assertion_search_oncogenic"
        return "assertion_search_mp79"
    if op == "AssertionGet":
        return "assertion_get_10" if v["assertion_id"] == 10 else "assertion_get_missing"
    if op == "GeneGet":
        if v.get("entrez_id") == [3845]:
            return "gene_kras_entrez"
        return {"BRAF": "gene_braf", "KRAS": "gene_kras"}.get(
            (v.get("symbol") or [""])[0], "gene_missing"
        )
    if op == "DiseaseLookup":
        if v.get("doid") == "1909" or str(v.get("disease", "")).casefold() == "melanoma":
            return "disease_doid1909" if v.get("doid") else "disease_melanoma"
        return "disease_none"
    if op == "TherapyLookup":
        hit = str(v.get("therapy", "")).casefold() == "vemurafenib"
        return "therapy_vemurafenib" if hit else "therapy_none"
    return "releases"


def _graphql(request: httpx.Request) -> httpx.Response:
    body = json.loads(request.content)
    match = re.search(r"query\s+(\w+)", body["query"])
    op = match.group(1) if match else ""
    return httpx.Response(200, json=load(_fixture_for(op, body.get("variables") or {})))


@pytest.fixture(autouse=True)
def _reset_metrics() -> Iterator[None]:
    """Keep the process-wide metrics collector clean between tests."""
    metrics.reset()
    yield
    metrics.reset()


@pytest.fixture
def mocked_civic() -> Iterator[respx.MockRouter]:
    """A respx router serving the recorded CIViC fixtures."""
    with respx.mock(base_url=BASE, assert_all_called=False) as router:
        router.post(GRAPHQL_PATH).mock(side_effect=_graphql)
        router.get(VARIANT_INDEX_PATH).mock(
            return_value=httpx.Response(200, text=(FX / "variant_summaries.tsv").read_text())
        )
        yield router


@pytest.fixture
async def civic_service(mocked_civic: respx.MockRouter) -> AsyncIterator[CivicService]:
    """A real CivicService over the respx-mocked client."""
    client = CivicClient(fast_settings())
    try:
        yield CivicService(client)
    finally:
        await client.aclose()


@pytest.fixture
def facade(civic_service: CivicService) -> Iterator[Any]:
    """A FastMCP facade with the fixture service injected; cleans up after."""
    mcp = create_civic_mcp(service_factory=lambda: civic_service)
    yield mcp
    set_civic_service(None)


@pytest.fixture
def call_tool() -> Callable[[Any, str, dict[str, Any]], Awaitable[Any]]:
    """Call a tool through an in-memory ``fastmcp.Client``; return the structured dict."""
    from fastmcp import Client

    async def _call(mcp: Any, name: str, args: dict[str, Any]) -> Any:
        async with Client(mcp) as client:
            res = await client.call_tool(name, args, raise_on_error=False)
        if isinstance(res.structured_content, dict):
            return res.structured_content
        return res.data

    return _call
