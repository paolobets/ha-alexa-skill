"""Tests for the config flow and the options flow."""

from homeassistant import config_entries
from homeassistant.const import CONF_CLIENT_ID, CONF_CLIENT_SECRET
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

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

USER_INPUT = {
    CONF_CLIENT_ID: "client-id",
    CONF_CLIENT_SECRET: "client-secret",
    CONF_LOCALE: DEFAULT_LOCALE,
    CONF_ENDPOINT: DEFAULT_ENDPOINT,
}


async def test_user_flow_creates_entry_with_defaults(hass: HomeAssistant) -> None:
    """The user step stores credentials, locale and endpoint; options are empty."""
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


async def test_single_instance(hass: HomeAssistant) -> None:
    """A second flow aborts as already configured."""
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
