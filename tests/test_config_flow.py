"""Tests for the config flow and the options flow."""

from homeassistant import config_entries
from homeassistant.const import CONF_CLIENT_ID, CONF_CLIENT_SECRET
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.alexa_bridge.const import (
    CONF_DOMAINS,
    CONF_ENDPOINT,
    CONF_EXCLUDE_ENTITIES,
    CONF_INCLUDE_ENTITIES,
    CONF_LOCALE,
    DEFAULT_ENDPOINT,
    DEFAULT_LOCALE,
    DOMAIN,
)
from custom_components.alexa_bridge.config_flow import LWA_TOKEN_URI

USER_INPUT = {
    CONF_CLIENT_ID: "client-id",
    CONF_CLIENT_SECRET: "client-secret",
    CONF_LOCALE: DEFAULT_LOCALE,
    CONF_ENDPOINT: DEFAULT_ENDPOINT,
}


async def test_user_flow_creates_entry_with_defaults(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """The user step stores credentials, locale and endpoint; options are empty."""
    aioclient_mock.post(LWA_TOKEN_URI, json={"access_token": "tok"})
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], USER_INPUT
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_LOCALE] == "it-IT"
    assert result["data"][CONF_ENDPOINT] == "https://api.eu.amazonalexa.com/v3/events"
    assert result["data"][CONF_CLIENT_ID] == "client-id"
    assert result["options"] == {}


async def test_user_flow_strips_credentials(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Spaces pasted around the credentials are neither stored nor sent to LWA."""
    aioclient_mock.post(LWA_TOKEN_URI, json={"access_token": "tok"})
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {**USER_INPUT, CONF_CLIENT_ID: " client-id ", CONF_CLIENT_SECRET: " client-secret "},
    )
    assert result["data"][CONF_CLIENT_ID] == "client-id"
    assert result["data"][CONF_CLIENT_SECRET] == "client-secret"
    sent = aioclient_mock.mock_calls[0][2]
    assert sent["client_id"] == "client-id"
    assert sent["client_secret"] == "client-secret"
    assert sent["scope"] == "alexa:skill_messaging"


async def test_user_flow_rejected_credentials_show_error(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Credentials refused by LWA keep the form open with invalid_auth."""
    aioclient_mock.post(LWA_TOKEN_URI, status=401, json={"error": "invalid_client"})
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}
    assert not hass.config_entries.async_entries(DOMAIN)


async def test_user_flow_lwa_unreachable_shows_error(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A network failure towards LWA is reported as cannot_connect."""
    aioclient_mock.post(LWA_TOKEN_URI, exc=TimeoutError())
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def test_single_instance(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A second flow aborts as already configured."""
    aioclient_mock.post(LWA_TOKEN_URI, json={"access_token": "tok"})
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def _entry(hass: HomeAssistant) -> MockConfigEntry:
    entry = MockConfigEntry(domain=DOMAIN, data=USER_INPUT, options={})
    entry.add_to_hass(hass)
    return entry


async def test_options_flow_shows_count_then_saves(hass: HomeAssistant) -> None:
    """The confirm step shows the count; options are saved only on confirm."""
    hass.states.async_set("light.a", "on")
    hass.states.async_set("light.b", "off")
    hass.states.async_set("switch.c", "off")
    entry = await _entry(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_DOMAINS: ["light"],
            CONF_INCLUDE_ENTITIES: [],
            CONF_EXCLUDE_ENTITIES: [],
        },
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "confirm"
    assert result["description_placeholders"]["count"] == "2"
    assert entry.options == {}

    result = await hass.config_entries.options.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_DOMAINS] == ["light"]
    assert entry.options[CONF_INCLUDE_ENTITIES] == []
    assert entry.options[CONF_EXCLUDE_ENTITIES] == []


async def test_options_domains_exclude_blocked(hass: HomeAssistant) -> None:
    """Blocked domains are not offered in the selector."""
    entry = await _entry(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    schema = result["data_schema"].schema
    selector = next(v for k, v in schema.items() if k == CONF_DOMAINS)
    options = selector.config["options"]
    assert "light" in options
    assert "automation" not in options
    assert "alarm_control_panel" not in options
