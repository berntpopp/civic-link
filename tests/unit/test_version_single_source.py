"""Guard: pyproject -> installed metadata -> __version__ -> serverInfo -> /health are one value."""

from __future__ import annotations

import tomllib
from importlib.metadata import version
from pathlib import Path

from fastapi.testclient import TestClient

from civic_link import __version__
from civic_link.app import create_app
from civic_link.buildinfo import build_info
from civic_link.mcp.facade import create_civic_mcp

DIST = "civic-link"


def _pyproject_version() -> str:
    pyproject = Path(__file__).resolve().parents[2] / "pyproject.toml"
    return tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"]["version"]


def test_pyproject_is_the_single_source() -> None:
    assert version(DIST) == _pyproject_version()


def test_dunder_version_is_metadata_derived() -> None:
    assert __version__ == version(DIST)
    assert build_info()["version"] == version(DIST)


def test_mcp_server_info_version_matches_package() -> None:
    assert create_civic_mcp().version == version(DIST)


def test_health_version_matches_package() -> None:
    resp = TestClient(create_app()).get("/health")
    assert resp.status_code == 200
    assert resp.json()["version"] == version(DIST)


def test_build_info_is_fixed_at_startup(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """The sha names the code that is running, not a later checkout of the source tree."""
    first = build_info()
    monkeypatch.setenv("CIVIC_LINK_GIT_SHA", "deadbeef0000")
    assert build_info() == first
