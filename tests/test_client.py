"""CIViC GraphQL client: honest User-Agent, caching, backoff and typed errors."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator

import httpx
import pytest
import respx

from civic_link import __version__
from civic_link.api.client import GRAPHQL_PATH, CivicClient
from civic_link.exceptions import (
    InvalidInputError,
    RateLimitedError,
    UpstreamSchemaError,
    UpstreamUnavailableError,
)
from tests.conftest import BASE, fast_settings, load

DOC = "query Q($molecular_profile_id: Int!) { molecularProfile(id: $molecular_profile_id) { id } }"
VARS: dict[str, object] = {"molecular_profile_id": 12}
OK = {"data": {"molecularProfile": {"id": 12}}}


@pytest.fixture
async def client() -> AsyncIterator[CivicClient]:
    c = CivicClient(fast_settings())
    yield c
    await c.aclose()


@respx.mock(base_url=BASE)
async def test_posts_fixed_document_with_variables_and_honest_user_agent(
    respx_mock: respx.MockRouter, client: CivicClient
) -> None:
    route = respx_mock.post(GRAPHQL_PATH).mock(return_value=httpx.Response(200, json=OK))
    data = await client.graphql(DOC, VARS)
    assert data == {"molecularProfile": {"id": 12}}
    sent = json.loads(route.calls.last.request.content)
    assert sent == {"query": DOC, "variables": VARS}
    ua = route.calls.last.request.headers["user-agent"]
    assert ua.startswith(f"civic-link/{__version__}") and "berntpopp/civic-link" in ua


@respx.mock(base_url=BASE)
async def test_variable_error_in_http_200_is_invalid_input_naming_the_parameter(
    respx_mock: respx.MockRouter, client: CivicClient
) -> None:
    respx_mock.post(GRAPHQL_PATH).mock(
        return_value=httpx.Response(200, json=load("graphql_variable_error"))
    )
    with pytest.raises(InvalidInputError) as info:
        await client.graphql(DOC, {"molecular_profile_id": 99999999999})
    assert info.value.extra["field"] == "molecular_profile_id"
    assert "99999999999" not in info.value.message  # upstream text is never echoed


@respx.mock(base_url=BASE)
async def test_variable_error_maps_through_the_field_table(
    respx_mock: respx.MockRouter, client: CivicClient
) -> None:
    body = {"errors": [{"message": "Variable $disease_id of type Int was provided invalid value"}]}
    respx_mock.post(GRAPHQL_PATH).mock(return_value=httpx.Response(200, json=body))
    with pytest.raises(InvalidInputError) as info:
        await client.graphql(DOC, {"disease_id": 1}, fields={"disease_id": "disease"})
    assert info.value.extra["field"] == "disease"


@respx.mock(base_url=BASE)
async def test_other_graphql_error_is_upstream_unavailable_and_never_reflected(
    respx_mock: respx.MockRouter, client: CivicClient
) -> None:
    body = {
        "data": None,
        "errors": [{"message": "Field 'x' doesn't exist; Variable $evil ‮"}],
    }
    respx_mock.post(GRAPHQL_PATH).mock(return_value=httpx.Response(200, json=body))
    with pytest.raises(UpstreamUnavailableError) as info:
        await client.graphql(DOC, VARS)
    assert not isinstance(info.value, InvalidInputError)
    assert info.value.extra["field"] == "response" and "doesn't" not in info.value.message


@respx.mock(base_url=BASE)
async def test_identical_calls_hit_upstream_once(
    respx_mock: respx.MockRouter, client: CivicClient
) -> None:
    route = respx_mock.post(GRAPHQL_PATH).mock(return_value=httpx.Response(200, json=OK))
    await client.graphql(DOC, VARS)
    await client.graphql(DOC, dict(VARS))
    assert route.call_count == 1


@respx.mock(base_url=BASE)
async def test_errors_are_not_cached(respx_mock: respx.MockRouter, client: CivicClient) -> None:
    route = respx_mock.post(GRAPHQL_PATH).mock(
        side_effect=[httpx.Response(200, json={"errors": [{"message": "boom"}]}), OK_RESPONSE()]
    )
    with pytest.raises(UpstreamUnavailableError):
        await client.graphql(DOC, VARS)
    assert await client.graphql(DOC, VARS) == OK["data"]
    assert route.call_count == 2


def OK_RESPONSE() -> httpx.Response:  # noqa: N802 - reads like the constant it builds
    return httpx.Response(200, json=OK)


@respx.mock(base_url=BASE)
async def test_429_retries_then_rate_limited_with_retry_after(
    respx_mock: respx.MockRouter, client: CivicClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    slept: list[float] = []

    async def _sleep(seconds: float) -> None:
        slept.append(seconds)

    monkeypatch.setattr("civic_link.api.client.asyncio.sleep", _sleep)
    route = respx_mock.post(GRAPHQL_PATH).mock(
        return_value=httpx.Response(429, headers={"Retry-After": "7"})
    )
    with pytest.raises(RateLimitedError) as info:
        await client.graphql(DOC, VARS)
    assert route.call_count == 1 + fast_settings().max_retries
    assert info.value.extra["retry_after_s"] == 7.0
    assert slept == [7.0, 7.0]


@respx.mock(base_url=BASE)
async def test_503_then_success_recovers(respx_mock: respx.MockRouter, client: CivicClient) -> None:
    respx_mock.post(GRAPHQL_PATH).mock(side_effect=[httpx.Response(503), OK_RESPONSE()])
    assert await client.graphql(DOC, VARS) == OK["data"]


@respx.mock(base_url=BASE)
async def test_persistent_timeout_is_retryable_upstream_unavailable(
    respx_mock: respx.MockRouter, client: CivicClient
) -> None:
    respx_mock.post(GRAPHQL_PATH).mock(side_effect=httpx.ReadTimeout("slow"))
    with pytest.raises(UpstreamUnavailableError) as info:
        await client.graphql(DOC, VARS)
    assert info.value.retryable is True


@respx.mock(base_url=BASE)
async def test_non_json_or_dataless_success_is_schema_error(
    respx_mock: respx.MockRouter, client: CivicClient
) -> None:
    respx_mock.post(GRAPHQL_PATH).mock(
        side_effect=[httpx.Response(200, text="<html>"), httpx.Response(200, json={"x": 1})]
    )
    with pytest.raises(UpstreamSchemaError):
        await client.graphql(DOC, VARS)
    with pytest.raises(UpstreamSchemaError):
        await client.graphql(DOC, {"molecular_profile_id": 13})


@respx.mock(base_url=BASE)
async def test_unexpected_status_is_fixed_message(
    respx_mock: respx.MockRouter, client: CivicClient
) -> None:
    respx_mock.post(GRAPHQL_PATH).mock(return_value=httpx.Response(404, text="secret path"))
    with pytest.raises(UpstreamUnavailableError) as info:
        await client.graphql(DOC, VARS)
    assert "secret" not in info.value.message


@respx.mock(base_url=BASE)
async def test_get_text_reads_a_same_origin_download(
    respx_mock: respx.MockRouter, client: CivicClient
) -> None:
    respx_mock.get("/downloads/x.tsv").mock(return_value=httpx.Response(200, text="a\tb\n"))
    assert await client.get_text("/downloads/x.tsv") == "a\tb\n"


async def test_rate_limit_refusal_propagates_before_any_request() -> None:
    settings = fast_settings()
    settings.daily_cap = 1
    c = CivicClient(settings)
    with respx.mock(base_url=BASE) as router:
        route = router.post(GRAPHQL_PATH).mock(return_value=httpx.Response(200, json=OK))
        await c.graphql(DOC, VARS)
        with pytest.raises(RateLimitedError):
            await c.graphql(DOC, {"molecular_profile_id": 1})
        assert route.call_count == 1
    await c.aclose()


@respx.mock(base_url=BASE)
async def test_concurrent_identical_calls_share_one_upstream_request(
    respx_mock: respx.MockRouter, client: CivicClient
) -> None:
    async def slow(_: httpx.Request) -> httpx.Response:
        await asyncio.sleep(0.01)
        return httpx.Response(200, json=OK)

    route = respx_mock.post(GRAPHQL_PATH).mock(side_effect=slow)
    results = await asyncio.gather(*(client.graphql(DOC, VARS) for _ in range(3)))
    assert route.call_count == 1 and all(r == OK["data"] for r in results)
