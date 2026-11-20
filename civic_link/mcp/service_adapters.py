"""Process-wide dependency-injection registry for the CIViC service.

The running server registers a concrete :class:`CivicService` at startup; tests inject
one over a respx-mocked client. An unregistered service is an ``internal`` error.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from civic_link.exceptions import InternalError

if TYPE_CHECKING:  # pragma: no cover - import only for type checkers
    from civic_link.service import CivicService

_service: CivicService | None = None


def get_civic_service() -> CivicService:
    """Return the registered :class:`CivicService` or raise ``InternalError``."""
    if _service is None:
        raise InternalError(
            "CIViC service is not initialised; the server must register it at startup.",
            recovery_action="switch_tool",
        )
    return _service


def set_civic_service(service: CivicService | None) -> None:
    """Register (or clear) the process-wide service. Used by the server and tests."""
    global _service
    _service = service
