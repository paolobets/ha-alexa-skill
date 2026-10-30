"""Tests for the smart home HTTP view."""

from collections.abc import Iterator
import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from homeassistant.const import CONF_CLIENT_ID, CONF_CLIENT_SECRET
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er, issue_registry as ir
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_mock_service,
)

from custom_components.alexa_bridge.config import BridgeAuth, BridgeConfig
from custom_components.alexa_bridge.const import DOMAIN, VIEW_URL
from custom_components.alexa_bridge.view import BridgeSmartHomeView

FIXTURES = Path(__file__).parent / "fixtures"
PROACTIVE = "homeassistant.components.alexa.config.async_enable_proactive_mode"
PROACTIVE_HANDLERS = "homeassistant.components.alexa.handlers.async_enable_proactive_mode"
ISSUE = "proactive_not_authorized"


@pytest.fixture(autouse=True)
def no_proactive_mode() -> Iterator[None]:
    """Every message marks the config authorized; never reach Amazon."""
    with patch(PROACTIVE, AsyncMock(return_value=MagicMock())):
        yield


def _message(name: str, endpoint_id: str | None = None) -> dict[str, Any]:
    message = json.loads((FIXTURES / f"{name}.json").read_text())
    if endpoint_id is not None:
        message["directive"]["endpoint"]["endpointId"] = endpoint_id
    return message


def _add(hass: HomeAssistant, entity_id: str, state: str = "off") -> er.RegistryEntry:
    domain, object_id = entity_id.split(".")
    entry = er.async_get(hass).async_get_or_create(
        domain, "test", f"uid_{object_id}", suggested_object_id=object_id
    )
    assert entry.entity_id == entity_id
    hass.states.async_set(entity_id, state, {"friendly_name": object_id})
    return entry


async def _setup(hass: HomeAssistant, get_config) -> None:
    assert await async_setup_component(hass, "http", {})
    hass.http.register_view(BridgeSmartHomeView(get_config))


async def _config(hass: HomeAssistant, options: dict[str, Any]) -> BridgeConfig:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_CLIENT_ID: "client-id", CONF_CLIENT_SECRET: "client-secret"},
        options=options,
    )
    entry.add_to_hass(hass)
    config = BridgeConfig(hass, entry)
    await config.async_initialize()
    await _setup(hass, lambda: config)
    return config


async def _post(client, message: dict[str, Any]) -> dict[str, Any]:
    resp = await client.post(VIEW_URL, json=message)
    assert resp.status == 200
    return await resp.json()


async def test_discovery_returns_only_selected(hass: HomeAssistant, hass_client):
    lights = [_add(hass, "light.sala"), _add(hass, "light.cucina")]
    _add(hass, "switch.pompa")
    await _config(hass, {"domains": ["light"]})

    body = await _post(await hass_client(), _message("discover"))

    endpoints = body["event"]["payload"]["endpoints"]
    assert sorted(e["endpointId"] for e in endpoints) == sorted(
        "ha-" + entry.id for entry in lights
    )


async def test_turn_on_with_stable_id_calls_service(hass: HomeAssistant, hass_client):
    entry = _add(hass, "light.sala")
    await _config(hass, {"domains": ["light"]})
    calls = async_mock_service(hass, "light", "turn_on")

    body = await _post(await hass_client(), _message("turn_on", "ha-" + entry.id))

    assert body["event"]["header"]["name"] == "Response"
    assert [call.data["entity_id"] for call in calls] == ["light.sala"]
    assert body["event"]["endpoint"]["endpointId"] == "ha-" + entry.id


async def test_report_state_keeps_stable_id(hass: HomeAssistant, hass_client):
    entry = _add(hass, "light.sala", "on")
    await _config(hass, {"domains": ["light"]})

    body = await _post(await hass_client(), _message("report_state", "ha-" + entry.id))

    assert body["event"]["header"]["name"] == "StateReport"
    assert body["event"]["endpoint"]["endpointId"] == "ha-" + entry.id
    power = [
        p for p in body["context"]["properties"] if p["name"] == "powerState"
    ]
    assert power[0]["value"] == "ON"


async def test_unknown_endpoint_returns_no_such_endpoint(
    hass: HomeAssistant, hass_client
):
    await _config(hass, {"domains": ["light"]})

    body = await _post(await hass_client(), _message("turn_on", "ha-doesnotexist"))

    assert body["event"]["payload"]["type"] == "NO_SUCH_ENDPOINT"
    assert body["event"]["endpoint"]["endpointId"] == "ha-doesnotexist"


async def test_not_shared_entity_rejected(hass: HomeAssistant, hass_client):
    entry = _add(hass, "switch.pompa")
    await _config(hass, {"domains": ["light"]})
    calls = async_mock_service(hass, "switch", "turn_on")

    body = await _post(await hass_client(), _message("turn_on", "ha-" + entry.id))

    assert body["event"]["payload"]["type"] == "NO_SUCH_ENDPOINT"
    assert calls == []


async def test_no_config_returns_bridge_unreachable(hass: HomeAssistant, hass_client):
    entry = _add(hass, "light.sala")
    await _setup(hass, lambda: None)
    client = await hass_client()

    for message in (_message("discover"), _message("turn_on", "ha-" + entry.id)):
        body = await _post(client, message)
        assert body["event"]["header"]["name"] == "ErrorResponse"
        assert body["event"]["payload"]["type"] == "BRIDGE_UNREACHABLE"

    assert body["event"]["endpoint"]["endpointId"] == "ha-" + entry.id


async def test_requires_auth(hass: HomeAssistant, hass_client_no_auth):
    await _config(hass, {"domains": ["light"]})
    client = await hass_client_no_auth()

    resp = await client.post(VIEW_URL, json=_message("discover"))

    assert resp.status == 401


def accept_grant_message() -> dict[str, Any]:
    return {
        "directive": {
            "header": {
                "namespace": "Alexa.Authorization",
                "name": "AcceptGrant",
                "messageId": "msg-1",
                "payloadVersion": "3",
            },
            "payload": {
                "grant": {"type": "OAuth2.AuthorizationCode", "code": "the-code"},
                "grantee": {"type": "BearerToken", "token": "bearer"},
            },
        }
    }


async def test_accept_grant_answered_by_bridge(hass: HomeAssistant, hass_client):
    config = await _config(hass, {"domains": ["light"]})
    with (
        patch.object(BridgeAuth, "async_do_auth", AsyncMock(return_value="tok")) as do_auth,
        patch(PROACTIVE_HANDLERS) as engine_proactive,
    ):
        body = await _post(await hass_client(), accept_grant_message())

    assert body["event"]["header"]["namespace"] == "Alexa.Authorization"
    assert body["event"]["header"]["name"] == "AcceptGrant.Response"
    assert body["event"]["payload"] == {}
    do_auth.assert_awaited_once_with("the-code")
    engine_proactive.assert_not_called()
    assert config.authorized
    assert config.is_reporting_states
    assert ir.async_get(hass).async_get_issue(DOMAIN, ISSUE) is None


@pytest.mark.parametrize(
    "do_auth",
    [AsyncMock(return_value=None), AsyncMock(side_effect=RuntimeError("boom"))],
    ids=["none", "raises"],
)
async def test_accept_grant_failure_reported(
    hass: HomeAssistant, hass_client, do_auth: AsyncMock
):
    config = await _config(hass, {"domains": ["light"]})
    on_authorized = AsyncMock()
    config.on_authorized = on_authorized
    with patch.object(BridgeAuth, "async_do_auth", do_auth):
        body = await _post(await hass_client(), accept_grant_message())
        await hass.async_block_till_done()

    assert body["event"]["header"]["namespace"] == "Alexa.Authorization"
    assert body["event"]["header"]["name"] == "ErrorResponse"
    assert body["event"]["payload"]["type"] == "ACCEPT_GRANT_FAILED"
    assert body["event"]["payload"]["message"]
    on_authorized.assert_not_called()
    assert not config.authorized
    assert not config.is_reporting_states
    issue = ir.async_get(hass).async_get_issue(DOMAIN, ISSUE)
    assert issue is not None
    assert issue.translation_key == ISSUE


async def test_accept_grant_without_config_returns_bridge_unreachable(
    hass: HomeAssistant, hass_client
):
    await _setup(hass, lambda: None)
    with patch.object(BridgeAuth, "async_do_auth", AsyncMock(return_value="tok")) as do_auth:
        body = await _post(await hass_client(), accept_grant_message())

    assert body["event"]["header"]["name"] == "ErrorResponse"
    assert body["event"]["payload"]["type"] == "BRIDGE_UNREACHABLE"
    do_auth.assert_not_called()


async def test_accept_grant_succeeds_when_proactive_mode_fails(
    hass: HomeAssistant, hass_client
):
    config = await _config(hass, {"domains": ["light"]})
    with (
        patch.object(BridgeAuth, "async_do_auth", AsyncMock(return_value="tok")),
        patch.object(
            BridgeConfig,
            "async_enable_proactive_mode",
            # First call from set_authorized(True), second after the grant.
            AsyncMock(side_effect=[None, RuntimeError("boom")]),
        ),
    ):
        body = await _post(await hass_client(), accept_grant_message())

    assert body["event"]["header"]["name"] == "AcceptGrant.Response"
    assert config.authorized
    assert ir.async_get(hass).async_get_issue(DOMAIN, ISSUE) is None
