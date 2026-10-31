"""Tests for the bridge Alexa config."""

from datetime import timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from homeassistant.components.alexa.smart_home import async_handle_message
from homeassistant.const import CONF_CLIENT_ID, CONF_CLIENT_SECRET
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.alexa_bridge.config import BridgeAuth, BridgeConfig
from custom_components.alexa_bridge.const import DOMAIN

PROACTIVE = "homeassistant.components.alexa.config.async_enable_proactive_mode"
PROACTIVE_HANDLERS = "homeassistant.components.alexa.handlers.async_enable_proactive_mode"


def _entry(hass: HomeAssistant, options: dict[str, Any] | None = None) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_CLIENT_ID: "client-id", CONF_CLIENT_SECRET: "client-secret"},
        options=options or {},
    )
    entry.add_to_hass(hass)
    return entry


async def _config(hass: HomeAssistant, options: dict[str, Any] | None = None) -> BridgeConfig:
    config = BridgeConfig(hass, _entry(hass, options))
    await config.async_initialize()
    return config


async def test_uses_own_storage_keys(hass: HomeAssistant, hass_storage: dict[str, Any]):
    config = await _config(hass)
    with patch(PROACTIVE, AsyncMock(return_value=MagicMock())):
        await config.set_authorized(True)
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=5))
    await hass.async_block_till_done()

    assert config.authorized is True
    assert hass_storage["alexa_bridge"]["data"] == {"authorized": True, "linked": True}
    assert not [key for key in hass_storage if key in ("alexa", "alexa_auth")]
    assert BridgeAuth(hass, "id", "secret")._store.key == "alexa_bridge_auth"


async def test_defaults_locale_and_endpoint(hass: HomeAssistant):
    config = await _config(hass)
    assert config.locale == "it-IT"
    assert config.endpoint == "https://api.eu.amazonalexa.com/v3/events"
    assert config.supports_auth is True
    assert config.entity_config == {}
    assert config.user_identifier() == config._entry.entry_id


async def test_should_report_state_follows_authorized(hass: HomeAssistant):
    config = await _config(hass)
    assert config.should_report_state is False
    with patch(PROACTIVE, AsyncMock(return_value=MagicMock())):
        await config.set_authorized(True)
    assert config.should_report_state is True
    assert config.is_reporting_states is True


async def test_should_expose_follows_options(hass: HomeAssistant):
    config = await _config(hass, {"domains": ["light"]})
    assert config.should_expose("light.x") is True
    assert config.should_expose("switch.y") is False


async def test_generate_alexa_id_prefers_known_ids(hass: HomeAssistant):
    config = await _config(hass)
    config.known_ids = {"light.gone": "ha-abc"}
    assert config.generate_alexa_id("light.gone") == "ha-abc"
    assert config.generate_alexa_id("light.other") == "light#other"


async def test_on_authorized_scheduled_after_accept_grant(hass: HomeAssistant):
    config = await _config(hass)
    callback = AsyncMock()
    config.on_authorized = callback
    with patch.object(BridgeAuth, "async_do_auth", AsyncMock(return_value="tok")):
        assert await config.async_accept_grant("code") == "tok"
    await hass.async_block_till_done()
    callback.assert_awaited_once_with()


async def test_set_authorized_does_not_call_on_authorized(hass: HomeAssistant):
    config = await _config(hass)
    callback = AsyncMock()
    config.on_authorized = callback
    with patch(PROACTIVE, AsyncMock(return_value=MagicMock())):
        await config.set_authorized(True)
    await hass.async_block_till_done()
    callback.assert_not_called()


async def test_on_authorized_not_called_when_grant_fails(hass: HomeAssistant):
    config = await _config(hass)
    callback = AsyncMock()
    config.on_authorized = callback
    with (
        patch.object(BridgeAuth, "async_do_auth", AsyncMock(side_effect=RuntimeError("lwa"))),
        pytest.raises(RuntimeError, match="lwa"),
    ):
        await config.async_accept_grant("code")
    await hass.async_block_till_done()
    callback.assert_not_called()


async def test_on_authorized_not_called_when_grant_returns_none(hass: HomeAssistant):
    config = await _config(hass)
    callback = AsyncMock()
    config.on_authorized = callback
    with patch.object(BridgeAuth, "async_do_auth", AsyncMock(return_value=None)):
        assert await config.async_accept_grant("code") is None
    await hass.async_block_till_done()
    callback.assert_not_called()


async def test_on_authorized_error_does_not_break_accept_grant(
    hass: HomeAssistant, caplog: pytest.LogCaptureFixture
):
    config = await _config(hass)
    callback = AsyncMock(side_effect=RuntimeError("sync boom"))
    config.on_authorized = callback
    with patch.object(BridgeAuth, "async_do_auth", AsyncMock(return_value="tok")):
        assert await config.async_accept_grant("code") == "tok"
    await hass.async_block_till_done()
    callback.assert_awaited_once()
    assert "on_authorized hook failed" in caplog.text
    assert "sync boom" in caplog.text


async def test_accept_grant_directive_then_on_authorized(hass: HomeAssistant):
    config = await _config(hass)
    order: list[str] = []

    async def do_auth(code: str) -> str:
        order.append(f"grant:{code}")
        return "tok"

    async def on_authorized() -> None:
        order.append("on_authorized")

    config.on_authorized = on_authorized
    message = {
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
    with (
        patch.object(BridgeAuth, "async_do_auth", side_effect=do_auth),
        patch(PROACTIVE, AsyncMock(return_value=MagicMock())),
        patch(PROACTIVE_HANDLERS, AsyncMock(return_value=MagicMock())),
    ):
        response = await async_handle_message(hass, config, message)
        await hass.async_block_till_done()

    assert response["event"]["header"]["name"] == "AcceptGrant.Response"
    assert response["event"]["header"]["namespace"] == "Alexa.Authorization"
    assert order == ["grant:the-code", "on_authorized"]


async def test_auth_methods_delegate_to_bridge_auth(hass: HomeAssistant):
    config = await _config(hass)
    with (
        patch.object(BridgeAuth, "async_get_access_token", AsyncMock(return_value="tok")),
        patch.object(BridgeAuth, "async_do_auth", AsyncMock(return_value="grant")) as do_auth,
        patch.object(BridgeAuth, "async_invalidate_access_token") as invalidate,
    ):
        assert await config.async_get_access_token() == "tok"
        assert await config.async_accept_grant("code") == "grant"
        config.async_invalidate_access_token()
    do_auth.assert_awaited_once_with("code")
    invalidate.assert_called_once_with()


def test_auth_strips_pasted_whitespace(hass: HomeAssistant):
    # The developer console copy button adds a space: LWA then answers 401.
    auth = BridgeAuth(hass, " client-id ", "client-secret\n")
    assert auth.client_id == "client-id"
    assert auth.client_secret == "client-secret"
