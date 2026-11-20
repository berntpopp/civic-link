"""CIViC MCP tool registrations."""

from __future__ import annotations

from typing import TYPE_CHECKING

from civic_link.mcp.tools.civic import register_civic_tools
from civic_link.mcp.tools.discovery import register_discovery_tools

if TYPE_CHECKING:
    from fastmcp import FastMCP


def register_all_tools(mcp: FastMCP) -> None:
    """Register every tool group on a FastMCP instance in canonical order."""
    register_discovery_tools(mcp)
    register_civic_tools(mcp)
