from __future__ import annotations

import datetime

import pytest

from app import mcp_server


@pytest.mark.asyncio
async def test_mcp_tool_metadata_describes_agent_input():
    tools = await mcp_server.mcp.list_tools()

    assert [tool.name for tool in tools] == ["get_spx_gamma_levels"]
    tool = tools[0]
    assert "calendar DTE integer" in tool.description
    assert tool.annotations.readOnlyHint is True
    assert "dte" in tool.inputSchema["properties"]


def test_mcp_transport_allows_production_hostname():
    security = mcp_server.mcp.settings.transport_security
    assert security is not None

    assert "gex.roymeshulam.com" in security.allowed_hosts
    assert "https://gex.roymeshulam.com" in security.allowed_origins
    assert "https://chatgpt.com" in security.allowed_origins
    assert "https://chat.openai.com" in security.allowed_origins


@pytest.mark.asyncio
async def test_mcp_tool_returns_single_or_array(monkeypatch):
    async def fake_get_bundle():
        return {
            "levels": {
                "2026-07-13": {
                    "call_wall": 6300.0,
                    "flip": 6250.5,
                    "put_wall": 6200.0,
                },
            },
        }, {}

    monkeypatch.setattr(mcp_server.runtime, "get_bundle", fake_get_bundle)
    monkeypatch.setattr(mcp_server.market, "today_expiry_date",
                        lambda: datetime.date(2026, 7, 12))

    single = await mcp_server.get_spx_gamma_levels(1)
    multiple = await mcp_server.get_spx_gamma_levels([1, "2026-07-14"])

    assert single["expiry"] == "2026-07-13"
    assert single["call_wall"] == 6300.0
    assert isinstance(multiple, list)
    assert multiple[1]["available"] is False
