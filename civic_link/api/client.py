"""Async client for the CIViC GraphQL API (and its same-origin nightly downloads).

Every request: passes the process-wide :class:`RateLimiter`, carries an honest
User-Agent (product/version + project URL, no user data), is restricted to the
configured origin over HTTPS with a hard response-byte cap, and backs off on
429/5xx/timeouts (honouring ``Retry-After``). Successful results are cached in-process
for ``cache_ttl_s`` (no data snapshot is kept).

GraphQL reports errors as HTTP 200 + ``errors[]``. A ``Variable $x`` error becomes
``invalid_input`` naming the tool parameter behind ``$x``; any other GraphQL error is an
upstream fault. Upstream text is used only to classify; callers see fixed messages
(Response-Envelope v1.1 error-message sanitation).
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable, Mapping
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

import httpx

from civic_link import __version__
from civic_link.api.url_guard import (
    MAX_REDIRECTS,
    build_origin_allowlist,
    make_url_guard,
    read_capped_response,
)
from civic_link.config import CivicSettings
from civic_link.exceptions import (
    InvalidInputError,
    RateLimitedError,
    UpstreamSchemaError,
    UpstreamUnavailableError,
)
from civic_link.ratelimit import RateLimiter

USER_AGENT = f"civic-link/{__version__} (+https://github.com/berntpopp/civic-link)"
_RETRY_STATUS = {429, 500, 502, 503, 504}

#: Epoch times of the upstream fetches behind the current tool call; a cache hit reports the
#: fetch that filled its entry (Response-Envelope v1.2 ``retrieved_at``). The MCP plane resets it.
FETCH_TIMES: ContextVar[list[float] | None] = ContextVar("civic_fetch_times", default=None)


def note_fetch(fetched_at: float) -> None:
    """Count an upstream fetch at epoch ``fetched_at`` towards the current call."""
    times = FETCH_TIMES.get()
    if times is not None:
        times.append(fetched_at)


def retrieved_at() -> str:
    """UTC time (``Z``) of the oldest upstream fetch behind this call; now when untracked."""
    times = FETCH_TIMES.get()
    when = datetime.fromtimestamp(min(times), UTC) if times else datetime.now(UTC)
    return when.isoformat(timespec="seconds").replace("+00:00", "Z")


def _retry_after(response: httpx.Response | None) -> float | None:
    raw = response.headers.get("retry-after") if response is not None else None
    try:
        return max(0.0, float(raw)) if raw is not None else None
    except ValueError:
        return None


_VARIABLE = re.compile(r"^Variable \$([A-Za-z_][A-Za-z0-9_]*)\b")


def _graphql_error(
    errors: list[Any], variables: Mapping[str, Any], fields: Mapping[str, str]
) -> Exception:
    """Map CIViC's HTTP-200 ``errors[]`` to a typed error naming the tool parameter."""
    for err in errors:
        match = _VARIABLE.match(str(err.get("message", "")) if isinstance(err, dict) else "")
        if match and match.group(1) in variables:  # only ever echo our own variable names
            field = fields.get(match.group(1), match.group(1))
            return InvalidInputError(
                f"CIViC rejected the value of `{field}`.",
                field=field,
                recovery_action="reformulate_input",
            )
    return UpstreamSchemaError("CIViC answered the query with a GraphQL error.", field="response")


GRAPHQL_PATH = "/api/graphql"


class CivicClient:
    """Rate-limited, cached, origin-guarded client for ``civicdb.org``."""

    def __init__(self, settings: CivicSettings, *, limiter: RateLimiter | None = None) -> None:
        """Build the HTTP client, limiter and cache from settings."""
        self.settings = settings
        self.limiter = limiter or RateLimiter(
            min_interval_s=settings.min_interval_s,
            daily_cap=settings.daily_cap,
            max_wait_s=settings.max_wait_s,
        )
        guard = make_url_guard(build_origin_allowlist(settings.base_url))
        self._http = httpx.AsyncClient(
            base_url=settings.base_url,
            timeout=settings.request_timeout_s,
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            follow_redirects=True,
            max_redirects=MAX_REDIRECTS,
            event_hooks={"request": [guard]},
        )
        self._cache: OrderedDict[str, tuple[float, tuple[Any, float]]] = OrderedDict()
        self._inflight: dict[str, asyncio.Future[tuple[Any, float]]] = {}
        self.upstream_requests = 0
        self.cache_hits = 0

    async def aclose(self) -> None:
        """Close the underlying HTTP connection pool."""
        await self._http.aclose()

    def _cache_get(self, key: str) -> tuple[Any, float] | None:
        hit = self._cache.get(key)
        if hit is None or hit[0] < time.monotonic():
            self._cache.pop(key, None)
            return None
        self._cache.move_to_end(key)
        self.cache_hits += 1
        return hit[1]

    def _cache_put(self, key: str, value: tuple[Any, float]) -> None:
        self._cache[key] = (time.monotonic() + self.settings.cache_ttl_s, value)
        while len(self._cache) > self.settings.cache_maxsize:
            self._cache.popitem(last=False)

    async def _once(self, key: str, fetch: Callable[[], Awaitable[Any]]) -> Any:
        async def timed() -> tuple[Any, float]:
            return await fetch(), time.time()

        hit = self._cache_get(key)
        if hit is None:
            # Single-flight: parallel identical calls share one upstream request (politeness).
            task = self._inflight.get(key)
            if task is None:
                task = self._inflight[key] = asyncio.ensure_future(timed())
                task.add_done_callback(lambda done: self._settle(key, done))
            hit = await asyncio.shield(task)
        note_fetch(hit[1])
        return hit[0]

    def _settle(self, key: str, task: asyncio.Future[tuple[Any, float]]) -> None:
        self._inflight.pop(key, None)
        if not task.cancelled() and task.exception() is None:
            self._cache_put(key, task.result())

    async def graphql(
        self,
        document: str,
        variables: Mapping[str, Any],
        *,
        fields: Mapping[str, str] | None = None,
    ) -> dict[str, Any]:
        """Run one fixed GraphQL ``document``; return ``data`` or raise a typed error.

        ``fields`` maps a variable name to the tool parameter it carries (default: same name).
        """
        body = {"query": document, "variables": dict(variables)}
        key = "POST " + json.dumps(body, sort_keys=True, default=str)

        async def fetch() -> dict[str, Any]:
            response = await self._request("POST", GRAPHQL_PATH, json=body)
            try:
                payload = response.json()
            except ValueError:
                raise UpstreamSchemaError(
                    "CIViC returned a non-JSON body.", field="response"
                ) from None
            if not isinstance(payload, dict):
                raise UpstreamSchemaError("CIViC returned a non-object body.", field="response")
            errors = payload.get("errors")
            if errors:
                raise _graphql_error(
                    errors if isinstance(errors, list) else [], variables, fields or {}
                )
            data = payload.get("data")
            if not isinstance(data, dict):
                raise UpstreamSchemaError("CIViC returned no data object.", field="response")
            return data

        result: dict[str, Any] = await self._once(key, fetch)
        return result

    async def get_text(self, path: str) -> str:
        """GET a same-origin download (e.g. a nightly TSV) as text."""

        async def fetch() -> str:
            return (await self._request("GET", path)).text

        result: str = await self._once("GET " + path, fetch)
        return result

    async def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        attempts = self.settings.max_retries + 1
        response: httpx.Response | None = None
        for attempt in range(attempts):
            if attempt:
                delay = _retry_after(response) or self.settings.backoff_base_s * 2 ** (attempt - 1)
                await asyncio.sleep(min(delay, 30.0))
            await self.limiter.acquire()
            self.upstream_requests += 1
            try:
                response = await read_capped_response(
                    self._http,
                    method,
                    path,
                    max_bytes=self.settings.max_response_bytes,
                    **kwargs,
                )
            except httpx.TimeoutException, httpx.TransportError:
                response = None
                continue
            if response.status_code not in _RETRY_STATUS:
                break
        if response is None or response.status_code in _RETRY_STATUS:
            if response is not None and response.status_code == 429:
                raise RateLimitedError(
                    "CIViC is rate limiting requests. Retry after retry_after_s seconds.",
                    retryable=True,
                    retry_after_s=_retry_after(response) or 60.0,
                )
            raise UpstreamUnavailableError("CIViC is temporarily unavailable.", retryable=True)
        if response.status_code != 200:
            raise UpstreamUnavailableError("CIViC returned an unexpected status.", retryable=False)
        return response
