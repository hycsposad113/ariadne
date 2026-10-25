"""Fake-transport boundary for Week 7 explanations.

Live clients are refused here. The service stores the public output only.
"""

from __future__ import annotations

from typing import Any

from urban_design.week7.service import FakeTransport, Week7Refusal, Week7Service


def interpret_request(
    service: Week7Service,
    workspace_id: str,
    transport: Any,
    *,
    source_text: str,
) -> dict[str, Any]:
    if not isinstance(transport, FakeTransport):
        raise Week7Refusal("live_transport_forbidden", {"live_ai": "OFFLINE"})
    return service.interpret(workspace_id, transport, source_text=source_text)
