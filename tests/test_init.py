"""Tests for setting up and unloading the integration."""

from collections.abc import Iterator
import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_CLIENT_ID, CONF_CLIENT_SECRET, EVENT_STATE_CHANGED
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.alexa_bridge import BridgeRuntime
from custom_components.alexa_bridge.config import BridgeAuth, BridgeConfig
from custom_components.alexa_bridge.const import DOMAIN, STORE_CONFIG, VIEW_URL
from custom_components.alexa_bridge.sync import SyncManager

from .test_view import accept_grant_message

FIXTURES = Path(__file__).parent / "fixtures"
PROACTIVE = "homeassistant.components.alexa.config.async_enable_proactive_mode"
PROACTIVE_HANDLERS = "homeassistant.components.alexa.handlers.async_enable_proactive_mode"


@pytest.fixture
def proactive() -> Iterator[AsyncMock]:
    """Never reach Amazon; expose the engine's proactive-mode entry point."""
    with patch(PROACTIVE, AsyncMock(return_value=MagicMock())) as mock:
        yield mock


def _entry(hass: HomeAssistant) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_CLIENT_ID: "client-id", CONF_CLIENT_SECRET: "client-secret"},
        options={"domains": ["light"]},
    )
    entry.add_to_hass(hass)
    return entry


def _discover() -> dict[str, Any]:
    return json.loads((FIXTURES / "discover.json").read_text())


async def _post(client) -> dict[str, Any]:
    resp = await client.post(VIEW_URL, json=_discover())
    assert resp.status == 200
    return await resp.json()


async def test_setup_registers_view_and_unload(
    hass: HomeAssistant, hass_client, proactive: AsyncMock
) -> None:
    hass.states.async_set("light.sala", "off", {"friendly_name": "sala"})
    entry = _entry(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    assert isinstance(entry.runtime_data, BridgeRuntime)
    assert isinstance(entry.runtime_data.config, BridgeConfig)
    assert isinstance(entry.runtime_data.sync, SyncManager)
    client = await hass_client()

    body = await _post(client)
    assert body["event"]["header"]["name"] == "Discover.Response"

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    body = await _post(client)
    assert body["event"]["header"]["name"] == "ErrorResponse"
    assert body["event"]["payload"]["type"] == "BRIDGE_UNREACHABLE"

    # Setting up again must not register the view a second time.
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    body = await _post(client)
    assert body["event"]["header"]["name"] == "Discover.Response"


async def test_repair_issue_when_stock_alexa_loaded(
    hass: HomeAssistant, proactive: AsyncMock
) -> None:
    hass.config.components.add("alexa")
    entry = _entry(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    issue = ir.async_get(hass).async_get_issue(DOMAIN, "stock_alexa_configured")
    assert issue is not None
    assert issue.translation_key == "stock_alexa_configured"


async def test_no_repair_issue_without_stock_alexa(
    hass: HomeAssistant, proactive: AsyncMock
) -> None:
    entry = _entry(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert ir.async_get(hass).async_get_issue(DOMAIN, "stock_alexa_configured") is None


async def test_proactive_mode_enabled_when_already_authorized(
    hass: HomeAssistant, hass_storage: dict[str, Any], proactive: AsyncMock
) -> None:
    hass_storage[STORE_CONFIG] = {
        "version": 1,
        "key": STORE_CONFIG,
        "data": {"authorized": True},
    }
    entry = _entry(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    proactive.assert_awaited_once()
    config = entry.runtime_data.config
    assert config.is_reporting_states

    # HA drops runtime_data on unload: keep our own reference.
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert not config.is_reporting_states


async def test_proactive_mode_not_enabled_when_not_authorized(
    hass: HomeAssistant, proactive: AsyncMock
) -> None:
    entry = _entry(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    proactive.assert_not_awaited()


async def test_proactive_mode_failure_does_not_fail_setup(
    hass: HomeAssistant, hass_storage: dict[str, Any], proactive: AsyncMock
) -> None:
    hass_storage[STORE_CONFIG] = {
        "version": 1,
        "key": STORE_CONFIG,
        "data": {"authorized": True},
    }
    proactive.side_effect = RuntimeError("LWA token refresh failed")
    entry = _entry(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    assert not entry.runtime_data.config.is_reporting_states


def _state_listeners(hass: HomeAssistant) -> int:
    return hass.bus.async_listeners().get(EVENT_STATE_CHANGED, 0)


async def test_accept_grant_single_state_listener_removed_on_unload(
    hass: HomeAssistant, hass_client
) -> None:
    """Real proactive mode: one listener whatever the relinks, none after unload."""
    entry = _entry(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    baseline = _state_listeners(hass)
    client = await hass_client()

    with (
        patch.object(BridgeAuth, "async_do_auth", AsyncMock(return_value="tok")),
        patch.object(BridgeAuth, "async_get_access_token", AsyncMock(return_value="tok")),
        patch(PROACTIVE_HANDLERS) as engine_proactive,
    ):
        for _ in range(3):  # first link, then two relinks
            resp = await client.post(VIEW_URL, json=accept_grant_message())
            body = await resp.json()
            assert body["event"]["header"]["name"] == "AcceptGrant.Response"
            await hass.async_block_till_done()
            assert _state_listeners(hass) == baseline + 1
        # A later directive through the engine adds nothing either.
        await _post(client)
        assert _state_listeners(hass) == baseline + 1
    engine_proactive.assert_not_called()

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert _state_listeners(hass) == baseline
