"""Heating thermostats shared with Alexa: temperature and mode, never power or OFF.

Alexa turns a room on or off through every device in it that has
Alexa.PowerController. Home Assistant's engine gives one to any climate entity
with an "off" HVAC mode, so "Alexa, turn off the study" also turns off the
study's heating, and "turn on" switches it to manual "heat". Amazon recommends
PowerController for air conditioners only ("unlike thermostats, which are
usually on all the time, users turn air conditioners on and off").

For heating-only thermostats (no cooling, drying or fan mode) the bridge
therefore drops PowerController and the OFF thermostat mode from what Alexa is
told, and refuses those directives should Alexa still send them. Climate
entities that can cool keep Home Assistant's default. Only the bridge's own
config is affected: the stock Alexa integration keeps the engine untouched.
"""

from __future__ import annotations

from collections.abc import Generator
from typing import Any

from homeassistant.components.alexa.capabilities import (
    AlexaCapability,
    AlexaPowerController,
    AlexaThermostatController,
)
from homeassistant.components.alexa.entities import ENTITY_ADAPTERS, ClimateCapabilities
from homeassistant.components.alexa.state_report import AlexaDirective
from homeassistant.components.climate import HVACMode
from homeassistant.core import HomeAssistant, State

from .config import BridgeConfig

CLIMATE_DOMAIN = "climate"
POWER_NAMESPACE = "Alexa.PowerController"
THERMOSTAT_NAMESPACE = "Alexa.ThermostatController"
ALEXA_OFF = "OFF"
_NOT_HEATING_ONLY = frozenset(
    {HVACMode.COOL, HVACMode.HEAT_COOL, HVACMode.DRY, HVACMode.FAN_ONLY}
)


def is_heating_thermostat(state: State | None) -> bool:
    """A climate entity that only heats: Alexa must not power it or set OFF."""
    if state is None or state.domain != CLIMATE_DOMAIN:
        return False
    modes = state.attributes.get("hvac_modes") or []
    return not _NOT_HEATING_ONLY.intersection(modes)


class _ThermostatControllerWithoutOff(AlexaThermostatController):
    """ThermostatController whose supported modes leave out OFF."""

    def configuration(self) -> dict[str, Any] | None:
        configuration = super().configuration()
        if configuration and "supportedModes" in configuration:
            configuration["supportedModes"] = [
                m for m in configuration["supportedModes"] if m != ALEXA_OFF
            ]
        return configuration


class BridgeClimateCapabilities(ClimateCapabilities):
    """Climate adapter: heating thermostats lose power and OFF, for the bridge only."""

    def interfaces(self) -> Generator[AlexaCapability]:
        if not (isinstance(self.config, BridgeConfig) and is_heating_thermostat(self.entity)):
            yield from super().interfaces()
            return
        for interface in super().interfaces():
            if isinstance(interface, AlexaPowerController):
                continue
            if type(interface) is AlexaThermostatController:
                yield _ThermostatControllerWithoutOff(self.hass, self.entity)
                continue
            yield interface


def install() -> None:
    """Make the engine build climate endpoints with the bridge's adapter (idempotent).

    Run at import, like the engine's own adapter registrations: discovery,
    AddOrUpdate, ChangeReport and ReportState all build their endpoints here.
    """
    ENTITY_ADAPTERS[CLIMATE_DOMAIN] = BridgeClimateCapabilities


def rejected_directive(
    hass: HomeAssistant, config: BridgeConfig, entity_id: str | None, message: dict[str, Any]
) -> dict[str, Any] | None:
    """ErrorResponse for power or OFF on a shared heating thermostat, else None.

    Entities not shared are left to the engine, which answers NO_SUCH_ENDPOINT.
    """
    if (
        entity_id is None
        or not config.should_expose(entity_id)
        or not is_heating_thermostat(hass.states.get(entity_id))
    ):
        return None
    directive = message.get("directive", {})
    header = directive.get("header", {})
    namespace = header.get("namespace")
    if namespace == POWER_NAMESPACE:
        return (
            AlexaDirective(message)
            .error(
                error_type="INVALID_DIRECTIVE",
                error_message="Heating thermostats are not turned on or off by Alexa",
            )
            .serialize()
        )
    mode = (directive.get("payload", {}).get("thermostatMode") or {}).get("value")
    if namespace == THERMOSTAT_NAMESPACE and header.get("name") == "SetThermostatMode" and mode == ALEXA_OFF:
        return (
            AlexaDirective(message)
            .error(
                namespace=THERMOSTAT_NAMESPACE,
                error_type="UNSUPPORTED_THERMOSTAT_MODE",
                error_message="Heating thermostats are not set to OFF by Alexa",
            )
            .serialize()
        )
    return None


install()
