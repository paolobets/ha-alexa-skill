"""Config flow and options flow for Alexa Bridge."""

from __future__ import annotations

import asyncio
from http import HTTPStatus
from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_CLIENT_ID, CONF_CLIENT_SECRET
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    AreaSelector,
    AreaSelectorConfig,
    EntitySelector,
    EntitySelectorConfig,
    SelectSelector,
    SelectSelectorConfig,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .const import (
    CONF_AREAS,
    CONF_DOMAINS,
    CONF_ENDPOINT,
    CONF_EXCLUDE_ENTITIES,
    CONF_INCLUDE_ENTITIES,
    CONF_LOCALE,
    DEFAULT_ENDPOINT,
    DEFAULT_LOCALE,
    DOMAIN,
)
from .selection import Selection, selectable_domains, shared_entity_ids


LWA_TOKEN_URI = "https://api.amazon.com/auth/o2/token"


async def async_check_credentials(
    hass: HomeAssistant, client_id: str, client_secret: str
) -> str | None:
    """Ask Login with Amazon for a Skill Messaging token; return an error key or None."""
    data = {
        "grant_type": "client_credentials",
        "scope": "alexa:skill_messaging",
        "client_id": client_id,
        "client_secret": client_secret,
    }
    try:
        async with asyncio.timeout(10):
            response = await async_get_clientsession(hass).post(LWA_TOKEN_URI, data=data)
    except (TimeoutError, aiohttp.ClientError):
        return "cannot_connect"
    if response.status == HTTPStatus.OK:
        return None
    if response.status in (HTTPStatus.BAD_REQUEST, HTTPStatus.UNAUTHORIZED):
        return "invalid_auth"
    return "cannot_connect"


class AlexaBridgeConfigFlow(ConfigFlow, domain=DOMAIN):
    """Single-instance flow collecting the Alexa Skill Messaging credentials."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry) -> AlexaBridgeOptionsFlow:
        """Return the options flow."""
        return AlexaBridgeOptionsFlow()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the credentials."""
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()

        errors: dict[str, str] = {}
        if user_input is not None:
            user_input = {
                **user_input,
                CONF_CLIENT_ID: user_input[CONF_CLIENT_ID].strip(),
                CONF_CLIENT_SECRET: user_input[CONF_CLIENT_SECRET].strip(),
            }
            error = await async_check_credentials(
                self.hass, user_input[CONF_CLIENT_ID], user_input[CONF_CLIENT_SECRET]
            )
            if error is None:
                return self.async_create_entry(
                    title="Alexa Bridge", data=user_input, options={}
                )
            errors["base"] = error

        schema = vol.Schema(
            {
                vol.Required(CONF_CLIENT_ID): str,
                vol.Required(CONF_CLIENT_SECRET): TextSelector(
                    TextSelectorConfig(type=TextSelectorType.PASSWORD)
                ),
                vol.Required(CONF_LOCALE, default=DEFAULT_LOCALE): str,
                vol.Required(CONF_ENDPOINT, default=DEFAULT_ENDPOINT): str,
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)


class AlexaBridgeOptionsFlow(OptionsFlow):
    """Pick what to share, then confirm after seeing how many entities."""

    def __init__(self) -> None:
        """Initialize the proposed selection."""
        self._proposed: dict[str, list[str]] = {}

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Choose domains, areas and per-entity overrides."""
        if user_input is not None:
            self._proposed = {
                CONF_DOMAINS: list(user_input.get(CONF_DOMAINS, [])),
                CONF_AREAS: list(user_input.get(CONF_AREAS, [])),
                CONF_INCLUDE_ENTITIES: list(user_input.get(CONF_INCLUDE_ENTITIES, [])),
                CONF_EXCLUDE_ENTITIES: list(user_input.get(CONF_EXCLUDE_ENTITIES, [])),
            }
            return await self.async_step_confirm()

        current = self.config_entry.options
        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_DOMAINS, default=list(current.get(CONF_DOMAINS, []))
                ): SelectSelector(
                    SelectSelectorConfig(
                        options=selectable_domains(),
                        multiple=True,
                    )
                ),
                vol.Optional(
                    CONF_AREAS, default=list(current.get(CONF_AREAS, []))
                ): AreaSelector(AreaSelectorConfig(multiple=True)),
                vol.Optional(
                    CONF_INCLUDE_ENTITIES,
                    default=list(current.get(CONF_INCLUDE_ENTITIES, [])),
                ): EntitySelector(EntitySelectorConfig(multiple=True)),
                vol.Optional(
                    CONF_EXCLUDE_ENTITIES,
                    default=list(current.get(CONF_EXCLUDE_ENTITIES, [])),
                ): EntitySelector(EntitySelectorConfig(multiple=True)),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)

    async def async_step_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show how many entities will be shared; save only on confirmation."""
        if user_input is not None:
            return self.async_create_entry(data=self._proposed)

        count = len(
            shared_entity_ids(self.hass, Selection.from_options(self._proposed))
        )
        return self.async_show_form(
            step_id="confirm",
            description_placeholders={"count": str(count)},
        )
