"""Discovery tools: ``get_server_capabilities`` and ``get_diagnostics`` (zero-arg)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from civic_link.buildinfo import build_info
from civic_link.mcp import metrics
from civic_link.mcp.annotations import READ_ONLY_OPEN_WORLD
from civic_link.mcp.capabilities import build_capabilities, capabilities_version
from civic_link.mcp.envelope import McpErrorContext, ToolReturn, run_mcp_tool
from civic_link.mcp.next_commands import cmd
from civic_link.mcp.service_adapters import get_civic_service

if TYPE_CHECKING:
    from fastmcp import FastMCP

_FIRST_STEP = cmd("search_molecular_profiles", query="BRAF V600E")


def register_discovery_tools(mcp: FastMCP) -> None:
    """Register the discovery tools on a FastMCP instance."""

    @mcp.tool(
        name="get_server_capabilities",
        annotations=READ_ONLY_OPEN_WORLD,
        output_schema=None,
        tags={"discovery"},
        description=(
            "Describe this server: CIViC identifiers, limits, data release, licence, "
            "classification axes, rate-limit policy and error codes. "
            "Signature: get_server_capabilities()."
        ),
    )
    async def get_server_capabilities() -> ToolReturn:
        async def call() -> dict[str, Any]:
            payload = build_capabilities()
            payload["_meta"] = {"next_commands": [_FIRST_STEP]}
            return payload

        return await run_mcp_tool(
            "get_server_capabilities", call, context=McpErrorContext("get_server_capabilities")
        )

    @mcp.tool(
        name="get_diagnostics",
        annotations=READ_ONLY_OPEN_WORLD,
        output_schema=None,
        tags={"discovery"},
        description=(
            "Report runtime state without calling CIViC: build, upstream request "
            "budget (today's usage vs the daily cap), cache hits and tool latency metrics. "
            "Signature: get_diagnostics()."
        ),
    )
    async def get_diagnostics() -> ToolReturn:
        async def call() -> dict[str, Any]:
            service = get_civic_service()
            client = service.client
            return {
                "build": build_info(),
                "upstream": {
                    "base_url": client.settings.base_url,
                    "requests_since_start": client.upstream_requests,
                    "cache_hits": client.cache_hits,
                    "rate_limiter": client.limiter.stats(),
                },
                "metrics": metrics.snapshot(),
                "capabilities_version": capabilities_version(),
                "_meta": {"next_commands": [cmd("get_server_capabilities"), _FIRST_STEP]},
            }

        return await run_mcp_tool(
            "get_diagnostics", call, context=McpErrorContext("get_diagnostics")
        )
